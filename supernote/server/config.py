import os

# Default port for Supernote Private Cloud
PORT = int(os.getenv("SUPERNOTE_PORT", "8080"))
HOST = os.getenv("SUPERNOTE_HOST", "0.0.0.0")
TRACE_LOG_FILE = os.getenv("SUPERNOTE_TRACE_LOG", "data/server_trace.log")
