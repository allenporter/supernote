FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUPERNOTE_STORAGE_DIR=/data \
    SUPERNOTE_CONFIG_DIR=/data/config \
    SUPERNOTE_HOST=0.0.0.0 \
    SUPERNOTE_PORT=8080

RUN groupadd -g 1000 -r supernote && useradd -u 1000 -r -m -g supernote supernote

WORKDIR /app

# Built from this repository's own source instead of the PyPI release,
# so the local Apple Vision OCR / Ollama embedding modules are
# included — see docker-compose.yml's build.context, which points this at
# the repo root. Build from a pinned commit/tag checkout, not a moving
# `main` branch, so the deployed image is reproducible.
COPY pyproject.toml README.md LICENSE ./
COPY supernote/ supernote/
RUN pip install --no-cache-dir ".[server]"

RUN mkdir -p /data /data/config && chown -R supernote:supernote /data

USER supernote

EXPOSE 8080 8081

VOLUME ["/data"]

CMD ["supernote", "serve"]
