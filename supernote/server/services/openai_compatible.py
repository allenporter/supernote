"""`LLMService` backed by any server implementing the OpenAI HTTP API.

This covers hosted OpenAI as well as local servers such as Ollama, llama.cpp,
vLLM and LM Studio. Only two endpoints are used, `/chat/completions` and
`/embeddings`, so the client is a thin layer over `aiohttp`.
"""

import asyncio
import base64
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aiohttp

from supernote.server.metrics import OPENAI_API_CALLS_TOTAL, OPENAI_API_DURATION_SECONDS
from supernote.server.services.llm import LLMError

__all__ = ["OpenAICompatibleService"]

logger = logging.getLogger(__name__)

# Local vision models can take minutes on a large page image.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=600)

# Errors from the transport or from a response that is not shaped as expected.
_RESPONSE_ERRORS = (
    aiohttp.ClientError,
    TimeoutError,
    ValueError,
    KeyError,
    IndexError,
    TypeError,
)

_CODE_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n?```\s*$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """Remove a Markdown code fence that some models wrap JSON output in."""
    match = _CODE_FENCE.match(text.strip())
    return match.group(1) if match else text


class OpenAICompatibleService:
    """`LLMService` for OpenAI-compatible `/v1` endpoints."""

    def __init__(
        self,
        base_url: str | None,
        generation_model: str | None,
        embedding_model: str | None,
        api_key: str | None = None,
        embedding_base_url: str | None = None,
        max_concurrency: int = 1,
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._embedding_base_url = (
            embedding_base_url.rstrip("/") if embedding_base_url else self._base_url
        )
        self._generation_model = generation_model or ""
        self._embedding_model = embedding_model or ""
        self._api_key = api_key
        self.max_concurrency = max_concurrency
        self._semaphore: asyncio.Semaphore | None = None

    @property
    def is_configured(self) -> bool:
        return bool(
            self._base_url
            and self._embedding_base_url
            and self._generation_model
            and self._embedding_model
        )

    @property
    def generation_model(self) -> str:
        return self._generation_model

    async def generate(
        self,
        prompt: str,
        *,
        image_png: bytes | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        """Generate text with `/chat/completions`."""
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if image_png is not None:
            image_b64 = base64.b64encode(image_png).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{image_b64}",
                        "detail": "high",
                    },
                }
            )
        payload: dict[str, Any] = {
            "model": self._generation_model,
            "messages": [{"role": "user", "content": content}],
        }
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": json_schema},
            }

        data = await self._post(
            "generate_content", self._base_url, "/chat/completions", payload
        )
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except _RESPONSE_ERRORS as err:
            raise LLMError(f"Unexpected chat completion response: {err}") from err
        if not isinstance(text, str):
            raise LLMError("Chat completion content is not a string")
        return _strip_code_fence(text) if json_schema is not None else text

    async def embed(self, text: str) -> list[float]:
        """Embed text with `/embeddings`."""
        payload = {"model": self._embedding_model, "input": text}
        data = await self._post(
            "embed_content", self._embedding_base_url, "/embeddings", payload
        )
        try:
            return [float(value) for value in data["data"][0]["embedding"]]
        except _RESPONSE_ERRORS as err:
            raise LLMError(f"Unexpected embedding response: {err}") from err

    async def _post(
        self,
        operation: str,
        base_url: str | None,
        path: str,
        payload: dict[str, Any],
    ) -> Any:
        """POST a JSON payload and return the decoded JSON response."""
        if not self.is_configured or base_url is None:
            raise ValueError("OpenAI-compatible endpoint not configured")

        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with self._track(operation):
            try:
                async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                    async with session.post(
                        f"{base_url}{path}", json=payload, headers=headers
                    ) as response:
                        if response.status >= 400:
                            body = await response.text()
                            raise LLMError(
                                f"{path} returned HTTP {response.status}: {body[:500]}"
                            )
                        return await response.json(content_type=None)
            except _RESPONSE_ERRORS as err:
                raise LLMError(f"{path} request failed: {err!r}") from err

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Lazy initialization of semaphore to ensure it's in the correct event loop."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
        return self._semaphore

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
            OPENAI_API_CALLS_TOTAL.labels(operation=operation, status=status).inc()
            OPENAI_API_DURATION_SECONDS.labels(operation=operation).observe(
                time.perf_counter() - start_time
            )
