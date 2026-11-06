# ViMusic on Android with Termux + Chrome

This deployment runs the Starlette-based API app on the same Android phone as Chrome. It binds to
`127.0.0.1:8765`, so the server is not exposed to other devices on the Wi-Fi network.

## 1. Install Termux

Install the current Termux release from one source only:

- F-Droid: https://f-droid.org/packages/com.termux/
- Official GitHub releases: https://github.com/termux/termux-app/releases

Do not mix Termux and its add-ons from different sources. Their APK signing keys
must match. Open Termux once after installation.

## 2. Clone the phone deployment branch

In Termux:

```bash
pkg update && pkg upgrade -y
pkg install -y git
git clone --branch termux/phone-local --depth 1 https://github.com/HansalBhangale/ViMusic.git ~/ViMusic
cd ~/ViMusic
bash scripts/termux-install.sh
```

After setup, close the Termux session completely and reopen Termux. This lets the
`termux-services` runit daemon start.

## 3. Enable and start ViMusic

```bash
sv-enable vimusic
bash ~/ViMusic/scripts/termux-start.sh
```

Check health:

```bash
bash ~/ViMusic/scripts/termux-status.sh
```

The health endpoint should answer at `http://127.0.0.1:8765/api/health`.

Stop the server:

```bash
bash ~/ViMusic/scripts/termux-stop.sh
```

View logs:

```bash
tail -f ~/.local/state/vimusic/log/current
```

## 4. Install the Chrome home-screen app

1. Start the ViMusic service.
2. Open Chrome on the same phone.
3. Visit `http://127.0.0.1:8765`.
4. Open Chrome's menu and choose **Install app** or **Add to Home screen**.
5. Launch ViMusic from the new home-screen icon.

The PWA caches only its basic app shell. API responses and audio streams are deliberately
not cached. A network connection is still required for online catalogue features.

## 5. OnePlus / OxygenOS background settings

For best reliability, open:

**Settings → Apps → App management → Termux → Battery usage**

Enable **Allow background activity** and **Allow auto-launch** if those switches are
available on your model/build.

Also check:

**Settings → Apps → Special app access → Battery optimization**

Show all apps, select Termux, and choose **Don't optimize** (wording can vary).
If your OxygenOS build offers a **Lock** action for Termux in Recents, use it.
Repeat these checks for Termux:Boot if you install it.

These settings reduce the chance that OxygenOS stops the local server; Android can
still terminate background processes under resource pressure.

## 6. Optional: keep CPU awake

For longer screen-off sessions, install the Termux:API add-on from the same source
as Termux, then in Termux run:

```bash
pkg install termux-api
```

The start script uses `termux-wake-lock` automatically when available. A wake lock
uses additional battery; the phone may become warm during long sessions.

## 7. Optional: start after phone reboot

Install Termux:Boot from the same source/signing channel as Termux. Open Termux:Boot
once, then in Termux run:

```bash
mkdir -p ~/.termux/boot
cp ~/ViMusic/scripts/termux-boot.sh ~/.termux/boot/start-vimusic
chmod 700 ~/.termux/boot/start-vimusic
```

Enable background activity / battery exemption for Termux:Boot as well.

## 8. Wi-Fi and mobile data

The local app always uses `127.0.0.1`; it does not need your phone's LAN address.
You can use Wi-Fi or mobile data. Outbound requests from Termux use Android's
currently active network route. When switching networks, a stream already in progress
may disconnect; restart the track or the ViMusic service if it does not recover.

Do not change the Uvicorn host to `0.0.0.0` for this phone-only setup. Doing so
would expose the API to other devices on the same network.

## Notes and limitations

- The Termux requirements intentionally omit FastAPI/Pydantic (the API uses Starlette directly) and the Docker-based bgutil service. The
  existing health endpoint will report the PO-token provider as unavailable.
- This deployment does not alter the YouTube extractor or guarantee that YouTube
  will accept a request. A mobile/residential IP is not a guarantee against bot checks,
  IP restrictions, rate limits, or player-client changes.
- This local hosting setup does not make unofficial audio extraction an official
  YouTube integration and does not override YouTube's platform terms.
- Your Render/Docker deployment remains on the `main` branch; this setup is isolated
  on `termux/phone-local`.
