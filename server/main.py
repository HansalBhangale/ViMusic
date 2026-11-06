import asyncio
import time
import re
import os
import tempfile
import base64
import socket
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import httpx
import yt_dlp
import uvicorn
from mutagen.mp4 import MP4, MP4Cover

app = FastAPI(title="ViMusic Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Keep normal yt-dlp output quiet, but surface extraction and PO-token errors.
class QuietLogger:
    def debug(self, msg):
        message = str(msg)
        if "pot" in message.lower() or "po token" in message.lower():
            print(f"[yt-dlp debug] {message}", flush=True)

    def info(self, msg):
        pass

    def warning(self, msg):
        print(f"[yt-dlp warning] {msg}", flush=True)

    def error(self, msg):
        print(f"[yt-dlp error] {msg}", flush=True)

# Setup optional persistent YouTube Cookies (from environment variable or file)
COOKIES_FILE = None
raw_cookies = os.environ.get("YOUTUBE_COOKIES", "").strip()
if raw_cookies:
    try:
        if os.path.isfile(raw_cookies):
            COOKIES_FILE = os.path.abspath(raw_cookies)
        else:
            cookie_content = raw_cookies
            # Support base64 encoded cookies to prevent environment newline mangling
            if not raw_cookies.startswith("#") and "\n" not in raw_cookies and len(raw_cookies) > 50:
                try:
                    decoded = base64.b64decode(raw_cookies).decode("utf-8", errors="ignore")
                    if "youtube.com" in decoded or "# Netscape" in decoded:
                        cookie_content = decoded
                except Exception:
                    pass
            temp_cookie_path = os.path.join(tempfile.gettempdir(), "yt_cookies.txt")
            with open(temp_cookie_path, "w", encoding="utf-8") as f:
                f.write(cookie_content)
            if os.path.exists(temp_cookie_path) and os.path.getsize(temp_cookie_path) > 10:
                COOKIES_FILE = temp_cookie_path
                print(f"[ViMusic] Loaded YouTube cookies from environment ({os.path.getsize(COOKIES_FILE)} bytes)")
    except Exception as e:
        print(f"[ViMusic] Failed to configure YouTube cookies: {e}")

# In-memory cache for stream URLs: video_id -> { "url": str, "expires": float, "title": str, ... }
stream_cache = {}
trending_cache = {"expires": 0, "tracks": []}

BASE_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'logger': QuietLogger(),
    'socket_timeout': 5,
    'js_runtimes': {'node': {}},
    'remote_components': {'ejs:github'},
}
if COOKIES_FILE:
    BASE_OPTS['cookiefile'] = COOKIES_FILE

ydl_search_opts = {
    **BASE_OPTS,
    'extract_flat': True,
}

@app.get("/")
async def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"status": "ok", "message": "ViMusic Backend Running"}

def _pot_provider_ready() -> bool:
    """Return True when the local bgutil PO-token HTTP server is listening."""
    try:
        with socket.create_connection(("127.0.0.1", 4416), timeout=0.5):
            return True
    except OSError:
        return False


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "engine": "vimusic-yt-streamer",
        "version": "2.7-stream-proxy",
        "ytdlp_version": getattr(yt_dlp.version, "__version__", "unknown"),
        "has_cookies": bool(COOKIES_FILE),
        "po_token_provider": "listening" if _pot_provider_ready() else "unavailable"
    }

@app.get("/api/search")
async def search(q: str, limit: int = 35):
    if not q or len(q.strip()) == 0:
        return []
    
    limit = max(5, min(limit, 60))
    loop = asyncio.get_event_loop()
    def _search():
        opts = dict(ydl_search_opts)
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"ytsearch{limit}:{q}", download=False)
            tracks = []
            for item in res.get("entries", []):
                if not item:
                    continue
                thumb = None
                if item.get("thumbnails"):
                    thumb = item["thumbnails"][-1].get("url")
                
                tracks.append({
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "artist": item.get("uploader") or item.get("channel") or "Unknown Artist",
                    "duration": item.get("duration") or 0,
                    "thumbnail": thumb or f"https://i.ytimg.com/vi/{item.get('id')}/hqdefault.jpg"
                })
            return tracks

    results = await loop.run_in_executor(None, _search)
    return results

