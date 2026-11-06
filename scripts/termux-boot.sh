#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

# Copy this file to ~/.termux/boot/start-vimusic and install Termux:Boot.
sleep 15
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock || true
fi
sv-enable vimusic
sv up vimusic
