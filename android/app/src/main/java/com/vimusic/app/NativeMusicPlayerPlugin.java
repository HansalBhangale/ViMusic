package com.vimusic.app;

import android.content.ComponentName;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.media3.common.MediaItem;
import androidx.media3.common.MediaMetadata;
import androidx.media3.common.PlaybackException;
import androidx.media3.common.PlaybackParameters;
import androidx.media3.common.Player;
import androidx.media3.session.MediaController;
import androidx.media3.session.SessionToken;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.google.common.util.concurrent.ListenableFuture;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutionException;

/**
 * Capacitor bridge to the process-independent Media3 playback service.
 *
 * The JavaScript UI sends playable stream URLs and metadata. This class does
 * not extract, download or transform media; the selected source provider is
 * responsible for returning a URL the app is authorized to play.
 */
@CapacitorPlugin(name = "NativeMusicPlayer")
public final class NativeMusicPlayerPlugin extends Plugin implements Player.Listener {
    private static final String TAG = "NativeMusicPlayer";

    @Nullable
    private volatile MediaController controller;

    @Nullable
    private ListenableFuture<MediaController> controllerFuture;

    private final Handler progressHandler = new Handler(Looper.getMainLooper());

    private final Runnable progressTicker = new Runnable() {
        @Override
        public void run() {
            MediaController current = controller;
            if (current == null || !current.isPlaying()) {
                return;
            }
            notifyListeners("playbackProgress", snapshot(current));
            progressHandler.postDelayed(this, 500L);
        }
    };

    @Override
    public void load() {
        super.load();
        connectController();
    }

    private synchronized void connectController() {
        if (controller != null || controllerFuture != null) {
            return;
        }

        SessionToken sessionToken = new SessionToken(
                getContext(),
                new ComponentName(getContext(), PlaybackService.class)
        );

        ListenableFuture<MediaController> future =
                new MediaController.Builder(getContext(), sessionToken).buildAsync();
        controllerFuture = future;

        future.addListener(() -> {
            try {
                MediaController connected = future.get();
                controller = connected;
                connected.addListener(this);
                notifyListeners("playbackState", snapshot(connected));
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                Log.e(TAG, "Interrupted while connecting to PlaybackService", error);
                notifyPlaybackError("INTERRUPTED", error.getMessage());
            } catch (ExecutionException error) {
                Log.e(TAG, "Unable to connect to PlaybackService", error);
                notifyPlaybackError("SERVICE_CONNECTION", error.getCause() != null
                        ? error.getCause().getMessage()
                        : error.getMessage());
            }
        }, ContextCompat.getMainExecutor(getContext()));
    }

    private void notifyPlaybackError(@NonNull String code, @Nullable String message) {
        JSObject event = new JSObject();
        event.put("code", code);
        event.put("message", message != null ? message : "Native playback service error");
        notifyListeners("playbackError", event);
    }

    private interface ControllerAction {
        void run(@NonNull MediaController mediaController) throws Exception;
    }

    private void withController(@NonNull PluginCall call, @NonNull ControllerAction action) {
        MediaController ready = controller;
        if (ready != null) {
            try {
                action.run(ready);
            } catch (Exception error) {
                Log.e(TAG, "Native player command failed", error);
                call.reject(error.getMessage() != null ? error.getMessage() : "Native player command failed");
            }
            return;
        }

        connectController();
        ListenableFuture<MediaController> pending = controllerFuture;
        if (pending == null) {
            call.reject("Playback service is not available");
            return;
        }

        pending.addListener(() -> {
            try {
                MediaController connected = pending.get();
                controller = connected;
                if (!connected.isCommandAvailable(Player.COMMAND_GET_CURRENT_MEDIA_ITEM)) {
                    call.reject("Playback service connected without a usable player");
                    return;
                }
                action.run(connected);
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                call.reject("Interrupted while connecting to the playback service");
            } catch (ExecutionException error) {
                call.reject(error.getCause() != null
                        ? error.getCause().getMessage()
                        : "Unable to connect to the playback service");
            } catch (Exception error) {
                call.reject(error.getMessage() != null
                        ? error.getMessage()
                        : "Native player command failed");
            }
        }, ContextCompat.getMainExecutor(getContext()));
    }

