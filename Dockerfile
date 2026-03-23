# Samva — Dual runtime: Node.js + Python
FROM node:22-slim

# Install Python 3 + pip + build tools for native modules (better-sqlite3)
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv curl \
    build-essential python3-dev \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

# Install Python deps first (cached layer)
COPY api/requirements.txt api/requirements.txt
RUN pip3 install --break-system-packages -q -r api/requirements.txt

# Install Node deps (cached layer)
COPY bridge/package.json bridge/package.json
RUN cd bridge && npm install --production

# Copy everything
COPY . .
RUN chmod +x start.sh

# Create data directories
RUN mkdir -p data/db data/sessions

# Railway assigns PORT dynamically
EXPOSE ${PORT:-3000}

CMD ["bash", "start.sh"]
