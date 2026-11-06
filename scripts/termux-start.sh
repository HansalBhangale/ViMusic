#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

if ! command -v sv >/dev/null 2>&1 || ! command -v sv-enable >/dev/null 2>&1; then
  echo "termux-services is not ready. Close and reopen Termux, then retry."
  exit 1
fi

sv-enable vimusic
sv up vimusic

if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock || true
fi

for attempt in $(seq 1 20); do
  if curl --silent --fail http://127.0.0.1:8765/api/health >/dev/null; then
    echo "ViMusic is running: http://127.0.0.1:8765"
    echo "Status: bash ~/ViMusic/scripts/termux-status.sh"
    echo "Stop:   bash ~/ViMusic/scripts/termux-stop.sh"
    exit 0
  fi
  sleep 1
done

echo "ViMusic did not become ready. Recent service log:"
tail -n 80 "$HOME/.local/state/vimusic/log/current" 2>/dev/null || true
exit 1
