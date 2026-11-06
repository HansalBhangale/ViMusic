import asyncio
import time
import re
import os
import tempfile
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

# In-memory cache for stream URLs: video_id -> { "url": str, "expires": float, "title": str, ... }
stream_cache = {}
trending_cache = {"expires": 0, "tracks": []}

ydl_search_opts = {
    'quiet': True,
    'no_warnings': True,
    'extract_flat': True,
}

ydl_extract_opts = {
    'format': 'ba[ext=m4a]/ba/b',
    'quiet': True,
    'no_warnings': True,
    'skip_download': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'tv_downgraded', 'web_embedded', 'mweb'],
            'player_skip': ['webpage']
        }
    }
}

@app.get("/")
async def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"status": "ok", "message": "ViMusic Backend Running"}

@app.get("/api/health")
def health():
    return {"status": "ok", "engine": "vimusic-yt-streamer"}

@app.get("/api/search")
async def search(q: str, limit: int = 35):
    if not q or len(q.strip()) == 0:
        return []
    
    limit = max(5, min(limit, 60))
    loop = asyncio.get_event_loop()
    def _search():
        with yt_dlp.YoutubeDL(ydl_search_opts) as ydl:
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
        # 1. Official YouTube Music algorithmic radio playlist RD{video_id}
        url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
        opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'playlist_items': '1-16'
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                res = ydl.extract_info(url, download=False)
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
                    if len(tracks) >= 12:
                        break
                if len(tracks) >= 4:
                    return tracks
        except Exception:
            pass

        # 2. Fallback search query if playlist extraction fails
        clean_title = re.sub(r'\(.*?\)|\[.*?\]', '', title).strip()
        clean_artist = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip()
        query = f"{clean_artist} {clean_title} songs similar"
        
        with yt_dlp.YoutubeDL(ydl_search_opts) as ydl:
            res = ydl.extract_info(f"ytsearch12:{query}", download=False)
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
            return tracks

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
        with yt_dlp.YoutubeDL(ydl_search_opts) as ydl:
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

    # Multi-client extraction rotation to bypass datacenter/cloud IP bot walls (e.g. Render, Railway)
    extraction_strategies = [
        # Strategy 1: Android / TV / Embedded client rotation (safest for datacenter IPs)
        {
            'format': 'ba[ext=m4a]/ba/b',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'tv_downgraded', 'web_embedded', 'mweb'],
                    'player_skip': ['webpage']
                }
            }
        },
        # Strategy 2: iOS / Mobile Web client fallback
        {
            'format': 'ba/b',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'mweb'],
                    'player_skip': ['webpage']
                }
            }
        },
        # Strategy 3: Standard extract fallback
        {
            'format': 'ba/b',
            'quiet': True,
            'no_warnings': True,
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
            continue

    if not info or not info.get("url"):
        raise HTTPException(status_code=500, detail=f"Failed to stream video: {last_err}")

    url = info["url"]
    thumb = None
    if info.get("thumbnails"):
        thumb = info["thumbnails"][-1].get("url")
        
    entry = {
        "url": url,
        "title": info.get("title", ""),
        "artist": info.get("uploader") or info.get("channel") or "Unknown Artist",
        "album": info.get("album") or "YouTube Music",
        "duration": info.get("duration", 0),
        "thumbnail": thumb or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "filesize": info.get("filesize") or info.get("filesize_approx") or 0,
        "mime_type": "audio/mp4",
        "expires": now + 4 * 3600 # 4 hours
    }
    stream_cache[video_id] = entry
    return entry

@app.get("/api/stream/{video_id}")
async def stream(video_id: str, request: Request):
    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(None, get_stream_url, video_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    stream_url = info["url"]
    range_header = request.headers.get("Range")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    if range_header:
        headers["Range"] = range_header

    client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    req = client.build_request("GET", stream_url, headers=headers)
    upstream_response = await client.send(req, stream=True)

    async def stream_generator():
        try:
            async for chunk in upstream_response.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await upstream_response.aclose()
            await client.aclose()

    content_type = upstream_response.headers.get("Content-Type", "audio/mp4")
    if "video/" in content_type:
        content_type = "audio/mp4"

    response_headers = {
        "Content-Type": content_type,
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=14400"
    }
    if "Content-Range" in upstream_response.headers:
        response_headers["Content-Range"] = upstream_response.headers["Content-Range"]
    if "Content-Length" in upstream_response.headers:
        response_headers["Content-Length"] = upstream_response.headers["Content-Length"]

    return StreamingResponse(
        stream_generator(),
        status_code=upstream_response.status_code,
        headers=response_headers
    )

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
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
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
    
    async with httpx.AsyncClient(timeout=10.0) as client:
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
