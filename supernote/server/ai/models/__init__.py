"""Task-based AI model interfaces and cross-cutting wrappers.

Models are split by capability (`ocr`, `summary`, `embedding`) rather than
bundled into a single monolithic service so each task can be configured,
concurrency-limited, or replaced independently.

## Adding a New Model Provider

To add a new provider (e.g., `<provider>`):

1. **Create a provider component** under `supernote/server/components/<provider>/`:
   - `__init__.py`: Define `<Name>Component` with `domain = "<provider>"`, `dependencies = ("ai",)`, and `platforms` listing its supported capabilities (e.g., `("ocr", "summary", "embedding")` or `("ocr",)`).
   - `backend.py`: Shared transport/client wrapper and `create_<provider>_backend(providers: Mapping[str, ProviderConfig], provider: str)` helper. Translate SDK or HTTP failures into `AIError` (`supernote.server.ai.base.AIError`).
   - `ocr.py` / `summary.py` / `embedding.py`: Implement the corresponding model subclass (`OcrModel`, `SummaryModel`, `EmbeddingModel`) and expose `async_setup_<platform>(core, registrar)` calling `registrar.register_<platform>("<provider>", create_<platform>_model)`.
2. **Register the component** in `BUILTIN_COMPONENTS` (`supernote/server/components/__init__.py`, `default_enabled=False`) and gate it on `configured_ai_providers` in `supernote/server/app.py`. Vector norm validation (`ValidatingEmbeddingModel`), Prometheus telemetry (`Instrumented*Model`), and concurrency limiting (`ModelConfig.max_concurrency`) are applied automatically by `AiRegistrar`.
3. **Add unit tests** with 1:1 file parity under `tests/server/components/<provider>/`.
"""

__all__ = [
    "embedding",
    "ocr",
    "summary",
]