@app.get("/api/radio/{video_id}")
async def get_radio(video_id: str, title: str = "", artist: str = ""):
    loop = asyncio.get_event_loop()
    def _fetch_radio():
        # Fast algorithmic search recommendations (prevents 502 gateway timeouts on datacenter IPs)
        clean_title = re.sub(r'\(.*?\)|\[.*?\]', '', title).strip()
        clean_artist = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip()
        query = f"{clean_artist} {clean_title} songs"
        
        search_opts = {
            **BASE_OPTS,
            'extract_flat': True,
            'socket_timeout': 4
        }
        try:
            with yt_dlp.YoutubeDL(search_opts) as ydl:
                res = ydl.extract_info(f"ytsearch10:{query}", download=False)
                tracks = []
                for item in res.get("entries", []):
                    if not item or item.get("id") == video_id:
                        continue
                    thumb = None
                    if item.get("thumbnails"):
                        thumb = item["thumbnails"][-1].get("url")
                    tracks.append({
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "artist": item.get("uploader") or item.get("channel") or "Unknown Artist",
                        "duration": item.get("duration") or 0,
                        "thumbnail": thumb or f"https://i.ytimg.com/vi/{item.get('id')}/hqdefault.jpg"
                    })
                    if len(tracks) >= 8:
                        break
                return tracks
        except Exception:
            return []

    results = await loop.run_in_executor(None, _fetch_radio)
    return results

@app.get("/api/trending")
async def get_trending():
    now = time.time()
    if trending_cache["tracks"] and trending_cache["expires"] > now:
        return trending_cache["tracks"]

    loop = asyncio.get_event_loop()
    def _fetch():
        query = "ytsearch25:top songs viral global music"
        opts = dict(ydl_search_opts)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                res = ydl.extract_info(query, download=False)
                tracks = []
                for item in res.get("entries", []):
                    if not item:
                        continue
                    dur = item.get("duration") or 0
                    if dur > 600 or dur < 60:
                        continue
                    thumb = None
                    if item.get("thumbnails"):
                        thumb = item["thumbnails"][-1].get("url")
                    tracks.append({
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "artist": item.get("uploader") or item.get("channel") or "Unknown Artist",
                        "duration": dur,
                        "thumbnail": thumb or f"https://i.ytimg.com/vi/{item.get('id')}/hqdefault.jpg"
                    })
                    if len(tracks) >= 12:
                        break
                return tracks
        except Exception:
            return []

    tracks = await loop.run_in_executor(None, _fetch)
    trending_cache["tracks"] = tracks
    trending_cache["expires"] = now + 3600
    return tracks

