"""Google Gemini client wrapper with Prometheus instrumentation."""

from __future__ import annotations

import logging
import time
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING

import aiohttp
import httpx
from google import genai
from google.genai import errors, types

from supernote.server.ai.base import AIError
from supernote.server.metrics import GEMINI_API_CALLS_TOTAL, GEMINI_API_DURATION_SECONDS

if TYPE_CHECKING:
    from supernote.server.config import ProviderConfig

__all__ = [
    "GeminiBackend",
    "create_gemini_backend",
]

logger = logging.getLogger(__name__)

_TRANSPORT_ERRORS = (
    httpx.HTTPError,
    aiohttp.ClientError,
    OSError,
    TimeoutError,
    ValueError,
    TypeError,
)


class GeminiBackend:
    """Google Gemini client wrapper with Prometheus instrumentation."""

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._client: genai.Client | None = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            http_options = (
                types.HttpOptions(
                    base_url=self._base_url,
                    retry_options=types.HttpRetryOptions(attempts=1),
                )
                if self._base_url is not None
                else None
            )
            self._client = genai.Client(
                api_key=self._api_key,
                http_options=http_options,
            )
        return self._client

    @contextmanager
    def _track_api_call(self, operation: str) -> Generator[None]:
        start_time = time.monotonic()
        status = "failure"
        try:
            yield
            status = "success"
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
        finally:
            duration = time.monotonic() - start_time
            GEMINI_API_CALLS_TOTAL.labels(operation=operation, status=status).inc()
            GEMINI_API_DURATION_SECONDS.labels(operation=operation).observe(duration)

    async def generate_content(
        self,
        model: str,
        contents: types.ContentListUnion | types.ContentListUnionDict,
        config: types.GenerateContentConfigOrDict | None = None,
    ) -> types.GenerateContentResponse:
        """Call Gemini `generate_content` with Prometheus instrumentation."""
        with self._track_api_call("generate_content"):
            return await self.client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

    async def embed_content(
        self,
        model: str,
        contents: types.ContentListUnion | types.ContentListUnionDict,
        config: types.EmbedContentConfigOrDict | None = None,
    ) -> types.EmbedContentResponse:
        """Call Gemini `embed_content` with Prometheus instrumentation."""
        with self._track_api_call("embed_content"):
            return await self.client.aio.models.embed_content(
                model=model,
                contents=contents,
                config=config,
            )


def create_gemini_backend(
    providers: Mapping[str, ProviderConfig],
    name: str = "gemini",
) -> GeminiBackend | None:
    """Create a `GeminiBackend` from configured providers, or `None` if unconfigured."""
    provider_cfg = providers.get(name)
    if (
        provider_cfg is None
        or not provider_cfg.api_key
        or not provider_cfg.api_key.strip()
    ):
        return None
    return GeminiBackend(provider_cfg.api_key, base_url=provider_cfg.base_url)