    private List<MediaItem> parseTracks(@Nullable JSArray tracks) throws JSONException {
        List<MediaItem> items = new ArrayList<>();

        if (tracks == null) {
            return items;
        }

        for (int index = 0; index < tracks.length(); index++) {
            JSONObject track = tracks.getJSONObject(index);

            String id = track.optString("id", "").trim();
            String streamUrl = track.optString("streamUrl", "").trim();

            if (id.isEmpty()) {
                throw new JSONException("Track at index " + index + " is missing its id");
            }
            if (streamUrl.isEmpty()) {
                throw new JSONException("Track at index " + index + " is missing streamUrl");
            }

            MediaMetadata.Builder metadata = new MediaMetadata.Builder()
                    .setTitle(track.optString("title", "Unknown title"))
                    .setArtist(track.optString("artist", "Unknown artist"));

            String album = track.optString("album", "");
            if (!album.isEmpty()) {
                metadata.setAlbumTitle(album);
            }

            String artworkUrl = track.optString("artworkUrl", "");
            if (!artworkUrl.isEmpty()) {
                metadata.setArtworkUri(Uri.parse(artworkUrl));
            }

            MediaItem.Builder item = new MediaItem.Builder()
                    .setMediaId(id)
                    .setUri(Uri.parse(streamUrl))
                    .setCustomCacheKey(id)
                    .setMediaMetadata(metadata.build());

            String mimeType = track.optString("mimeType", "");
            if (!mimeType.isEmpty()) {
                item.setMimeType(mimeType);
            }

            items.add(item.build());
        }

        return items;
    }

    private JSObject snapshot(@NonNull Player player) {
        JSObject result = new JSObject();

        result.put("isPlaying", player.isPlaying());
        result.put("playWhenReady", player.getPlayWhenReady());
        result.put("playbackState", player.getPlaybackState());
        result.put("currentPosition", player.getCurrentPosition());
        result.put("bufferedPosition", player.getBufferedPosition());
        result.put("duration", player.getDuration() < 0 ? 0 : player.getDuration());
        result.put("currentMediaItemIndex", player.getCurrentMediaItemIndex());
        result.put("mediaItemCount", player.getMediaItemCount());
        result.put("repeatMode", player.getRepeatMode());
        result.put("shuffleEnabled", player.getShuffleModeEnabled());

        MediaItem current = player.getCurrentMediaItem();
        if (current != null) {
            result.put("mediaId", current.mediaId);
            result.put("title", current.mediaMetadata.title != null
                    ? current.mediaMetadata.title.toString()
                    : "");
            result.put("artist", current.mediaMetadata.artist != null
                    ? current.mediaMetadata.artist.toString()
                    : "");
            result.put("artworkUrl", current.mediaMetadata.artworkUri != null
                    ? current.mediaMetadata.artworkUri.toString()
                    : "");
        } else {
            result.put("mediaId", JSONObject.NULL);
            result.put("title", "");
            result.put("artist", "");
            result.put("artworkUrl", "");
        }

        return result;
    }

