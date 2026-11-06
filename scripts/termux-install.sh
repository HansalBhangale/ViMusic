#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== ViMusic Termux setup =="
pkg update -y
pkg upgrade -y
pkg install -y python git nodejs-lts ffmpeg curl termux-services

cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
  python -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip

# Remove the previous FastAPI/Pydantic attempt if it exists. Termux now uses
# Starlette directly, so pydantic-core and its Rust/maturin build are unnecessary.
.venv/bin/python -m pip uninstall -y fastapi pydantic pydantic-core || true

.venv/bin/python -m pip install -r requirements-termux.txt

mkdir -p "$HOME/.local/state/vimusic"
SERVICE_DIR="$PREFIX/var/service/vimusic"
mkdir -p "$SERVICE_DIR/log"

cat > "$SERVICE_DIR/run" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
cd "$PROJECT_DIR" || exit 1
exec "$PROJECT_DIR/.venv/bin/python" -u -m uvicorn server.main:app --host 127.0.0.1 --port 8765 --no-access-log
EOF

cat > "$SERVICE_DIR/log/run" <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
mkdir -p "$HOME/.local/state/vimusic/log"
exec svlogd -tt "$HOME/.local/state/vimusic/log"
EOF

chmod 700 "$SERVICE_DIR/run" "$SERVICE_DIR/log/run"

echo
echo "Dependencies and the runit service are installed."
echo "Close this Termux session, reopen Termux, then run:"
echo "  sv-enable vimusic"
echo "  bash '$PROJECT_DIR/scripts/termux-start.sh'"
echo
echo "The server will listen only on 127.0.0.1:8765."
