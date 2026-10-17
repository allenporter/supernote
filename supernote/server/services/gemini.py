import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from supernote.server.metrics import GEMINI_API_CALLS_TOTAL, GEMINI_API_DURATION_SECONDS
from supernote.server.services.llm import LLMError

if TYPE_CHECKING:
    from google import genai
    from google.genai import types

__all__ = ["GeminiService"]

logger = logging.getLogger(__name__)


class GeminiService:
    """`LLMService` backed by the Google Gemini API."""

    def __init__(
        self,
        api_key: str | None,
        generation_model: str,
        embedding_model: str,
        max_concurrency: int = 5,
    ) -> None:
        self.api_key = api_key
        self._generation_model = generation_model
        self._embedding_model = embedding_model
        self.max_concurrency = max_concurrency
        self._client: "genai.Client | None" = None
        self._semaphore: asyncio.Semaphore | None = None
        if self.api_key:
            # Deferred: google-genai is a heavy import (pulls in ~300
            # transitive modules), so only pay for it when an API key is
            # actually configured.
            from google import genai  # noqa: PLC0415

            self._client = genai.Client(
                api_key=self.api_key, http_options={"api_version": "v1alpha"}
            )

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    @property
    def generation_model(self) -> str:
        return self._generation_model

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Lazy initialization of semaphore to ensure it's in the correct event loop."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
        return self._semaphore

    async def generate(
        self,
        prompt: str,
        *,
        image_png: bytes | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        """Generate text using the Gemini API."""
        # Deferred: see __init__.
        from google.genai import types  # noqa: PLC0415

        config: types.GenerateContentConfigDict = {}
        contents: Any = prompt
        if image_png is not None:
            contents = [
                types.Content(
                    parts=[
                        types.Part.from_text(text=prompt),
                        types.Part.from_bytes(data=image_png, mime_type="image/png"),
                    ]
                )
            ]
            config["media_resolution"] = types.MediaResolution.MEDIA_RESOLUTION_HIGH
        if json_schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = json_schema

        response = await self._generate_content(
            model=self._generation_model,
            contents=contents,
            config=config or None,
        )
        return response.text or ""

    async def embed(self, text: str) -> list[float]:
        """Embed text using the Gemini API."""
        response = await self._embed_content(self._embedding_model, text)
        if not response.embeddings or response.embeddings[0].values is None:
            raise LLMError("No embeddings returned from Gemini API")
        return list(response.embeddings[0].values)

    async def _generate_content(
        self,
        model: str,
        contents: Any,
        config: "types.GenerateContentConfigDict | None",
    ) -> "types.GenerateContentResponse":
        if self._client is None:
            raise ValueError("Gemini API key not configured")
        async with self._track("generate_content"):
            return await self._client.aio.models.generate_content(
                model=model, contents=contents, config=config
            )

    async def _embed_content(
        self, model: str, contents: str
    ) -> "types.EmbedContentResponse":
        if self._client is None:
            raise ValueError("Gemini API key not configured")
        async with self._track("embed_content"):
            return await self._client.aio.models.embed_content(
                model=model, contents=contents
            )

    @asynccontextmanager
    async def _track(self, operation: str) -> AsyncIterator[None]:
        """Limit concurrency and record call metrics for one API call."""
        start_time = time.perf_counter()
        status = "success"
        try:
            async with self._get_semaphore():
                yield
        except Exception:
            status = "failure"
            raise
        finally:
            GEMINI_API_CALLS_TOTAL.labels(operation=operation, status=status).inc()
            GEMINI_API_DURATION_SECONDS.labels(operation=operation).observe(
                time.perf_counter() - start_time
            )