    @PluginMethod
    public void setQueue(PluginCall call) {
        withController(call, mediaController -> {
            JSArray tracks = call.getArray("tracks");
            List<MediaItem> items = parseTracks(tracks);

            if (items.isEmpty()) {
                throw new IllegalArgumentException("Queue must contain at least one playable track");
            }

            int requestedIndex = call.getInt("startIndex", 0);
            int startIndex = Math.max(0, Math.min(requestedIndex, items.size() - 1));
            long positionMs = Math.max(0L, call.getLong("positionMs", 0L));
            boolean playWhenReady = call.getBoolean("playWhenReady", true);

            mediaController.setMediaItems(items, startIndex, positionMs);
            mediaController.prepare();

            if (playWhenReady) {
                mediaController.play();
            } else {
                mediaController.pause();
            }

            boolean shuffle = call.getBoolean("shuffleEnabled", false);
            mediaController.setShuffleModeEnabled(shuffle);

            String repeat = call.getString("repeatMode", "off");
            applyRepeatMode(mediaController, repeat);

            call.resolve(snapshot(mediaController));
        });
    }

    @PluginMethod
    public void appendToQueue(PluginCall call) {
        withController(call, mediaController -> {
            List<MediaItem> items = parseTracks(call.getArray("tracks"));
            if (items.isEmpty()) {
                call.resolve(snapshot(mediaController));
                return;
            }

            if (mediaController.getMediaItemCount() == 0) {
                mediaController.setMediaItems(items);
                mediaController.prepare();
                mediaController.play();
            } else {
                mediaController.addMediaItems(items);
            }

            call.resolve(snapshot(mediaController));
        });
    }

    @PluginMethod
    public void play(PluginCall call) {
        withController(call, mediaController -> {
            mediaController.play();
            call.resolve(snapshot(mediaController));
        });
    }

    @PluginMethod
    public void pause(PluginCall call) {
        withController(call, mediaController -> {
            mediaController.pause();
            call.resolve(snapshot(mediaController));
        });
    }

    @PluginMethod
    public void seekTo(PluginCall call) {
        withController(call, mediaController -> {
            long positionMs = Math.max(0L, call.getLong("positionMs", 0L));
            mediaController.seekTo(positionMs);
            call.resolve(snapshot(mediaController));
        });
    }

    @PluginMethod
    public void seekToNext(PluginCall call) {
        withController(call, mediaController -> {
            int count = mediaController.getMediaItemCount();
            int index = mediaController.getCurrentMediaItemIndex();

            if (count > 0 && mediaController.getRepeatMode() == Player.REPEAT_MODE_ONE) {
                mediaController.seekTo(index, 0L);
            } else if (mediaController.hasNextMediaItem()) {
                mediaController.seekToNextMediaItem();
            } else if (count > 0 && mediaController.getRepeatMode() == Player.REPEAT_MODE_ALL) {
                mediaController.seekTo(0, 0L);
            }

            call.resolve(snapshot(mediaController));
        });
    }

    @PluginMethod
    public void seekToPrevious(PluginCall call) {
        withController(call, mediaController -> {
            int count = mediaController.getMediaItemCount();
            int index = mediaController.getCurrentMediaItemIndex();

            if (mediaController.getCurrentPosition() > 4000L) {
                mediaController.seekTo(0L);
            } else if (mediaController.hasPreviousMediaItem()) {
                mediaController.seekToPreviousMediaItem();
            } else if (count > 0 && mediaController.getRepeatMode() == Player.REPEAT_MODE_ALL) {
                mediaController.seekTo(count - 1, 0L);
            } else if (count > 0) {
                mediaController.seekTo(index, 0L);
            }

            call.resolve(snapshot(mediaController));
        });
    }

    @PluginMethod
    public void clearQueue(PluginCall call) {
        withController(call, mediaController -> {
            mediaController.stop();
            mediaController.clearMediaItems();
            call.resolve(snapshot(mediaController));
        });
    }

    @PluginMethod
    public void setRepeatMode(PluginCall call) {
        withController(call, mediaController -> {
            applyRepeatMode(mediaController, call.getString("repeatMode", "off"));
            call.resolve(snapshot(mediaController));
        });
    }

