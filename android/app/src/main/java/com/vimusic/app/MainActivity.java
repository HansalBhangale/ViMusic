package com.vimusic.app;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(NativeMusicPlayerPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
