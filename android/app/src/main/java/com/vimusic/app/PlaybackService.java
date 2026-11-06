package com.vimusic.app;

import androidx.annotation.Nullable;
import androidx.media3.common.AudioAttributes;
import androidx.media3.common.C;
import androidx.media3.common.Player;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.session.MediaSession;
import androidx.media3.session.MediaSessionService;

/**
 * Owns the audio player independently of the WebView/activity lifecycle.
 *
 * Media3's MediaSessionService manages the media notification and exposes a
 * session to Android System UI, Bluetooth controls and lock-screen controls.
 */
public final class PlaybackService extends MediaSessionService {
    @Nullable
    private ExoPlayer player;

    @Nullable
    private MediaSession mediaSession;

    @Override
    public void onCreate() {
        super.onCreate();

        AudioAttributes audioAttributes = new AudioAttributes.Builder()
                .setUsage(C.USAGE_MEDIA)
                .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
                .build();

        player = new ExoPlayer.Builder(this)
                .setAudioAttributes(audioAttributes, true)
                .setHandleAudioBecomingNoisy(true)
                .build();

        player.setRepeatMode(Player.REPEAT_MODE_OFF);

        mediaSession = new MediaSession.Builder(this, player)
                .setId("ViMusicPlayback")
                .build();
    }

    @Nullable
    @Override
    public MediaSession onGetSession(MediaSession.ControllerInfo controllerInfo) {
        return mediaSession;
    }

    @Override
    public void onDestroy() {
        if (mediaSession != null) {
            mediaSession.getPlayer().release();
            mediaSession.release();
            mediaSession = null;
            player = null;
        } else if (player != null) {
            player.release();
            player = null;
        }

        super.onDestroy();
    }
}
