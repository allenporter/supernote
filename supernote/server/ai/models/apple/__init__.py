"""macOS local AI model implementations backed by Apple system frameworks (`Vision`).

This package provides `supernote.server.ai.models.apple.backend.AppleVisionBackend` and
`supernote.server.ai.models.apple.ocr.AppleOcrModel` for zero-cost, on-device handwriting OCR on
macOS hosts when `provider: apple` is configured in `supernote.server.config.ServerConfig`.
"""

__all__ = [
    "backend",
    "ocr",
]
