#!/bin/bash
set -e
echo "========================================="
echo "  Samva — Starting services"
echo "========================================="

# Railway puts everything in /app
APP_DIR="${RAILWAY_APP_DIR:-$(pwd)}"
cd "$APP_DIR"

mkdir -p data/db data/sessions

# Install Python deps
echo "[Start] Installing Python dependencies..."
cd "$APP_DIR/api"
pip3 install -q -r requirements.txt 2>/dev/null || python3 -m pip install -q -r requirements.txt || echo "[Start] pip install skipped (may be pre-installed)"
cd "$APP_DIR"

# Install Node deps
echo "[Start] Installing Node dependencies..."
cd "$APP_DIR/bridge"
npm install --production 2>/dev/null || echo "[Start] npm install skipped (may be pre-installed)"
cd "$APP_DIR"

# Start Python API in background
echo "[Start] Launching Core API on port 8000..."
cd "$APP_DIR/api"
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!
cd "$APP_DIR"

# Wait for API to be ready
echo "[Start] Waiting for Core API..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "[Start] Core API is ready!"
        break
    fi
    if ! kill -0 $API_PID 2>/dev/null; then
        echo "[Start] ERROR: Core API process died. Check logs."
        # Still start bridge so Railway can see health check
        break
    fi
    sleep 1
done

# Start Node bridge (foreground — Railway monitors this process)
echo "[Start] Launching WhatsApp Bridge on port ${PORT:-3000}..."
cd "$APP_DIR/bridge"
exec node src/index.js
