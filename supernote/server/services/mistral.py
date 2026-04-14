import asyncio
import base64
import json
from typing import Any, cast

from mistralai.client import Mistral
from mistralai.client.models import (
    AssistantMessage,
    SystemMessage,
    ToolMessage,
    UserMessage,
)

from supernote.server.services.ai_service import AIService


class MistralService(AIService):
    """AI service implementation using Mistral AI."""

    def __init__(
        self,
        api_key: str | None,
        ocr_model: str,
        embedding_model: str,
        chat_model: str,
        max_concurrency: int = 5,
    ) -> None:
        self._ocr_model = ocr_model
        self._embedding_model = embedding_model
        self._chat_model = chat_model
        self.max_concurrency = max(1, max_concurrency)
        self._client: Mistral | None = None
        self._semaphore: asyncio.Semaphore | None = None
        if api_key:
            self._client = Mistral(api_key=api_key)

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    @property
    def provider_name(self) -> str:
        return "MISTRAL"

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Lazy initialization of semaphore to ensure it's in the correct event loop."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
        return self._semaphore

    async def ocr_image(self, png_data: bytes, prompt: str) -> str:
        # The dedicated OCR API does not accept a prompt — it extracts text
        # directly from the document. The `prompt` parameter is part of the
        # AIService interface for providers that support vision+instruction
        # (e.g. Gemini), and is intentionally unused here.
        if self._client is None:
            raise ValueError("Mistral API key not configured")

        b64_image = base64.b64encode(png_data).decode()
        async with self._get_semaphore():
            response = await self._client.ocr.process_async(
                model=self._ocr_model,
                document={
                    "type": "image_url",
                    "image_url": f"data:image/png;base64,{b64_image}",
                },
            )
        pages = getattr(response, "pages", None)
        if not pages:
            return ""
        return "\n\n".join(
            page.markdown for page in pages if getattr(page, "markdown", None)
        )

    async def embed_text(self, text: str) -> list[float]:
        if self._client is None:
            raise ValueError("Mistral API key not configured")

        async with self._get_semaphore():
            response = await self._client.embeddings.create_async(
                model=self._embedding_model,
                inputs=[text],
            )
        if not response.data:
            raise ValueError("No embeddings returned from Mistral API")
        embedding = response.data[0].embedding
        if embedding is None:
            raise ValueError("No embedding values returned from Mistral API")
        return list(embedding)

    async def generate_json(self, prompt: str, schema: dict[str, Any]) -> str:
        if self._client is None:
            raise ValueError("Mistral API key not configured")

        schema_str = json.dumps(schema, separators=(",", ":"))
        full_prompt = (
            f"{prompt}\n\nRespond with valid JSON matching this schema:\n{schema_str}"
        )
        async with self._get_semaphore():
            response = await self._client.chat.complete_async(
                model=self._chat_model,
                messages=cast(
                    list[AssistantMessage | SystemMessage | ToolMessage | UserMessage],
                    [UserMessage(content=full_prompt)],
                ),
                response_format={"type": "json_object"},
            )
        content = response.choices[0].message.content if response.choices else ""
        return (
            content
            if isinstance(content, str)
            else json.dumps(content, separators=(",", ":"))
        )
