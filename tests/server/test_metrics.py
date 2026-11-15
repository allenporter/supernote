import asyncio
import json
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, make_mocked_request
from prometheus_client import REGISTRY

from supernote.server.ai.base import AIError
from supernote.server.ai.models.embedding import (
    EmbeddingTaskType,
    InstrumentedEmbeddingModel,
)
from supernote.server.ai.models.gemini.backend import GeminiBackend
from supernote.server.ai.models.gemini.embedding import GeminiEmbeddingModel
from supernote.server.ai.models.gemini.ocr import GeminiOcrModel
from supernote.server.ai.models.gemini.summary import GeminiSummaryModel
from supernote.server.ai.models.ocr import InstrumentedOcrModel
from supernote.server.ai.models.openai.backend import OpenAIBackend
from supernote.server.ai.models.openai.embedding import OpenAIEmbeddingModel
from supernote.server.ai.models.openai.ocr import OpenAIOcrModel
from supernote.server.ai.models.openai.summary import OpenAISummaryModel
from supernote.server.ai.models.summary import InstrumentedSummaryModel
from supernote.server.app import create_app, metrics_middleware
from supernote.server.config import ServerConfig
from supernote.server.keys import SESSION_MANAGER_KEY
from supernote.server.metrics import (
    PIPELINE_DURATION_BUCKETS,
    REQUEST_DURATION_BUCKETS,
    AIStage,
    NoteProcessingMode,
    init_note_processing_metrics,
    record_ai_tokens,
    record_note_page_diff,
    track_ai_request,
    track_note_processing_run,
)

REMOVED_LEGACY_METRICS = (
    "supernote_gemini_api_calls_total",
    "supernote_gemini_api_duration_seconds",
    "supernote_openai_api_calls_total",
    "supernote_openai_api_duration_seconds",
    "supernote_apple_ai_calls_total",
    "supernote_apple_ai_duration_seconds",
)


async def test_metrics_endpoint(client: TestClient) -> None:
    """Verify that the metrics endpoint is exposed and returns Prometheus format."""
    resp = await client.get("/metrics")
    assert resp.status == 200
    assert "text/plain" in resp.headers["Content-Type"]

    body = await resp.text()
    # Should contain Python runtime or process metrics
    assert (
        "python_gc_objects_collected_total" in body
        or "process_cpu_seconds_total" in body
    )
    # Should contain our custom metrics and exclude removed vendor-specific families
    assert "supernote_http_requests_total" in body
    assert "supernote_http_requests_in_progress" in body
    assert "supernote_note_processing_runs_total" in body
    assert "supernote_note_processing_duration_seconds" in body
    assert "supernote_note_pages_parsed_total" in body
    assert "supernote_processor_queue_paused" in body
    assert (
        REGISTRY.get_sample_value(
            "supernote_http_requests_total",
            {"method": "GET", "path": "/metrics", "status": "200"},
        )
        is None
    )
    for legacy_metric in REMOVED_LEGACY_METRICS:
        assert legacy_metric not in body


async def test_http_request_tracking(client: TestClient) -> None:
    """Verify that HTTP requests increment request counters and export extended latency buckets."""
    before = (
        REGISTRY.get_sample_value(
            "supernote_http_requests_total",
            {"method": "GET", "path": "/api/file/query/server", "status": "200"},
        )
        or 0.0
    )

    resp = await client.get("/api/file/query/server")
    assert resp.status == 200

    after = (
        REGISTRY.get_sample_value(
            "supernote_http_requests_total",
            {"method": "GET", "path": "/api/file/query/server", "status": "200"},
        )
        or 0.0
    )

    assert after == before + 1.0

    for bucket in REQUEST_DURATION_BUCKETS:
        bucket_val = REGISTRY.get_sample_value(
            "supernote_http_request_duration_seconds_bucket",
            {
                "method": "GET",
                "path": "/api/file/query/server",
                "le": str(bucket),
            },
        )
        assert bucket_val is not None


