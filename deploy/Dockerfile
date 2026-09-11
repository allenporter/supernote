FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUPERNOTE_STORAGE_DIR=/data \
    SUPERNOTE_CONFIG_DIR=/data/config \
    SUPERNOTE_HOST=0.0.0.0 \
    SUPERNOTE_PORT=8080

RUN groupadd -g 1000 -r supernote && useradd -u 1000 -r -m -g supernote supernote

WORKDIR /app

# Pinned to the version current as of this scaffold (2026-09). Bump deliberately.
RUN pip install --no-cache-dir "supernote[server]==0.20.0"

RUN mkdir -p /data /data/config && chown -R supernote:supernote /data

USER supernote

EXPOSE 8080 8081

VOLUME ["/data"]

CMD ["supernote", "serve"]
