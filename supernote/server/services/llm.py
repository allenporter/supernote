"""Provider-neutral interface for the language models used by the server.

OCR, summarization, embedding and search code depend only on `LLMService`.
Backends translate these calls into a specific vendor API.
"""

from typing import Any, Protocol

__all__ = [
    "LLMError",
    "LLMService",
]


class LLMError(RuntimeError):
    """Raised when a model backend fails or returns an unusable response."""


class LLMService(Protocol):
    """A text generation and embedding backend."""

    @property
    def is_configured(self) -> bool:
        """Whether the backend has enough configuration to make calls."""
        ...

    @property
    def generation_model(self) -> str:
        """Model used for `generate` (OCR and summaries)."""
        ...

    async def generate(
        self,
        prompt: str,
        *,
        image_png: bytes | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        """Generate text for a prompt.

        Args:
            prompt: The text prompt.
            image_png: Optional PNG image sent alongside the prompt.
            json_schema: Optional JSON schema the response must conform to. When
                set, the returned string is a JSON document.
        """
        ...

    async def embed(self, text: str) -> list[float]:
        """Return the embedding vector for a block of text."""
        ...
