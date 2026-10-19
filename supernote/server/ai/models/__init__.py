"""Task-based AI model interfaces and provider implementations.

Models are split by capability (`ocr`, `summary`, `embedding`) rather than
bundled into a single monolithic service so each task can be configured,
concurrency-limited, or replaced independently.

Provider subpackages under `supernote.server.ai.models.<provider>` implement
`ocr`, `summary`, and `embedding` modules with `create_ocr_model`,
`create_summary_model`, and `create_embedding_model` factory functions.
"""

__all__ = [
    "embedding",
    "fake",
    "ocr",
    "summary",
]
