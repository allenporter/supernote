"""Task-based AI model interfaces and provider implementations.

Models are split by capability (`ocr`, `summary`, `embedding`) rather than
bundled into a single monolithic service so each task can be configured,
concurrency-limited, or replaced independently.

## Adding a New Model Provider

To add a new provider (e.g., `<provider>`):

1. **Create the provider subpackage** under `supernote/server/ai/models/<provider>/`:
   - `backend.py`: Shared transport/client wrapper and `create_<provider>_backend(providers: Mapping[str, ProviderConfig])` helper. Translate SDK or HTTP failures into `AIError` (`supernote.server.ai.base.AIError`).
   - `ocr.py`: Subclass `OcrModel` (`extract_text(png_data, prompt) -> str`) and provide `create_ocr_model(config: ServerConfig) -> OcrModel | None`.
   - `summary.py`: Subclass `SummaryModel` (`summarize(prompt) -> SummaryResponse`, using `get_summary_json_schema()`) and provide `create_summary_model(config: ServerConfig) -> SummaryModel | None`.
   - `embedding.py`: Subclass `EmbeddingModel` (`_embed(text, task_type) -> list[float]`) and provide `create_embedding_model(config: ServerConfig) -> EmbeddingModel | None`.
2. **Register the provider** in the top-level factories (`create_ocr_model`, `create_summary_model`, `create_embedding_model` in `ocr.py`, `summary.py`, and `embedding.py`). Concurrency limiting (`ModelConfig.max_concurrency`) and vector norm validation (`EmbeddingModel.embed`) are applied automatically by the base layer.
3. **Add unit tests** with 1:1 file parity under `tests/server/ai/models/<provider>/`.
"""

__all__ = [
    "embedding",
    "fake",
    "gemini",
    "ocr",
    "openai",
    "summary",
]
