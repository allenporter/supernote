import asyncio
from typing import Any

from google import genai
from google.genai import types

from supernote.server.services.ai_service import AIService


class GeminiService(AIService):
    """AI service implementation using Google Gemini."""

    def __init__(
        self,
        api_key: str | None,
        ocr_model: str,
        embedding_model: str,
        chat_model: str,
        max_concurrency: int = 5,
    ) -> None:
        self.api_key = api_key
        self._ocr_model = ocr_model
        self._embedding_model = embedding_model
        self._chat_model = chat_model
        self.max_concurrency = max(1, max_concurrency)
        self._client: genai.Client | None = None
        self._semaphore: asyncio.Semaphore | None = None
        if self.api_key:
            self._client = genai.Client(
                api_key=self.api_key, http_options={"api_version": "v1alpha"}
            )

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    @property
    def provider_name(self) -> str:
        return "GEMINI"

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

    async def ocr_image(self, png_data: bytes, prompt: str) -> str:
        response = await self.generate_content(
            model=self._ocr_model,
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_text(text=prompt),
                        types.Part.from_bytes(data=png_data, mime_type="image/png"),
                    ]
                )
            ],
            config={"media_resolution": "media_resolution_high"},  # type: ignore[arg-type]
        )
        return response.text or ""

    async def embed_text(self, text: str) -> list[float]:
        response = await self.embed_content(
            model=self._embedding_model,
            contents=text,
        )
        if not response.embeddings:
            raise ValueError("No embeddings returned from Gemini API")
        values = response.embeddings[0].values
        if not values:
            raise ValueError("Empty embedding values returned from Gemini API")
        return list(values)

    async def generate_json(self, prompt: str, schema: dict[str, Any]) -> str:
        response = await self.generate_content(
            model=self._chat_model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": schema,
            },
        )
        return response.text or ""
