"""Tests for `supernote.server.ai.models.gemini.embedding`."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import EmbeddingTaskType
from supernote.server.ai.models.gemini.backend import GeminiBackend
from supernote.server.ai.models.gemini.embedding import GeminiEmbeddingModel


async def test_gemini_embedding_model() -> None:
    with patch("google.genai.Client") as mock_client_cls:
        backend = GeminiBackend(api_key="fake-key")
        mock_client = mock_client_cls.return_value
        backend._client = mock_client

        embedding_model = GeminiEmbeddingModel(backend, "text-embedding-004")
        mock_emb_resp = MagicMock()
        mock_emb_resp.embeddings = [MagicMock(values=[0.1, 0.2, 0.3])]
        mock_client.aio.models.embed_content = AsyncMock(return_value=mock_emb_resp)

        vec = await embedding_model.embed(
            "This is the text to embed.",
            task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT,
        )
        assert vec == [0.1, 0.2, 0.3]
        _, emb_kwargs = mock_client.aio.models.embed_content.call_args
        assert emb_kwargs["model"] == "text-embedding-004"
        assert emb_kwargs["contents"] == "This is the text to embed."
        assert emb_kwargs["config"] == types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT"
        )

        mock_empty_resp = MagicMock()
        mock_empty_resp.embeddings = []
        mock_client.aio.models.embed_content = AsyncMock(return_value=mock_empty_resp)
        with pytest.raises(AIError, match="No embeddings returned from Gemini API"):
            await embedding_model.embed(
                "This is the text to embed.",
                task_type=EmbeddingTaskType.RETRIEVAL_QUERY,
            )
