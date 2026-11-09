"""Tests for ExtendedClient."""

from typing import Any

from aiohttp import web
from pytest_aiohttp import AiohttpClient

from supernote.client.auth import ConstantAuth
from supernote.client.client import Client
from supernote.client.extended import ExtendedClient
from supernote.models.base import ProcessingStatus


async def test_extended_client_methods(aiohttp_client: AiohttpClient) -> None:
    """Verify all ExtendedClient methods send expected payloads and parse typed VOs."""
    recorded: list[tuple[str, str, dict[str, Any] | None]] = []

    async def handle_csrf(_request: web.Request) -> web.Response:
        return web.Response(text="ok", headers={"X-XSRF-TOKEN": "csrf-token"})

    async def handle_summaries(request: web.Request) -> web.Response:
        recorded.append((request.method, request.path, await request.json()))
        return web.json_response(
            {"success": True, "summaryDOList": [], "totalRecords": 0}
        )

    async def handle_search(request: web.Request) -> web.Response:
        recorded.append((request.method, request.path, await request.json()))
        return web.json_response(
            {
                "success": True,
                "results": [
                    {
                        "fileId": 10,
                        "fileName": "Notes.note",
                        "pageIndex": 1,
                        "pageId": "P1",
                        "score": 0.9,
                        "textPreview": "match",
                        "date": "2026-11-01",
                    }
                ],
            }
        )

    async def handle_transcript(request: web.Request) -> web.Response:
        recorded.append((request.method, request.path, await request.json()))
        return web.json_response(
            {
                "success": True,
                "pages": [
                    {
                        "pageIndex": 0,
                        "pageId": "P0",
                        "text": "Hello",
                        "date": None,
                    }
                ],
            }
        )

    async def handle_processing_status(request: web.Request) -> web.Response:
        recorded.append((request.method, request.path, await request.json()))
        return web.json_response({"success": True, "statusMap": {"10": "COMPLETED"}})

    async def handle_system_tasks(request: web.Request) -> web.Response:
        recorded.append((request.method, request.path, None))
        return web.json_response(
            {
                "success": True,
                "tasks": [
                    {
                        "id": 1,
                        "fileId": 10,
                        "taskType": "OCR",
                        "key": "P0",
                        "status": "COMPLETED",
                        "retryCount": 0,
                        "updateTime": 1000,
                        "lastError": None,
                    }
                ],
            }
        )

    async def handle_ai_status(request: web.Request) -> web.Response:
        recorded.append((request.method, request.path, None))
        return web.json_response(
            {
                "success": True,
                "hasApiKey": True,
                "ocrEnabled": True,
                "ocrModel": "apple-vision",
                "summaryEnabled": True,
                "summaryModel": "ollama/qwen2.5",
                "vectorSearchEnabled": False,
                "embeddingModel": None,
                "model": "apple-vision",
            }
        )

    async def handle_note_cover(request: web.Request) -> web.Response:
        recorded.append((request.method, request.path, await request.json()))
        return web.json_response(
            {
                "success": True,
                "url": "http://127.0.0.1/api/oss/png/10/0?sig=abc",
            }
        )

    app = web.Application()
    app.router.add_get("/api/csrf", handle_csrf)
    app.router.add_post("/api/extended/file/summary/list", handle_summaries)
    app.router.add_post("/api/extended/search", handle_search)
    app.router.add_post("/api/extended/transcript", handle_transcript)
    app.router.add_post(
        "/api/extended/file/processing/status", handle_processing_status
    )
    app.router.add_get("/api/extended/system/tasks", handle_system_tasks)
    app.router.add_get("/api/extended/ai/status", handle_ai_status)
    app.router.add_post("/api/extended/file/note/cover", handle_note_cover)

    test_client = await aiohttp_client(app)
    base_client = Client(
        test_client.session,
        host=str(test_client.make_url("")),
        auth=ConstantAuth("token-123"),
    )
    ext = ExtendedClient(base_client)

    summaries = await ext.list_summaries(file_id=10)
    assert summaries.total_records == 0

    search_vo = await ext.search(query="match", top_n=2, name_filter="Notes")
    assert len(search_vo.results) == 1
    assert search_vo.results[0].file_id == 10

    transcript_vo = await ext.get_transcript(file_id=10, start_index=0, end_index=1)
    assert len(transcript_vo.pages) == 1
    assert transcript_vo.pages[0].text == "Hello"

    status_vo = await ext.get_processing_status(file_ids=[10])
    assert status_vo.status_map == {"10": ProcessingStatus.COMPLETED}

    tasks_vo = await ext.list_system_tasks()
    assert len(tasks_vo.tasks) == 1
    assert tasks_vo.tasks[0].status == ProcessingStatus.COMPLETED

    ai_vo = await ext.get_ai_status()
    assert ai_vo.has_api_key is True
    assert ai_vo.ocr_enabled is True
    assert ai_vo.ocr_model == "apple-vision"
    assert ai_vo.summary_enabled is True
    assert ai_vo.summary_model == "ollama/qwen2.5"
    assert ai_vo.vector_search_enabled is False
    assert ai_vo.embedding_model is None
    assert ai_vo.model == "apple-vision"

    cover_vo = await ext.get_note_cover(file_id=10)
    assert cover_vo.url == "http://127.0.0.1/api/oss/png/10/0?sig=abc"

    assert recorded == [
        ("POST", "/api/extended/file/summary/list", {"fileId": "10"}),
        (
            "POST",
            "/api/extended/search",
            {
                "query": "match",
                "topN": 2,
                "nameFilter": "Notes",
                "dateAfter": None,
                "dateBefore": None,
            },
        ),
        (
            "POST",
            "/api/extended/transcript",
            {"fileId": "10", "startIndex": 0, "endIndex": 1},
        ),
        ("POST", "/api/extended/file/processing/status", {"fileIds": ["10"]}),
        ("GET", "/api/extended/system/tasks", None),
        ("GET", "/api/extended/ai/status", None),
        ("POST", "/api/extended/file/note/cover", {"fileId": "10"}),
    ]