async def test_http_mcp_oauth_known_path_preserved(client: TestClient) -> None:
    """Verify known MCP OAuth discovery requests retain their canonical route path label."""
    oauth_labels = {
        "method": "GET",
        "path": "/.well-known/oauth-authorization-server",
        "status": "200",
    }
    before_oauth = (
        REGISTRY.get_sample_value("supernote_http_requests_total", oauth_labels) or 0.0
    )

    oauth_resp = await client.get("/.well-known/oauth-authorization-server")
    assert oauth_resp.status == 200
    assert (
        REGISTRY.get_sample_value("supernote_http_requests_total", oauth_labels)
        == before_oauth + 1.0
    )


async def test_http_mcp_unmatched_scanner_path_collapsed(client: TestClient) -> None:
    """Verify unmatched scanner paths caught by MCP ASGIResource collapse to 'HTTP 404'."""
    scanner_path = "/unmatched/scanner/path"
    not_found_labels = {"method": "GET", "path": "HTTP 404", "status": "404"}
    before_404 = (
        REGISTRY.get_sample_value("supernote_http_requests_total", not_found_labels)
        or 0.0
    )

    scanner_resp = await client.get(scanner_path)
    assert scanner_resp.status == 404
    assert (
        REGISTRY.get_sample_value("supernote_http_requests_total", not_found_labels)
        == before_404 + 1.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_http_requests_total",
            {"method": "GET", "path": scanner_path, "status": "404"},
        )
        is None
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_http_request_duration_seconds_count",
            {"method": "GET", "path": scanner_path},
        )
        is None
    )


async def test_http_in_progress_gauge_and_nonstandard_method_normalized(
    aiohttp_client: Any,
) -> None:
    """Verify active requests update in-progress gauge and normalize non-standard HTTP verbs to 'OTHER'."""
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_handler(_request: web.Request) -> web.Response:
        entered.set()
        await release.wait()
        return web.Response(text="ok")

    app = web.Application(middlewares=[metrics_middleware])
    app.router.add_route("*", "/slow", slow_handler)
    custom_client = await aiohttp_client(app)

    before_other_in_flight = (
        REGISTRY.get_sample_value(
            "supernote_http_requests_in_progress", {"method": "OTHER"}
        )
        or 0.0
    )
    before_other_total = (
        REGISTRY.get_sample_value(
            "supernote_http_requests_total",
            {"method": "OTHER", "path": "/slow", "status": "200"},
        )
        or 0.0
    )

    req_task = asyncio.create_task(custom_client.request("PROPFIND", "/slow"))
    await entered.wait()
    assert (
        REGISTRY.get_sample_value(
            "supernote_http_requests_in_progress", {"method": "OTHER"}
        )
        == before_other_in_flight + 1.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_http_requests_in_progress", {"method": "PROPFIND"}
        )
        is None
    )

    release.set()
    slow_resp = await req_task
    assert slow_resp.status == 200
    assert (
        REGISTRY.get_sample_value(
            "supernote_http_requests_in_progress", {"method": "OTHER"}
        )
        == before_other_in_flight
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_http_requests_total",
            {"method": "OTHER", "path": "/slow", "status": "200"},
        )
        == before_other_total + 1.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_http_requests_total",
            {"method": "PROPFIND", "path": "/slow", "status": "200"},
        )
        is None
    )


