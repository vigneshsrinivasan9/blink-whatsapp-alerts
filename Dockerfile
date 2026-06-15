# Blink -> WhatsApp/Telegram motion monitor — container image.
#
# Designed for always-on hosts (Raspberry Pi, mini PC, cloud VM, NAS). Uses
# system ffmpeg (multi-arch) and the vendored patched blinkpy fork.
#
# Build:  docker build -t blink-monitor .
# Run:    docker compose up -d   (see docker-compose.yml)
FROM python:3.13-slim

# System ffmpeg (used to extract frames across the clip). Works on amd64 + arm64.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching), then the patched blinkpy fork.
COPY requirements-docker.txt ./
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY vendor/ ./vendor/
RUN pip install --no-cache-dir --no-deps vendor/blinkpy-*.whl

# App source.
COPY src/ ./src/
COPY main.py ./

# Frames are written here; mount a volume to persist/inspect them.
ENV FRAMES_DIR=/data/frames \
    BLINK_CREDS_FILE=/data/blink_creds.json \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data/frames

# No tunnel inside the container: run telegram_only (Telegram uploads images
# directly, so no PUBLIC_BASE_URL is needed). Override via env/.env if desired.
ENV NOTIFY_MODE=telegram_only

CMD ["python", "main.py"]
