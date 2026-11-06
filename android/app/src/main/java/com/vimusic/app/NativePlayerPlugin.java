package com.vimusic.app;

import android.content.ComponentName;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import androidx.core.content.ContextCompat;
import androidx.media3.common.C;
import androidx.media3.common.MediaItem;
import androidx.media3.common.MediaMetadata;
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

/** JavaScript bridge to the service-owned Media3 player. */
@CapacitorPlugin(name = "NativePlayer")
public final class NativePlayerPlugin extends Plugin implements Player.Listener {
    private static final String TAG = "NativePlayerPlugin";
    private static final long PROGRESS_INTERVAL_MS = 500L;
    private MediaController controller;
    private ListenableFuture<MediaController> controllerFuture;
    private boolean listenerAttached;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final Runnable progressTicker = new Runnable() {
        @Override public void run() {
            emitProgress();
            mainHandler.postDelayed(this, PROGRESS_INTERVAL_MS);
        }
    };

    private interface ControllerAction { void run(MediaController player) throws Exception; }

    @Override public void load() {
        super.load();
        connectController();
        mainHandler.post(progressTicker);
    }

    private void connectController() {
        if (controller != null || controllerFuture != null) return;
        SessionToken token = new SessionToken(
            getContext(), new ComponentName(getContext(), NativePlaybackService.class)
        );
        controllerFuture = new MediaController.Builder(getContext(), token).buildAsync();
        controllerFuture.addListener(() -> {
            try {
                attachController(controllerFuture.get());
            } catch (Exception error) {
                Log.e(TAG, "Could not connect to Media3 service", error);
                JSObject event = new JSObject();
                event.put("message", safeMessage(error));
                notifyListeners("playbackError", event);
            }
        }, ContextCompat.getMainExecutor(getContext()));
    }

    private void attachController(MediaController value) {
        if (value == null) return;
        if (controller != value) {
            controller = value;
            listenerAttached = false;
        }
        if (!listenerAttached) {
            controller.addListener(this);
            listenerAttached = true;
        }
        emitPlaybackState();
        emitProgress();
    }

    private void withController(PluginCall call, ControllerAction action) {
        connectController();
        if (controller != null) {
            try { action.run(controller); }
            catch (Exception error) { call.reject(safeMessage(error)); }
            return;
        }
        ListenableFuture<MediaController> future = controllerFuture;
        if (future == null) {
            call.reject("Native playback service is unavailable.");
            return;
        }
        future.addListener(() -> {
            try {
                attachController(future.get());
                if (controller == null) {
                    call.reject("Could not connect to native playback service.");
                    return;
                }
                action.run(controller);
            } catch (Exception error) {
                call.reject(safeMessage(error));
            }
        }, ContextCompat.getMainExecutor(getContext()));
    }

    private static String safeMessage(Throwable error) {
        Throwable cause = error;
        while (cause.getCause() != null) cause = cause.getCause();
        String message = cause.getMessage();
        return message == null || message.trim().isEmpty()
            ? cause.getClass().getSimpleName() : message;
    }

    private List<MediaItem> parseMediaItems(JSArray tracks) throws JSONException {
        List<MediaItem> items = new ArrayList<>();
        if (tracks == null) return items;
        for (int i = 0; i < tracks.length(); i++) {
            JSONObject track = tracks.getJSONObject(i);
            if (track == null) continue;
            String id = track.optString("id", "");
            String url = track.optString("url", "");
            if (id.isEmpty() || url.isEmpty()) continue;
            String title = track.optString("title", "Unknown title");
            String artist = track.optString("artist", "Unknown artist");
            String artwork = track.optString("artwork", "");
            MediaMetadata.Builder metadata = new MediaMetadata.Builder()
                .setTitle(title)
                .setArtist(artist)
                .setAlbumTitle("ViMusic");
            if (!artwork.isEmpty()) metadata.setArtworkUri(Uri.parse(artwork));
            items.add(new MediaItem.Builder()
                .setMediaId(id)
                .setUri(Uri.parse(url))
                .setMediaMetadata(metadata.build())
                .build());
        }
        return items;
    }

    private JSObject statePayload() {
        JSObject result = new JSObject();
        if (controller == null) {
            result.put("isPlaying", false);
            result.put("playWhenReady", false);
            result.put("playbackState", "idle");
            result.put("currentIndex", -1);
            result.put("currentMediaId", "");
            result.put("positionMs", 0L);
            result.put("durationMs", 0L);
            result.put("mediaItemCount", 0);
            return result;
        }
        MediaItem current = controller.getCurrentMediaItem();
        long duration = controller.getDuration();
        result.put("isPlaying", controller.isPlaying());
        result.put("playWhenReady", controller.getPlayWhenReady());
        result.put("playbackState", playbackStateName(controller.getPlaybackState()));
        result.put("currentIndex", controller.getCurrentMediaItemIndex());
        result.put("currentMediaId", current == null ? "" : current.mediaId);
        result.put("title", current == null || current.mediaMetadata.title == null
            ? "" : current.mediaMetadata.title.toString());
        result.put("artist", current == null || current.mediaMetadata.artist == null
            ? "" : current.mediaMetadata.artist.toString());
        result.put("positionMs", Math.max(0L, controller.getCurrentPosition()));
        result.put("durationMs", duration == C.TIME_UNSET ? 0L : Math.max(0L, duration));
        result.put("mediaItemCount", controller.getMediaItemCount());
        result.put("repeatMode", controller.getRepeatMode());
        result.put("shuffleEnabled", controller.getShuffleModeEnabled());
        return result;
    }

    private static String playbackStateName(int value) {
        switch (value) {
            case Player.STATE_BUFFERING: return "buffering";
            case Player.STATE_READY: return "ready";
            case Player.STATE_ENDED: return "ended";
            case Player.STATE_IDLE:
            default: return "idle";
        }
    }