def get_stream_url(video_id: str):
    cached = stream_cache.get(video_id)
    now = time.time()
    if cached and cached["expires"] > now:
        return cached

    info = None
    last_err = None

    # Try mweb first: yt-dlp recommends using a PO-token provider for this client.
    # The bgutil plugin obtains tokens from the local HTTP service on 127.0.0.1:4416.
    extraction_strategies = [
        {
            **BASE_OPTS,
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'skip_download': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['mweb']
                }
            }
        },
        # Fallback client that can work for some videos without a GVS PO token.
        {
            **BASE_OPTS,
            'format': 'bestaudio/best',
            'skip_download': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android_vr']
                }
            }
        },
        # Additional client fallback.
        {
            **BASE_OPTS,
            'format': 'bestaudio/best',
            'skip_download': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv_downgraded', 'web_safari']
                }
            }
        },
        # Standard yt-dlp client selection as a final fallback.
        {
            **BASE_OPTS,
            'format': 'bestaudio/best',
            'skip_download': True
        }
    ]

    for strat in extraction_strategies:
        try:
            with yt_dlp.YoutubeDL(strat) as ydl:
                res = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                if res and res.get("url"):
                    info = res
                    break
        except Exception as e:
            last_err = e
            print(f"[STREAM] Extraction strategy failed for {video_id}: {e}", flush=True)
            continue

    if not info or not info.get("url"):
        # Auto-fallback: search for alternate clean upload via oEmbed metadata
        try:
            with httpx.Client(timeout=4.0) as client:
                oembed_res = client.get(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json")
                if oembed_res.status_code == 200:
                    meta = oembed_res.json()
                    song_title = meta.get("title", "")
                    song_author = meta.get("author_name", "")
                    search_q = f"{song_title} {song_author} audio"
                    fb_opts = {'quiet': True, 'extract_flat': True, 'logger': QuietLogger()}
                    if COOKIES_FILE:
                        fb_opts['cookiefile'] = COOKIES_FILE
                    with yt_dlp.YoutubeDL(fb_opts) as ydl:
                        s = ydl.extract_info(f"ytsearch3:{search_q}", download=False)
                        for entry in s.get("entries", []):
                            alt_id = entry.get("id")
                            if alt_id and alt_id != video_id:
                                return get_stream_url(alt_id)
        except Exception:
            pass

        raise HTTPException(status_code=500, detail=f"Failed to stream video: {last_err}")

    url = info["url"]
    thumb = None
    if info.get("thumbnails"):
        thumb = info["thumbnails"][-1].get("url")
        
    audio_ext = (info.get("ext") or "").lower()
    if audio_ext == "webm":
        mime_type = "audio/webm"
    elif audio_ext == "opus":
        mime_type = "audio/ogg"
    elif audio_ext == "mp3":
        mime_type = "audio/mpeg"
    else:
        mime_type = info.get("mime_type") or "audio/mp4"

    entry = {
        "url": url,
        # Keep the headers yt-dlp says are required for this media URL.
        "http_headers": dict(info.get("http_headers") or {}),
        "title": info.get("title", ""),
        "artist": info.get("uploader") or info.get("channel") or "Unknown Artist",
        "album": info.get("album") or "YouTube Music",
        "duration": info.get("duration", 0),
        "thumbnail": thumb or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "filesize": info.get("filesize") or info.get("filesize_approx") or 0,
        "mime_type": mime_type,
        "expires": now + 2 * 3600
    }
    stream_cache[video_id] = entry
    return entry

@app.get("/api/stream/{video_id}")
async def stream(video_id: str, request: Request):
    loop = asyncio.get_running_loop()

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=15.0,
            read=60.0,
            write=15.0,
            pool=15.0
        ),
        follow_redirects=True
    )

    async def open_upstream(stream_info):
        # YouTube media URLs may require the headers returned by yt-dlp.
        upstream_headers = {}
        extracted_headers = stream_info.get("http_headers") or {}

        blocked_headers = {
            "host",
            "connection",
            "content-length",
            "transfer-encoding",
            "range",
            "accept-encoding",
            "proxy-authorization",
            "proxy-connection"
        }

        for key, value in extracted_headers.items():
            if str(key).lower() not in blocked_headers and value is not None:
                upstream_headers[str(key)] = str(value)

        upstream_headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Linux; Android 14) "
            "AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36"
        )
        # Avoid transparent decompression so Content-Length and byte ranges
        # continue to describe the bytes being proxied.
        upstream_headers["Accept-Encoding"] = "identity"

        range_header = request.headers.get("range")
        if range_header:
            upstream_headers["Range"] = range_header

        upstream_request = client.build_request(
            "GET",
            stream_info["url"],
            headers=upstream_headers
        )
        return await client.send(upstream_request, stream=True)

    try:
        # 1. Get a playable media URL and its required request headers.
        try:
            info = await loop.run_in_executor(None, get_stream_url, video_id)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"YouTube audio extraction failed: {exc}"
            ) from exc

        if not info or not info.get("url"):
            raise HTTPException(
                status_code=502,
                detail="The extractor did not return a playable audio URL"
            )

        # 2. Request the media. Retry once if the signed URL has expired.
        try:
            upstream_response = await open_upstream(info)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not connect to the YouTube audio source: {exc}"
            ) from exc

        if upstream_response.status_code in (403, 410):
            await upstream_response.aclose()
            stream_cache.pop(video_id, None)

            try:
                info = await loop.run_in_executor(None, get_stream_url, video_id)
                upstream_response = await open_upstream(info)
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Audio URL refresh failed: {exc}"
                ) from exc

        # 3. Preserve 416 and its Content-Range for invalid client ranges.
        if upstream_response.status_code == 416:
            response_headers = {}
            content_range = upstream_response.headers.get("Content-Range")
            if content_range:
                response_headers["Content-Range"] = content_range
            await upstream_response.aclose()
            await client.aclose()
            return Response(
                status_code=416,
                content=b"",
                headers=response_headers
            )

        if upstream_response.status_code not in (200, 206):
            upstream_status = upstream_response.status_code
            preview = bytearray()
            try:
                async for chunk in upstream_response.aiter_raw(chunk_size=512):
                    preview.extend(chunk)
                    if len(preview) >= 1024:
                        break
            finally:
                await upstream_response.aclose()

            error_text = preview[:1024].decode("utf-8", errors="replace")
            raise HTTPException(
                status_code=502,
                detail=(
                    f"YouTube audio source returned HTTP {upstream_status}: "
                    f"{error_text[:300]}"
                )
            )

        # 4. Determine and forward the upstream media type.
        upstream_type = (
            upstream_response.headers.get("Content-Type", "")
            .split(";", 1)[0]
            .strip()
            .lower()
        )
        if (
            not upstream_type
            or upstream_type == "application/octet-stream"
            or upstream_type.startswith("video/")
        ):
            content_type = info.get("mime_type") or "audio/mp4"
        else:
            content_type = upstream_type

        response_headers = {
            "Content-Type": content_type,
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
            "Content-Disposition": "inline"
        }

        for header_name in ("Content-Range", "Content-Length", "ETag", "Last-Modified"):
            header_value = upstream_response.headers.get(header_name)
            if header_value:
                response_headers[header_name] = header_value

        # Use raw bytes: the upstream request asked for identity encoding,
        # so the upstream Content-Length and Range metadata stay consistent.
        async def stream_generator():
            try:
                async for chunk in upstream_response.aiter_raw(chunk_size=65536):
                    if chunk:
                        yield chunk
            finally:
                await upstream_response.aclose()
                await client.aclose()

        return StreamingResponse(
            stream_generator(),
            status_code=upstream_response.status_code,
            headers=response_headers
        )

    except HTTPException:
        await client.aclose()
        raise
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(
            status_code=502,
            detail=f"HTTP streaming error: {exc}"
        ) from exc
    except Exception as exc:
        await client.aclose()
        raise HTTPException(
            status_code=502,
            detail=f"Audio streaming proxy failed: {exc}"
        ) from exc

