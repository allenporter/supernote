import abc
from typing import Any


class AIService(abc.ABC):
    """Abstract base class for AI service backends (OCR, embeddings, generation)."""

    @property
    @abc.abstractmethod
    def is_configured(self) -> bool:
        """Return True if the service is properly configured with an API key."""
        ...

    @property
    @abc.abstractmethod
    def provider_name(self) -> str:
        """Return the name of the AI provider (e.g. 'GEMINI', 'MISTRAL')."""
        ...

    @abc.abstractmethod
    async def ocr_image(self, png_data: bytes, prompt: str) -> str:
        """Perform OCR on a PNG image using the given prompt.

        Returns the extracted text content.
        """
        ...

    @abc.abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text."""
        ...

    @abc.abstractmethod
    async def generate_json(self, prompt: str, schema: dict[str, Any]) -> str:
        """Generate JSON content following the given schema.

        Returns a JSON string.
        """
        ...
