"""OpenAI-compatible HTTP client with Prometheus instrumentation.

Only two endpoints are used, `/chat/completions` and `/embeddings`, so the
client is a thin layer over `aiohttp` rather than a vendor SDK.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import aiohttp

from supernote.server.ai.base import AIError
from supernote.server.metrics import OPENAI_API_CALLS_TOTAL, OPENAI_API_DURATION_SECONDS

if TYPE_CHECKING:
    from supernote.server.config import ProviderConfig

__all__ = [
    "DEFAULT_BASE_URL",
    "OpenAIBackend",
    "create_openai_backend",
]

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"

# Local vision models can take minutes on a large page image.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=600)

# Transport failures and responses that are not shaped as expected.
_RESPONSE_ERRORS = (
    aiohttp.ClientError,
    TimeoutError,
    ValueError,
    KeyError,
    IndexError,
    TypeError,
)


class OpenAIBackend:
    """OpenAI-compatible HTTP client with Prometheus instrumentation."""

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    @contextmanager
    def _track_api_call(self, operation: str) -> Generator[None]:
        start_time = time.monotonic()
        status = "failure"
        try:
            yield
            status = "success"
        except AIError as err:
            logger.error(f"OpenAI-compatible API error during {operation}: {err}")
            raise
        except _RESPONSE_ERRORS as err:
            logger.error(f"OpenAI-compatible API error during {operation}: {err!r}")
            raise AIError(
                f"OpenAI-compatible API error during {operation}: {err!r}"
            ) from err
        finally:
            duration = time.monotonic() - start_time
            OPENAI_API_CALLS_TOTAL.labels(operation=operation, status=status).inc()
            OPENAI_API_DURATION_SECONDS.labels(operation=operation).observe(duration)

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            async with session.post(
                f"{self._base_url}{path}", json=payload, headers=headers
            ) as response:
                if response.status >= 400:
                    body = await response.text()
                    raise AIError(
                        f"{path} returned HTTP {response.status}: {body[:500]}"
                    )
                return await response.json(content_type=None)

    async def chat_completion(
        self,
        model: str,
        content: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Send one user message to `/chat/completions` and return the reply text."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
        }
        if response_format is not None:
            payload["response_format"] = response_format
        with self._track_api_call("chat_completion"):
            data = await self._post("/chat/completions", payload)
            text = data["choices"][0]["message"]["content"] or ""
            if not isinstance(text, str):
                raise TypeError("chat completion content is not a string")
            return text

    async def embeddings(self, model: str, text: str) -> list[float]:
        """Return the embedding vector for `text` from `/embeddings`."""
        with self._track_api_call("embeddings"):
            data = await self._post("/embeddings", {"model": model, "input": text})
            return [float(value) for value in data["data"][0]["embedding"]]


def create_openai_backend(
    providers: Mapping[str, ProviderConfig],
    name: str = "openai",
) -> OpenAIBackend | None:
    """Create an `OpenAIBackend` from configured providers, or `None` if unconfigured.

    A provider entry needs a `base_url` (e.g. a local Ollama server) or an
    `api_key` (hosted OpenAI at `DEFAULT_BASE_URL`).
    """
    provider_cfg = providers.get(name)
    if provider_cfg is None:
        return None
    base_url = (provider_cfg.base_url or "").strip()
    api_key = (provider_cfg.api_key or "").strip() or None
    if not base_url and not api_key:
        return None
    return OpenAIBackend(base_url or DEFAULT_BASE_URL, api_key)
