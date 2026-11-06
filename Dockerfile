# ==========================================
# Stage 1: Build PO Token Provider
# ==========================================

FROM node:22-bookworm-slim AS pot-provider-build

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/bgutil-ytdlp-pot-provider

RUN git clone \
    --depth 1 \
    --single-branch \
    --branch 2.0.2 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git .

WORKDIR /opt/bgutil-ytdlp-pot-provider/server

RUN npm ci && npx tsc


# ==========================================
# Stage 2: Python Backend
# ==========================================

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    libstdc++6 \
    libatomic1 \
    && rm -rf /var/lib/apt/lists/*


# Copy Node.js runtime
COPY --from=pot-provider-build \
    /usr/local/bin/node \
    /usr/local/bin/node


# Copy PO Token Provider
COPY --from=pot-provider-build \
    /opt/bgutil-ytdlp-pot-provider/server \
    /opt/bgutil-ytdlp-pot-provider/server


# Install Python dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


# Copy application
COPY server/ ./server/
COPY static/ ./static/


EXPOSE 8000

ENV PORT=8000
ENV PYTHONUNBUFFERED=1


# Start PO-token server and FastAPI backend
CMD ["sh", "-c", "node /opt/bgutil-ytdlp-pot-provider/server/build/main.js --host 127.0.0.1 --port 4416 & exec uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000}"]