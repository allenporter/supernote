"""HTTP platform setup for the AI component (`GET /api/extended/ai/status`)."""

from __future__ import annotations

from aiohttp import web

from supernote.models.extended import WebAiStatusVO
from supernote.server.ai.models.embedding import EmbeddingModel
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.ai.models.summary import SummaryModel
from supernote.server.ai.models.text import TextGenerationModel
from supernote.server.components.http import HttpRegistrar
from supernote.server.core import ServerCore

from . import (
    EMBEDDING_MODEL_KEY,
    OCR_MODEL_KEY,
    SUMMARY_MODEL_KEY,
    TEXT_MODEL_KEY,
)

__all__ = ["async_setup_http", "routes"]

routes = web.RouteTableDef()


@routes.get("/api/extended/ai/status")
async def handle_extended_ai_status(request: web.Request) -> web.Response:
    """Return server AI processing configuration and capability health status."""
    ocr_model: OcrModel | None = request.app.get(OCR_MODEL_KEY)
    summary_model: SummaryModel | None = request.app.get(SUMMARY_MODEL_KEY)
    embedding_model: EmbeddingModel | None = request.app.get(EMBEDDING_MODEL_KEY)
    text_model: TextGenerationModel | None = request.app.get(TEXT_MODEL_KEY)

    ocr_enabled = ocr_model is not None
    ocr_model_id = ocr_model.model_id if ocr_model is not None else None

    summary_enabled = summary_model is not None
    summary_model_id = summary_model.model_id if summary_model is not None else None

    vector_search_enabled = embedding_model is not None
    embedding_model_id = (
        embedding_model.model_id if embedding_model is not None else None
    )

    text_enabled = text_model is not None
    text_model_id = text_model.model_id if text_model is not None else None

    is_configured = any(
        (ocr_enabled, summary_enabled, vector_search_enabled, text_enabled)
    )
    primary_model = (
        ocr_model_id or summary_model_id or embedding_model_id or text_model_id
    )

    return web.json_response(
        WebAiStatusVO(
            has_api_key=is_configured,
            ocr_enabled=ocr_enabled,
            ocr_model=ocr_model_id,
            summary_enabled=summary_enabled,
            summary_model=summary_model_id,
            vector_search_enabled=vector_search_enabled,
            embedding_model=embedding_model_id,
            text_enabled=text_enabled,
            text_model=text_model_id,
            model=primary_model,
        ).to_dict()
    )


async def async_setup_http(core: ServerCore, registrar: HttpRegistrar) -> None:
    """Register AI status HTTP routes on ``registrar.router``."""
    registrar.router.add_routes(routes)
