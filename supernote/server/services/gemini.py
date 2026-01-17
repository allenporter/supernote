import asyncio
import logging
from typing import Any

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class GeminiService:
    """Shared service for interacting with Google Gemini API."""

    def __init__(self, api_key: str | None, max_concurrency: int = 5) -> None:
        self.api_key = api_key
        self.max_concurrency = max_concurrency
        self._client: genai.Client | None = None
        self._semaphore: asyncio.Semaphore | None = None
        if self.api_key:
            self._client = genai.Client(
                api_key=self.api_key, http_options={"api_version": "v1alpha"}
            )

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Lazy initialization of semaphore to ensure it's in the correct event loop."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
        return self._semaphore

    async def generate_content(
        self,
        model: str,
        contents: Any,
        config: types.GenerateContentConfigOrDict | None = None,
    ) -> types.GenerateContentResponse:
        """Asynchronously generate content using the Gemini API."""
        if self._client is None:
            raise ValueError("Gemini API key not configured")

        async with self._get_semaphore():
            return await self._client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

    async def embed_content(
        self,
        model: str,
        contents: Any,
        config: types.EmbedContentConfigOrDict | None = None,
    ) -> types.EmbedContentResponse:
        """Asynchronously generate embeddings using the Gemini API."""
        if self._client is None:
            raise ValueError("Gemini API key not configured")

        async with self._get_semaphore():
            return await self._client.aio.models.embed_content(
                model=model,
                contents=contents,
                config=config,
            )
