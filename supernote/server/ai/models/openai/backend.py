"""OpenAI-compatible HTTP client with error translation and token reporting.

Only two endpoints are used, `/chat/completions` and `/embeddings`, so the
client is a thin layer over `aiohttp` rather than a vendor SDK.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import aiohttp

from supernote.server.ai.base import AIError
from supernote.server.metrics import record_ai_tokens

if TYPE_CHECKING:
    from supernote.server.config import ProviderConfig

__all__ = [
    "DEFAULT_BASE_URL",
    "OpenAIBackend",
    "REQUEST_TIMEOUT",
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
    OSError,
    ValueError,
    KeyError,
    IndexError,
    TypeError,
)


def _non_negative_int(value: object) -> int | None:
    """Coerce a raw JSON token count to a non-negative `int`, rejecting `bool`."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and math.isfinite(value) and value >= 0:
        return int(value)
    return None


def _record_usage(data: Any, *, provider: str) -> None:
    """Record mutually exclusive token counts from an OpenAI-compatible `usage` block.

    Per the OpenAI `/chat/completions` specification, `completion_tokens`
    includes `completion_tokens_details.reasoning_tokens`, so reasoning tokens
    are subtracted to report `output` as visible completion tokens only.
    """
    if not isinstance(data, Mapping):
        return
    usage = data.get("usage")
    if not isinstance(usage, Mapping):
        return
    details = usage.get("completion_tokens_details")
    raw_reasoning = (
        details.get("reasoning_tokens") if isinstance(details, Mapping) else None
    )
    reasoning = _non_negative_int(raw_reasoning)
    completion = _non_negative_int(usage.get("completion_tokens"))
    if completion is not None and reasoning is not None:
        completion = max(0, completion - reasoning)
    record_ai_tokens(
        provider=provider,
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=completion,
        thinking_tokens=reasoning,
    )


class OpenAIBackend:
    """OpenAI-compatible HTTP client with error translation and token reporting."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        provider: str = "openai",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._provider = provider

    @property
    def provider(self) -> str:
        return self._provider

    @contextmanager
    def _handle_api_errors(self, operation: str) -> Generator[None]:
        try:
            yield
        except AIError as err:
            logger.error(f"OpenAI-compatible API error during {operation}: {err}")
            raise
        except _RESPONSE_ERRORS as err:
            logger.error(f"OpenAI-compatible API error during {operation}: {err!r}")
            raise AIError(
                f"OpenAI-compatible API error during {operation}: {err!r}"
            ) from err

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
        with self._handle_api_errors("chat_completion"):
            data = await self._post("/chat/completions", payload)
            _record_usage(data, provider=self._provider)
            text = data["choices"][0]["message"]["content"] or ""
            if not isinstance(text, str):
                raise TypeError("chat completion content is not a string")
            return text

    async def embeddings(self, model: str, text: str) -> list[float]:
        """Return the embedding vector for `text` from `/embeddings`."""
        with self._handle_api_errors("embeddings"):
            data = await self._post("/embeddings", {"model": model, "input": text})
            _record_usage(data, provider=self._provider)
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
    return OpenAIBackend(base_url or DEFAULT_BASE_URL, api_key, provider=name)