async def test_http_cancelled_request_records_499_without_duration() -> None:
    """Verify CancelledError records status='499', decrements in-progress gauge, and skips latency observation."""

    async def _noop_long_poll(_r: web.Request) -> web.Response:
        return web.Response()

    app = web.Application(middlewares=[metrics_middleware])
    app.router.add_get("/long-poll", _noop_long_poll)

    cancel_499_labels = {"method": "GET", "path": "/long-poll", "status": "499"}
    cancel_500_labels = {"method": "GET", "path": "/long-poll", "status": "500"}
    cancel_dur_labels = {"method": "GET", "path": "/long-poll"}
    before_get_in_flight = (
        REGISTRY.get_sample_value(
            "supernote_http_requests_in_progress", {"method": "GET"}
        )
        or 0.0
    )
    before_499 = (
        REGISTRY.get_sample_value("supernote_http_requests_total", cancel_499_labels)
        or 0.0
    )
    before_500 = (
        REGISTRY.get_sample_value("supernote_http_requests_total", cancel_500_labels)
        or 0.0
    )
    before_dur = (
        REGISTRY.get_sample_value(
            "supernote_http_request_duration_seconds_count", cancel_dur_labels
        )
        or 0.0
    )

    fake_request = make_mocked_request("GET", "/long-poll", app=app)
    match_info = await app.router.resolve(fake_request)
    match_info.add_app(app)
    fake_request._match_info = match_info

    async def _raise_cancelled(_req: web.Request) -> web.StreamResponse:
        assert (
            REGISTRY.get_sample_value(
                "supernote_http_requests_in_progress", {"method": "GET"}
            )
            == before_get_in_flight + 1.0
        )
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await metrics_middleware(fake_request, _raise_cancelled)

    assert (
        REGISTRY.get_sample_value(
            "supernote_http_requests_in_progress", {"method": "GET"}
        )
        == before_get_in_flight
    )
    assert (
        REGISTRY.get_sample_value("supernote_http_requests_total", cancel_499_labels)
        == before_499 + 1.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_http_requests_total", cancel_500_labels)
        or 0.0
    ) == before_500
    assert (
        REGISTRY.get_sample_value(
            "supernote_http_request_duration_seconds_count", cancel_dur_labels
        )
        or 0.0
    ) == before_dur


async def test_metrics_disabled(
    server_config: ServerConfig, aiohttp_client: Any
) -> None:
    """Verify that the metrics endpoint is not registered when metrics_enabled is False."""
    server_config.metrics_enabled = False

    app = create_app(server_config)
    client = await aiohttp_client(app)

    resp = await client.get("/metrics")
    assert resp.status == 404


async def test_db_session_active_gauge(client: TestClient) -> None:
    """Verify DatabaseSessionManager increments and decrements active sessions gauge."""
    assert client.app is not None
    session_manager = client.app[SESSION_MANAGER_KEY]
    before = REGISTRY.get_sample_value("supernote_db_sessions_active") or 0.0

    async with session_manager.session():
        active_inside = REGISTRY.get_sample_value("supernote_db_sessions_active") or 0.0
        assert active_inside == before + 1.0

    after = REGISTRY.get_sample_value("supernote_db_sessions_active") or 0.0
    assert after == before