@app.get("/api/download/{video_id}")
async def download(video_id: str):
    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(None, get_stream_url, video_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    title = info.get("title", video_id)
    artist = info.get("artist", "Unknown Artist")
    clean_filename = re.sub(r'[\/\\:*?"<>|]', '_', f"{artist} - {title}").strip()
    
    # Download audio stream to temp file, tag with ID3/MP4, and stream back
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        headers = dict(info.get("http_headers") or {})
        headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        audio_res = await client.get(info["url"], headers=headers)
        
        # Download cover art
        cover_bytes = None
        if info.get("thumbnail"):
            try:
                cover_res = await client.get(info["thumbnail"], headers=headers)
                if cover_res.status_code == 200:
                    cover_bytes = cover_res.content
            except Exception:
                pass

        # Write to temporary file and tag
        temp_file = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
        temp_path = temp_file.name
        temp_file.write(audio_res.content)
        temp_file.close()

        try:
            # Tag with Mutagen
            mp4 = MP4(temp_path)
            mp4["\xa9nam"] = title
            mp4["\xa9ART"] = artist
            mp4["\xa9alb"] = info.get("album", "YouTube Music")
            if cover_bytes:
                mp4["covr"] = [MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
            mp4.save()
        except Exception:
            pass # Return original if tagging error

        def iterfile():
            try:
                with open(temp_path, mode="rb") as f:
                    yield from f
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

        response_headers = {
            "Content-Type": "audio/mp4",
            "Content-Disposition": f'attachment; filename="{clean_filename}.mp3"',
        }

        return StreamingResponse(
            iterfile(),
            headers=response_headers
        )

@app.get("/api/lyrics")
async def get_lyrics(artist: str = "", title: str = "", duration: int = 0):
    clean_title = re.sub(r'\(.*?\)|\[.*?\]', '', title).strip()
    clean_artist = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip()
    
    async with httpx.AsyncClient(timeout=3.5) as client:
        try:
            url = f"https://lrclib.net/api/get?artist_name={clean_artist}&track_name={clean_title}"
            if duration:
                url += f"&duration={duration}"
            res = await client.get(url)
            if res.status_code == 200:
                return res.json()
            
            search_res = await client.get(f"https://lrclib.net/api/search?q={clean_title} {clean_artist}")
            if search_res.status_code == 200:
                items = search_res.json()
                if items and len(items) > 0:
                    return items[0]
            return {"syncedLyrics": None, "plainLyrics": "No lyrics found."}
        except Exception:
            return {"syncedLyrics": None, "plainLyrics": "Error fetching lyrics."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
