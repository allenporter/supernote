"""Google Gemini client wrapper with Prometheus instrumentation."""

from __future__ import annotations

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager

from google import genai
from google.genai import errors, types

from supernote.server.ai.base import AIError
from supernote.server.metrics import GEMINI_API_CALLS_TOTAL, GEMINI_API_DURATION_SECONDS

__all__ = [
    "GeminiBackend",
]

logger = logging.getLogger(__name__)


class GeminiBackend:
    """Google Gemini client wrapper with Prometheus instrumentation."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: genai.Client | None = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    @contextmanager
    def _track_api_call(self, operation: str) -> Generator[None]:
        start_time = time.monotonic()
        status = "success"
        try:
            yield
        except errors.APIError as err:
            status = "failure"
            logger.error(f"Gemini API error during {operation}: {err}")
            raise AIError(f"Gemini API error during {operation}: {err}") from err
        except Exception as err:
            status = "failure"
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
