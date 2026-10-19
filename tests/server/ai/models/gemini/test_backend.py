"""Tests for `supernote.server.ai.models.gemini.backend`."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from supernote.server.ai.base import AIError
from supernote.server.ai.models.gemini.backend import GeminiBackend


async def test_gemini_backend_translates_client_errors_to_ai_error() -> None:
    with patch("google.genai.Client") as mock_client_cls:
        backend = GeminiBackend(api_key="fake-key")
        mock_client = mock_client_cls.return_value
        backend._client = mock_client

        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("network timeout")
        )
        with pytest.raises(AIError, match="Unexpected error calling Gemini API"):
            await backend.generate_content(model="gemini-2.0-flash", contents="hello")

        mock_client.aio.models.embed_content = AsyncMock(
            side_effect=RuntimeError("network timeout")
        )
        with pytest.raises(AIError, match="Unexpected error calling Gemini API"):
            await backend.embed_content(model="text-embedding-004", contents="hello")