async def test_gemini_ai_metrics_and_tokens(aiohttp_server: Any) -> None:
    """Verify unified AI request, extended latency buckets, and token metrics for Gemini."""
    should_fail = False
    summary_mode = False

    async def handle_generate_content(request: web.Request) -> web.Response:
        if should_fail:
            return web.json_response(
                {
                    "error": {
                        "code": 404,
                        "message": "model not found",
                        "status": "NOT_FOUND",
                    }
                },
                status=404,
            )
        text = (
            json.dumps(
                {
                    "segments": [
                        {
                            "date_range": "2026-11-09",
                            "summary": "Daily notes",
                            "extracted_dates": ["2026-11-09"],
                            "page_refs": [1],
                        }
                    ]
                }
            )
            if summary_mode
            else "transcribed text"
        )
        return web.json_response(
            {
                "candidates": [{"content": {"parts": [{"text": text}]}}],
                "usageMetadata": {
                    "promptTokenCount": 250,
                    "candidatesTokenCount": 40,
                    "thoughtsTokenCount": 15,
                },
            }
        )

    async def handle_batch_embed(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "embeddings": [
                    {
                        "values": [0.1, 0.2, 0.3],
                        "statistics": {"tokenCount": 18},
                    }
                ]
            }
        )

    app = web.Application()
    app.router.add_post(
        "/v1beta/models/{model}:generateContent", handle_generate_content
    )
    app.router.add_post("/v1beta/models/{model}:batchEmbedContents", handle_batch_embed)
    server = await aiohttp_server(app)
    gemini = GeminiBackend(
        api_key="test-api-key",
        base_url=str(server.make_url("/")),
        provider="gemini",
    )
    ocr_model = InstrumentedOcrModel(GeminiOcrModel(gemini, "gemini-3-flash-preview"))
    summary_model = InstrumentedSummaryModel(
        GeminiSummaryModel(gemini, "gemini-3-flash-preview")
    )
    embed_model = InstrumentedEmbeddingModel(
        GeminiEmbeddingModel(gemini, "gemini-embedding-001")
    )

    ocr_labels = {
        "provider": "gemini",
        "model": "gemini-3-flash-preview",
        "stage": "ocr",
        "status": "success",
    }
    before_ocr = (
        REGISTRY.get_sample_value("supernote_ai_requests_total", ocr_labels) or 0.0
    )
    before_in_tok = (
        REGISTRY.get_sample_value(
            "supernote_ai_tokens_total",
            {
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
                "stage": "ocr",
                "token_type": "input",
            },
        )
        or 0.0
    )
    before_out_tok = (
        REGISTRY.get_sample_value(
            "supernote_ai_tokens_total",
            {
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
                "stage": "ocr",
                "token_type": "output",
            },
        )
        or 0.0
    )
    before_think_tok = (
        REGISTRY.get_sample_value(
            "supernote_ai_tokens_total",
            {
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
                "stage": "ocr",
                "token_type": "thinking",
            },
        )
        or 0.0
    )

    assert await ocr_model.extract_text(b"png", "prompt") == "transcribed text"

    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", ocr_labels)
        == before_ocr + 1.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_ai_tokens_total",
            {
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
                "stage": "ocr",
                "token_type": "input",
            },
        )
        == before_in_tok + 250.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_ai_tokens_total",
            {
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
                "stage": "ocr",
                "token_type": "output",
            },
        )
        == before_out_tok + 40.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_ai_tokens_total",
            {
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
                "stage": "ocr",
                "token_type": "thinking",
            },
        )
        == before_think_tok + 15.0
    )

    # Verify extended latency histogram buckets (> 10s up to 600s) are exported
    for bucket in PIPELINE_DURATION_BUCKETS:
        bucket_val = REGISTRY.get_sample_value(
            "supernote_ai_request_duration_seconds_bucket",
            {
                "provider": "gemini",
                "model": "gemini-3-flash-preview",
                "stage": "ocr",
                "le": str(bucket),
            },
        )
        assert bucket_val is not None
    top_bucket_val = REGISTRY.get_sample_value(
        "supernote_ai_request_duration_seconds_bucket",
        {
            "provider": "gemini",
            "model": "gemini-3-flash-preview",
            "stage": "ocr",
            "le": "600.0",
        },
    )
    assert top_bucket_val is not None and top_bucket_val >= 1.0

    # Summary stage attribution (distinct from OCR even on same model)
    summary_mode = True
    summary_labels = {
        "provider": "gemini",
        "model": "gemini-3-flash-preview",
        "stage": "summary",
        "status": "success",
    }
    before_summary = (
        REGISTRY.get_sample_value("supernote_ai_requests_total", summary_labels) or 0.0
    )
    await summary_model.summarize("Summarize")
    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", summary_labels)
        == before_summary + 1.0
    )

    # Embedding document vs query stage attribution & Vertex/Enterprise token statistics
    doc_labels = {
        "provider": "gemini",
        "model": "gemini-embedding-001",
        "stage": "embedding_doc",
        "status": "success",
    }
    query_labels = {
        "provider": "gemini",
        "model": "gemini-embedding-001",
        "stage": "embedding_query",
        "status": "success",
    }
    before_doc = (
        REGISTRY.get_sample_value("supernote_ai_requests_total", doc_labels) or 0.0
    )
    before_query = (
        REGISTRY.get_sample_value("supernote_ai_requests_total", query_labels) or 0.0
    )
    before_embed_tok = (
        REGISTRY.get_sample_value(
            "supernote_ai_tokens_total",
            {
                "provider": "gemini",
                "model": "gemini-embedding-001",
                "stage": "embedding_doc",
                "token_type": "input",
            },
        )
        or 0.0
    )
    await embed_model.embed("doc text", EmbeddingTaskType.RETRIEVAL_DOCUMENT)
    await embed_model.embed("query text", EmbeddingTaskType.RETRIEVAL_QUERY)
    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", doc_labels)
        == before_doc + 1.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", query_labels)
        == before_query + 1.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_ai_tokens_total",
            {
                "provider": "gemini",
                "model": "gemini-embedding-001",
                "stage": "embedding_doc",
                "token_type": "input",
            },
        )
        == before_embed_tok + 18.0
    )

    # Error tracking
    should_fail = True
    fail_labels = {
        "provider": "gemini",
        "model": "gemini-3-flash-preview",
        "stage": "ocr",
        "status": "failure",
    }
    before_fail = (
        REGISTRY.get_sample_value("supernote_ai_requests_total", fail_labels) or 0.0
    )
    with pytest.raises(AIError):
        await ocr_model.extract_text(b"png", "prompt")
    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", fail_labels)
        == before_fail + 1.0
    )

    # All 6 legacy per-vendor metrics are removed
    for legacy_metric in REMOVED_LEGACY_METRICS:
        assert (
            REGISTRY.get_sample_value(
                legacy_metric,
                {"operation": "generate_content", "status": "success"},
            )
            is None
        )
        assert (
            REGISTRY.get_sample_value(
                f"{legacy_metric}_count",
                {"operation": "generate_content"},
            )
            is None
        )


