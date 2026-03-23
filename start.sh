#!/bin/bash
set -e
echo "========================================="
echo "  Samva — Starting services"
echo "========================================="

mkdir -p data/db data/sessions

# Start Python API in background
echo "[Start] Launching Core API on port 8000..."
cd /app/api
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!
cd /app

# Wait for API to be ready
echo "[Start] Waiting for Core API..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "[Start] Core API is ready!"
        break
    fi
    if ! kill -0 $API_PID 2>/dev/null; then
        echo "[Start] WARNING: Core API not started yet. Bridge will retry."
        break
    fi
    sleep 1
done

# Start Node bridge (foreground — Railway monitors this process)
echo "[Start] Launching WhatsApp Bridge on port ${PORT:-3000}..."
cd /app/bridge
exec node src/index.js
