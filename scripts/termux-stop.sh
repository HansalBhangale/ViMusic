#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

if command -v sv >/dev/null 2>&1; then
  sv down vimusic || true
fi

if command -v termux-wake-unlock >/dev/null 2>&1; then
  termux-wake-unlock || true
fi

echo "ViMusic service stopped."
