FROM python:3.14-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUPERNOTE_STORAGE_DIR=/data \
    SUPERNOTE_CONFIG_DIR=/data/config \
    SUPERNOTE_HOST=0.0.0.0 \
    SUPERNOTE_PORT=8080

# Create a non-root user
RUN groupadd -g 1000 -r supernote && useradd -u 1000 -r -g supernote supernote

# Install system dependencies for SQL Lite CLI
RUN apt-get update && \
    apt-get install -y --no-install-recommends sqlite3 && \
    rm -rf /var/lib/apt/lists/*

# Set working directory and copy project files
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY supernote/ supernote/

# Install the package with server dependencies
RUN pip install --no-cache-dir ".[server]"

# Create directories for storage and config, and set permissions
RUN mkdir -p /data /data/config && \
    chown -R supernote:supernote /data

# Switch to non-root user
USER supernote

EXPOSE 8080

VOLUME ["/data"]

CMD ["supernote-server", "serve"]