async def test_openai_ai_metrics_and_tokens(aiohttp_server: Any) -> None:
    """Verify mutually exclusive OpenAI token accounting and billed-failure tracking."""
    return_empty_choices = False

    async def handle_chat(request: web.Request) -> web.Response:
        if return_empty_choices:
            return web.json_response(
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 50,
                        "completion_tokens": 10,
                        "total_tokens": 60,
                    },
                }
            )
        return web.json_response(
            {
                "choices": [{"message": {"content": "not valid json"}}],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 60,
                    "total_tokens": 180,
                    "completion_tokens_details": {"reasoning_tokens": 25},
                },
            }
        )

    async def handle_embeddings(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "data": [{"embedding": [0.3, 0.4, 0.5]}],
                "usage": {"prompt_tokens": 14, "total_tokens": 14},
            }
        )

    app = web.Application()
    app.router.add_post("/v1/chat/completions", handle_chat)
    app.router.add_post("/v1/embeddings", handle_embeddings)
    server = await aiohttp_server(app)

    backend = OpenAIBackend(str(server.make_url("/v1")), provider="ollama")
    ocr_model = InstrumentedOcrModel(OpenAIOcrModel(backend, "gemma-vision"))
    summary_model = InstrumentedSummaryModel(
        OpenAISummaryModel(backend, "gemma-vision")
    )
    embed_model = InstrumentedEmbeddingModel(
        OpenAIEmbeddingModel(backend, "nomic-embed")
    )

    in_labels = {
        "provider": "ollama",
        "model": "gemma-vision",
        "stage": "ocr",
        "token_type": "input",
    }
    out_labels = {
        "provider": "ollama",
        "model": "gemma-vision",
        "stage": "ocr",
        "token_type": "output",
    }
    think_labels = {
        "provider": "ollama",
        "model": "gemma-vision",
        "stage": "ocr",
        "token_type": "thinking",
    }
    before_in = REGISTRY.get_sample_value("supernote_ai_tokens_total", in_labels) or 0.0
    before_out = (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", out_labels) or 0.0
    )
    before_think = (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", think_labels) or 0.0
    )

    # OpenAI completion_tokens=60 includes reasoning_tokens=25 -> output=35, thinking=25
    await ocr_model.extract_text(b"png", "Transcribe")
    assert (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", in_labels)
        == before_in + 120.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", out_labels)
        == before_out + 35.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", think_labels)
        == before_think + 25.0
    )

    # Summary JSON parse failure after HTTP 200 records status="failure"
    summary_fail_labels = {
        "provider": "ollama",
        "model": "gemma-vision",
        "stage": "summary",
        "status": "failure",
    }
    before_summary_fail = (
        REGISTRY.get_sample_value("supernote_ai_requests_total", summary_fail_labels)
        or 0.0
    )
    with pytest.raises(AIError, match="Failed to parse"):
        await summary_model.summarize("Summarize")
    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", summary_fail_labels)
        == before_summary_fail + 1.0
    )

    # HTTP 200 with empty `choices` (e.g. content filter) still records billed tokens + failure
    return_empty_choices = True
    ocr_fail_labels = {
        "provider": "ollama",
        "model": "gemma-vision",
        "stage": "ocr",
        "status": "failure",
    }
    before_ocr_fail = (
        REGISTRY.get_sample_value("supernote_ai_requests_total", ocr_fail_labels) or 0.0
    )
    before_in_filter = (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", in_labels) or 0.0
    )
    before_out_filter = (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", out_labels) or 0.0
    )
    with pytest.raises(AIError, match="during chat_completion"):
        await ocr_model.extract_text(b"png", "Blocked")
    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", ocr_fail_labels)
        == before_ocr_fail + 1.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", in_labels)
        == before_in_filter + 50.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", out_labels)
        == before_out_filter + 10.0
    )

    # Embedding records input tokens relative to baseline
    embed_tok_labels = {
        "provider": "ollama",
        "model": "nomic-embed",
        "stage": "embedding_query",
        "token_type": "input",
    }
    before_embed_tok = (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", embed_tok_labels) or 0.0
    )
    await embed_model.embed("search query", EmbeddingTaskType.RETRIEVAL_QUERY)
    assert (
        REGISTRY.get_sample_value("supernote_ai_tokens_total", embed_tok_labels)
        == before_embed_tok + 14.0
    )


