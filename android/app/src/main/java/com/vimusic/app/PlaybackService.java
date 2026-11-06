package com.vimusic.app;

import android.content.Context;

import androidx.annotation.Nullable;
import androidx.media3.common.AudioAttributes;
import androidx.media3.common.C;
import androidx.media3.common.Player;
import androidx.media3.datasource.DataSource;
import androidx.media3.datasource.DefaultHttpDataSource;
import androidx.media3.datasource.cache.CacheDataSource;
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor;
import androidx.media3.datasource.cache.SimpleCache;
import androidx.media3.database.StandaloneDatabaseProvider;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory;
import androidx.media3.session.MediaSession;
import androidx.media3.session.MediaSessionService;

import java.io.File;

/**
 * Owns audio playback independently of the WebView/activity lifecycle.
 *
 * Media3 creates the ongoing media notification and publishes transport
 * controls to Android System UI, the lock screen, Bluetooth and compatible
 * companion devices.
 */
public final class PlaybackService extends MediaSessionService {
    private static final long MAX_CACHE_BYTES = 512L * 1024L * 1024L;

    @Nullable
    private ExoPlayer player;

    @Nullable
    private MediaSession mediaSession;

    @Nullable
    private SimpleCache cache;

    @Override
    public void onCreate() {
        super.onCreate();

        File cacheDirectory = new File(getCacheDir(), "media3_audio");
        cache = new SimpleCache(
                cacheDirectory,
                new LeastRecentlyUsedCacheEvictor(MAX_CACHE_BYTES),
                new StandaloneDatabaseProvider(this)
        );

        DefaultHttpDataSource.Factory upstreamFactory =
                new DefaultHttpDataSource.Factory()
                        .setUserAgent("ViMusic/1.0 (Android)")
                        .setConnectTimeoutMs(15_000)
                        .setReadTimeoutMs(60_000)
                        .setAllowCrossProtocolRedirects(true);

        DataSource.Factory cacheDataSourceFactory =
                new CacheDataSource.Factory()
                        .setCache(cache)
                        .setUpstreamDataSourceFactory(upstreamFactory)
                        .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR);

        ExoPlayer exoPlayer = new ExoPlayer.Builder(this)
                .setMediaSourceFactory(new DefaultMediaSourceFactory(cacheDataSourceFactory))
                .setAudioAttributes(
                        new AudioAttributes.Builder()
                                .setUsage(C.USAGE_MEDIA)
                                .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
                                .build(),
                        true
                )
                .setHandleAudioBecomingNoisy(true)
                // Hold a CPU wake lock while foreground audio playback continues with screen off.
                .setWakeMode(C.WAKE_MODE_LOCAL)
                .build();

        exoPlayer.setRepeatMode(Player.REPEAT_MODE_OFF);
        player = exoPlayer;

        mediaSession = new MediaSession.Builder(this, exoPlayer)
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
            mediaSession.release();
            mediaSession = null;
        }

        if (player != null) {
            player.release();
            player = null;
        }

        if (cache != null) {
            cache.release();
            cache = null;
        }

        super.onDestroy();
    }
}
