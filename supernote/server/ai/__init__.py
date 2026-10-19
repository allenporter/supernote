"""AI model abstractions and prompt formatting for notebook processing and search.

Callers interact with AI capabilities by formatting provider-neutral prompts
and passing them to task-specific model interfaces (`OcrModel`, `SummaryModel`,
`EmbeddingModel`). This keeps the processing pipeline and search service
decoupled from any specific model vendor or SDK.

Typical usage:

```python
from supernote.server.ai.prompts import PageMetadata, format_ocr_prompt

prompt = format_ocr_prompt(page_metadata)
text = await ocr_model.extract_text(png_bytes, prompt)
```
"""

__all__ = [
    "base",
    "models",
    "prompts",
]