async def test_ai_request_cancellation_and_token_guards() -> None:
    """Verify CancelledError records status='cancelled' without polluting failure/latency."""
    base_labels = {
        "provider": "gemini",
        "model": "cancel-test-model",
        "stage": "embedding_query",
    }
    cancel_labels = {**base_labels, "status": "cancelled"}
    fail_labels = {**base_labels, "status": "failure"}

    before_cancel = (
        REGISTRY.get_sample_value("supernote_ai_requests_total", cancel_labels) or 0.0
    )
    before_fail = (
        REGISTRY.get_sample_value("supernote_ai_requests_total", fail_labels) or 0.0
    )
    before_dur_count = (
        REGISTRY.get_sample_value(
            "supernote_ai_request_duration_seconds_count", base_labels
        )
        or 0.0
    )
    before_cancel_tok = (
        REGISTRY.get_sample_value(
            "supernote_ai_tokens_total",
            {**base_labels, "token_type": "input"},
        )
        or 0.0
    )

    with pytest.raises(asyncio.CancelledError):
        with track_ai_request(
            provider="gemini",
            model="cancel-test-model",
            stage=AIStage.EMBEDDING_QUERY,
        ):
            # Mismatched provider and invalid/non-finite token values are safely ignored
            record_ai_tokens(
                provider="other-provider",
                input_tokens=999,
            )
            record_ai_tokens(
                provider="gemini",
                input_tokens=float("nan"),
                output_tokens=float("inf"),
                thinking_tokens=True,
            )
            record_ai_tokens(
                provider="gemini",
                input_tokens=0,
                output_tokens=-5,
                thinking_tokens=0.2,
            )
            record_ai_tokens(
                provider="gemini",
                input_tokens=12.9,
            )
            raise asyncio.CancelledError

    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", cancel_labels)
        == before_cancel + 1.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", fail_labels) or 0.0
    ) == before_fail
    assert (
        REGISTRY.get_sample_value(
            "supernote_ai_request_duration_seconds_count", base_labels
        )
        or 0.0
    ) == before_dur_count
    assert (
        REGISTRY.get_sample_value(
            "supernote_ai_tokens_total",
            {**base_labels, "token_type": "input"},
        )
        == before_cancel_tok + 12.0
    )


