#!/bin/bash
set -e
echo "Samva — Starting services"
mkdir -p data/db data/sessions

# Install Python deps
cd api && pip install -q -r requirements.txt && cd ..

# Install Node deps
cd bridge && npm install --production && cd ..

# Start Python API in background
cd api && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
cd ..

# Wait for API
for i in {1..30}; do
    curl -s http://localhost:8000/health > /dev/null 2>&1 && break
    sleep 1
done

# Start Node bridge (foreground — this is what Railway monitors)
cd bridge && exec node src/index.js
