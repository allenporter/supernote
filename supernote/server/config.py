import os

# Default port for Supernote Private Cloud
PORT = int(os.getenv("SUPERNOTE_PORT", "8080"))
HOST = os.getenv("SUPERNOTE_HOST", "0.0.0.0")
TRACE_LOG_FILE = os.getenv("SUPERNOTE_TRACE_LOG", "data/server_trace.log")
STORAGE_DIR = os.getenv("SUPERNOTE_STORAGE_DIR", "storage")
USER_CONFIG_FILE = os.getenv("SUPERNOTE_USER_CONFIG_FILE", "config/users.yaml")


class Config:
    PORT = PORT
    HOST = HOST
    TRACE_LOG_FILE = TRACE_LOG_FILE
    STORAGE_DIR = STORAGE_DIR
    USER_CONFIG_FILE = USER_CONFIG_FILE
