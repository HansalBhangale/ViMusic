#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

if command -v sv >/dev/null 2>&1; then
  sv status vimusic || true
fi

echo
if curl --silent --show-error --fail http://127.0.0.1:8765/api/health; then
  echo
  echo "Open in Chrome: http://127.0.0.1:8765"
else
  echo "Local API is not responding."
  exit 1
fi