    private void applyRepeatMode(@NonNull MediaController mediaController, @Nullable String repeatMode) {
        if ("one".equalsIgnoreCase(repeatMode)) {
            mediaController.setRepeatMode(Player.REPEAT_MODE_ONE);
        } else if ("all".equalsIgnoreCase(repeatMode)) {
            mediaController.setRepeatMode(Player.REPEAT_MODE_ALL);
        } else {
            mediaController.setRepeatMode(Player.REPEAT_MODE_OFF);
        }
    }

    @PluginMethod
    public void setShuffleEnabled(PluginCall call) {
        withController(call, mediaController -> {
            mediaController.setShuffleModeEnabled(call.getBoolean("enabled", false));
            call.resolve(snapshot(mediaController));
        });
    }

    @PluginMethod
    public void setPlaybackSpeed(PluginCall call) {
        withController(call, mediaController -> {
            float speed = call.getFloat("speed", 1.0f);
            if (speed < 0.25f || speed > 3.0f) {
                throw new IllegalArgumentException("Playback speed must be between 0.25 and 3.0");
            }
            mediaController.setPlaybackParameters(new PlaybackParameters(speed));
            call.resolve(snapshot(mediaController));
        });
    }

    @PluginMethod
    public void setVolume(PluginCall call) {
        withController(call, mediaController -> {
            float volume = call.getFloat("volume", 1.0f);
            if (volume < 0.0f || volume > 1.0f) {
                throw new IllegalArgumentException("Volume must be between 0 and 1");
            }
            mediaController.setVolume(volume);
            call.resolve(snapshot(mediaController));
        });
    }

    @PluginMethod
    public void getState(PluginCall call) {
        withController(call, mediaController -> call.resolve(snapshot(mediaController)));
    }

    @PluginMethod
    public void getQueue(PluginCall call) {
        withController(call, mediaController -> {
            JSArray tracks = new JSArray();

            for (int index = 0; index < mediaController.getMediaItemCount(); index++) {
                MediaItem item = mediaController.getMediaItemAt(index);
                JSObject track = new JSObject();

                track.put("id", item.mediaId);
                track.put("title", item.mediaMetadata.title != null
                        ? item.mediaMetadata.title.toString()
                        : "");
                track.put("artist", item.mediaMetadata.artist != null
                        ? item.mediaMetadata.artist.toString()
                        : "");
                track.put("thumbnail", item.mediaMetadata.artworkUri != null
                        ? item.mediaMetadata.artworkUri.toString()
                        : "");
                track.put("streamUrl", item.localConfiguration != null
                        ? item.localConfiguration.uri.toString()
                        : "");

                tracks.put(track);
            }

            JSObject result = snapshot(mediaController);
            result.put("tracks", tracks);
            call.resolve(result);
        });
    }

    private void updateProgressTicker() {
        progressHandler.removeCallbacks(progressTicker);
        MediaController current = controller;
        if (current != null && current.isPlaying()) {
            progressHandler.postDelayed(progressTicker, 500L);
        }
    }

    @Override
    protected void handleOnDestroy() {
        progressHandler.removeCallbacksAndMessages(null);

        if (controller != null) {
            controller.removeListener(this);
        }

        if (controllerFuture != null) {
            MediaController.releaseFuture(controllerFuture);
            controllerFuture = null;
            controller = null;
        }

        super.handleOnDestroy();
    }

    @Override
    public void onEvents(@NonNull Player player, @NonNull Player.Events events) {
        notifyListeners("playbackState", snapshot(player));
        updateProgressTicker();
    }

    @Override
    public void onMediaItemTransition(@Nullable MediaItem mediaItem, int reason) {
        MediaController current = controller;
        if (current != null) {
            notifyListeners("trackChanged", snapshot(current));
            updateProgressTicker();
        }
    }

    @Override
    public void onPlayerError(@NonNull PlaybackException error) {
        JSObject event = new JSObject();
        event.put("code", error.errorCode);
        event.put("message", error.getMessage() != null ? error.getMessage() : "Audio playback failed");
        notifyListeners("playbackError", event);
        updateProgressTicker();
    }
}