def test_note_processing_run_metrics_tracker() -> None:
    """Verify `.note` run counter seeding, outcome tracking, buckets, and cancellation."""
    init_note_processing_metrics()
    for mode in NoteProcessingMode:
        for status in ("success", "failure"):
            assert (
                REGISTRY.get_sample_value(
                    "supernote_note_processing_runs_total",
                    {"mode": mode.value, "status": status},
                )
                is not None
            )

    full_ok = {"mode": "full", "status": "success"}
    full_fail = {"mode": "full", "status": "failure"}
    on_demand_cancel = {"mode": "on_demand", "status": "cancelled"}

    before_ok = (
        REGISTRY.get_sample_value("supernote_note_processing_runs_total", full_ok)
        or 0.0
    )
    before_fail = (
        REGISTRY.get_sample_value("supernote_note_processing_runs_total", full_fail)
        or 0.0
    )
    before_cancel = (
        REGISTRY.get_sample_value(
            "supernote_note_processing_runs_total", on_demand_cancel
        )
        or 0.0
    )
    before_full_dur = (
        REGISTRY.get_sample_value(
            "supernote_note_processing_duration_seconds_count", {"mode": "full"}
        )
        or 0.0
    )
    before_on_demand_dur = (
        REGISTRY.get_sample_value(
            "supernote_note_processing_duration_seconds_count", {"mode": "on_demand"}
        )
        or 0.0
    )

    with track_note_processing_run(mode=NoteProcessingMode.FULL) as run:
        run.set_succeeded(True)

    with track_note_processing_run(mode=NoteProcessingMode.FULL) as run:
        run.set_succeeded(False)

    with pytest.raises(RuntimeError, match="db failure"):
        with track_note_processing_run(mode=NoteProcessingMode.FULL):
            raise RuntimeError("db failure")

    with pytest.raises(asyncio.CancelledError):
        with track_note_processing_run(mode=NoteProcessingMode.ON_DEMAND) as run:
            run.set_succeeded(True)
            raise asyncio.CancelledError

    assert (
        REGISTRY.get_sample_value("supernote_note_processing_runs_total", full_ok)
        == before_ok + 1.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_note_processing_runs_total", full_fail)
        == before_fail + 2.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_note_processing_runs_total", on_demand_cancel
        )
        == before_cancel + 1.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_note_processing_duration_seconds_count", {"mode": "full"}
        )
        == before_full_dur + 3.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_note_processing_duration_seconds_count", {"mode": "on_demand"}
        )
        or 0.0
    ) == before_on_demand_dur

    for bucket in PIPELINE_DURATION_BUCKETS:
        assert (
            REGISTRY.get_sample_value(
                "supernote_note_processing_duration_seconds_bucket",
                {"mode": "full", "le": str(bucket)},
            )
            is not None
        )

    # Calling record_ai_tokens outside track_ai_request is a safe no-op
    record_ai_tokens(
        provider="gemini", input_tokens=999, output_tokens=999, thinking_tokens=999
    )


def test_record_note_page_diff_metrics() -> None:
    """Verify page-diff counter seeding and mutually exclusive increments."""
    init_note_processing_metrics()
    change_types = ("added", "modified", "moved", "unchanged", "deleted")
    for change_type in change_types:
        assert (
            REGISTRY.get_sample_value(
                "supernote_note_pages_parsed_total",
                {"change_type": change_type},
            )
            is not None
        )

    before_counts = {
        ct: (
            REGISTRY.get_sample_value(
                "supernote_note_pages_parsed_total",
                {"change_type": ct},
            )
            or 0.0
        )
        for ct in change_types
    }

    record_note_page_diff(
        added=2,
        modified=1,
        moved=3,
        unchanged=4,
        deleted=2,
    )
    record_note_page_diff(
        moved=1,
        unchanged=5,
    )

    assert (
        REGISTRY.get_sample_value(
            "supernote_note_pages_parsed_total", {"change_type": "added"}
        )
        == before_counts["added"] + 2.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_note_pages_parsed_total", {"change_type": "modified"}
        )
        == before_counts["modified"] + 1.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_note_pages_parsed_total", {"change_type": "moved"}
        )
        == before_counts["moved"] + 4.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_note_pages_parsed_total", {"change_type": "unchanged"}
        )
        == before_counts["unchanged"] + 9.0
    )
    assert (
        REGISTRY.get_sample_value(
            "supernote_note_pages_parsed_total", {"change_type": "deleted"}
        )
        == before_counts["deleted"] + 2.0
    )