    private void emitPlaybackState() {
        notifyListeners("playbackState", statePayload());
    }

    private void emitProgress() {
        if (controller == null) return;
        JSObject event = new JSObject();
        long duration = controller.getDuration();
        event.put("positionMs", Math.max(0L, controller.getCurrentPosition()));
        event.put("durationMs", duration == C.TIME_UNSET ? 0L : Math.max(0L, duration));
        event.put("isPlaying", controller.isPlaying());
        notifyListeners("playbackProgress", event);
    }

    @PluginMethod public void setQueue(PluginCall call) {
        final List<MediaItem> items;
        try { items = parseMediaItems(call.getArray("tracks")); }
        catch (JSONException error) {
            call.reject("Invalid queue data: " + safeMessage(error));
            return;
        }
        if (items.isEmpty()) {
            call.reject("The queue contains no valid audio items.");
            return;
        }
        int requestedIndex = call.getInt("startIndex", 0);
        long startPositionMs = call.getLong("startPositionMs", 0L);
        boolean playWhenReady = call.getBoolean("playWhenReady", true);
        withController(call, player -> {
            int index = Math.max(0, Math.min(requestedIndex, items.size() - 1));
            player.setMediaItems(items, index, Math.max(0L, startPositionMs));
            player.prepare();
            if (playWhenReady) player.play(); else player.pause();
            call.resolve(statePayload());
        });
    }

    @PluginMethod public void addToQueue(PluginCall call) {
        final List<MediaItem> items;
        try { items = parseMediaItems(call.getArray("tracks")); }
        catch (JSONException error) {
            call.reject("Invalid queue data: " + safeMessage(error));
            return;
        }
        withController(call, player -> {
            if (!items.isEmpty()) player.addMediaItems(items);
            call.resolve(statePayload());
        });
    }

    @PluginMethod public void play(PluginCall call) {
        withController(call, player -> { player.play(); call.resolve(statePayload()); });
    }

    @PluginMethod public void pause(PluginCall call) {
        withController(call, player -> { player.pause(); call.resolve(statePayload()); });
    }

    @PluginMethod public void skipToNext(PluginCall call) {
        withController(call, player -> {
            if (player.hasNextMediaItem()) player.seekToNextMediaItem();
            call.resolve(statePayload());
        });
    }

    @PluginMethod public void skipToPrevious(PluginCall call) {
        withController(call, player -> {
            if (player.hasPreviousMediaItem()) player.seekToPreviousMediaItem();
            else player.seekTo(0L);
            call.resolve(statePayload());
        });
    }

    @PluginMethod public void seekTo(PluginCall call) {
        long positionMs = call.getLong("positionMs", 0L);
        withController(call, player -> {
            player.seekTo(Math.max(0L, positionMs));
            call.resolve(statePayload());
        });
    }

    @PluginMethod public void setVolume(PluginCall call) {
        double requested = call.getDouble("volume", 1.0);
        float volume = (float) Math.max(0.0, Math.min(1.0, requested));
        withController(call, player -> { player.setVolume(volume); call.resolve(statePayload()); });
    }

    @PluginMethod public void setPlaybackRate(PluginCall call) {
        double requested = call.getDouble("rate", 1.0);
        float rate = (float) Math.max(0.5, Math.min(2.0, requested));
        withController(call, player -> {
            player.setPlaybackParameters(new PlaybackParameters(rate));
            call.resolve(statePayload());
        });
    }

    @PluginMethod public void setRepeatMode(PluginCall call) {
        String mode = call.getString("mode", "off");
        int repeatMode = "one".equals(mode) ? Player.REPEAT_MODE_ONE
            : ("all".equals(mode) ? Player.REPEAT_MODE_ALL : Player.REPEAT_MODE_OFF);
        withController(call, player -> { player.setRepeatMode(repeatMode); call.resolve(statePayload()); });
    }

    @PluginMethod public void setShuffleEnabled(PluginCall call) {
        boolean enabled = call.getBoolean("enabled", false);
        withController(call, player -> { player.setShuffleModeEnabled(enabled); call.resolve(statePayload()); });
    }

    @PluginMethod public void clearQueue(PluginCall call) {
        withController(call, player -> {
            player.stop();
            player.clearMediaItems();
            call.resolve(statePayload());
        });
    }

    @PluginMethod public void getState(PluginCall call) {
        withController(call, player -> call.resolve(statePayload()));
    }

    @Override public void onIsPlayingChanged(boolean isPlaying) { emitPlaybackState(); }
    @Override public void onPlaybackStateChanged(int playbackState) { emitPlaybackState(); }

    @Override public void onMediaItemTransition(MediaItem mediaItem, int reason) {
        JSObject event = statePayload();
        event.put("reason", reason);
        notifyListeners("trackChanged", event);
        emitPlaybackState();
    }

    @Override public void onPlayerError(androidx.media3.common.PlaybackException error) {
        JSObject event = new JSObject();
        event.put("message", error.getMessage() == null ? "Audio playback failed." : error.getMessage());
        event.put("errorCode", error.errorCode);
        notifyListeners("playbackError", event);
        emitPlaybackState();
    }

    @Override protected void handleOnDestroy() {
        mainHandler.removeCallbacks(progressTicker);
        if (controllerFuture != null) {
            if (controller != null) {
                controller.removeListener(this);
            }
            // The future owns the controller instance; release it exactly once.
            MediaController.releaseFuture(controllerFuture);
            controllerFuture = null;
            controller = null;
        } else if (controller != null) {
            controller.removeListener(this);
            controller.release();
            controller = null;
        }
        super.handleOnDestroy();
    }
}
