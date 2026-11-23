"""Google Gemini client wrapper with error translation and token reporting."""

from __future__ import annotations

import logging
import math
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING

import aiohttp
import httpx2
from google import genai
from google.genai import errors, types

from supernote.server.ai.base import AIError
from supernote.server.metrics import record_ai_tokens

if TYPE_CHECKING:
    from supernote.server.config import ProviderConfig

__all__ = [
    "GeminiBackend",
    "create_gemini_backend",
]

logger = logging.getLogger(__name__)

_TRANSPORT_ERRORS = (
    httpx2.HTTPError,
    aiohttp.ClientError,
    OSError,
    TimeoutError,
    ValueError,
    TypeError,
)


def _positive_int(value: object) -> int:
    """Coerce a raw SDK token count (`int` or finite `float`, excluding `bool`) to a positive `int`."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value if value > 0 else 0
    if isinstance(value, float) and math.isfinite(value) and value > 0:
        return int(value)
    return 0


class GeminiBackend:
    """Google Gemini client wrapper with error translation and token reporting."""

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        *,
        provider: str,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._provider = provider
        self._client: genai.Client | None = None

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            if self._base_url is not None:
                http_options = types.HttpOptions(
                    base_url=self._base_url,
                    api_version="v1beta",
                    retry_options=types.HttpRetryOptions(attempts=1),
                )
            else:
                http_options = types.HttpOptions(api_version="v1beta")
            self._client = genai.Client(
                api_key=self._api_key,
                http_options=http_options,
            )
        return self._client

    @contextmanager
    def _handle_api_errors(self, operation: str) -> Generator[None]:
        try:
            yield
        except AIError as err:
            logger.error(f"Gemini API error during {operation}: {err}")
            raise
        except errors.APIError as err:
            logger.error(f"Gemini API error during {operation}: {err}")
            raise AIError(f"Gemini API error during {operation}: {err}") from err
        except _TRANSPORT_ERRORS as err:
            logger.error(f"Unexpected error calling Gemini API ({operation}): {err}")
            raise AIError(
                f"Unexpected error calling Gemini API ({operation}): {err}"
            ) from err

    async def generate_content(
        self,
        model: str,
        contents: types.ContentListUnion | types.ContentListUnionDict,
        config: types.GenerateContentConfigOrDict | None = None,
    ) -> types.GenerateContentResponse:
        """Call Gemini `generate_content` and report mutually exclusive token usage."""
        with self._handle_api_errors("generate_content"):
            response = await self.client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        if usage := response.usage_metadata:
            record_ai_tokens(
                provider=self._provider,
                input_tokens=_positive_int(usage.prompt_token_count)
                + _positive_int(usage.tool_use_prompt_token_count),
                output_tokens=usage.candidates_token_count,
                thinking_tokens=usage.thoughts_token_count,
            )
        return response

    async def embed_content(
        self,
        model: str,
        contents: types.ContentListUnion | types.ContentListUnionDict,
        config: types.EmbedContentConfigOrDict | None = None,
    ) -> types.EmbedContentResponse:
        """Call Gemini `embed_content` and report token usage when available.

        Note: `ContentEmbedding.statistics.token_count` is populated by Vertex AI /
        Gemini Enterprise endpoints and omitted by the public Gemini Developer
        `v1beta` API.
        """
        with self._handle_api_errors("embed_content"):
            response = await self.client.aio.models.embed_content(
                model=model,
                contents=contents,
                config=config,
            )
        if response.embeddings:
            record_ai_tokens(
                provider=self._provider,
                input_tokens=sum(
                    _positive_int(emb.statistics.token_count)
                    for emb in response.embeddings
                    if emb.statistics is not None
                ),
            )
        return response


def create_gemini_backend(
    providers: Mapping[str, ProviderConfig],
    provider: str,
) -> GeminiBackend | None:
    """Create a `GeminiBackend` from configured providers, or `None` if unconfigured."""
    provider_cfg = providers.get(provider)
    if (
        provider_cfg is None
        or not provider_cfg.api_key
        or not provider_cfg.api_key.strip()
    ):
        return None
    return GeminiBackend(
        provider_cfg.api_key,
        base_url=provider_cfg.base_url,
        provider=provider,
    )
