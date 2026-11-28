"""HTTP platform tests for `supernote.server.components.timeline.http`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.server.constants import CACHE_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageMetadataDO
from supernote.server.db.models.summary import SummaryDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.keys import BLOB_STORAGE_KEY, COMPONENT_LOADER_KEY
from supernote.server.utils.paths import get_page_png_path


def _utc_ms(year: int, month: int, day: int, hour: int = 12) -> int:
    return int(datetime(year, month, day, hour, 0, 0, tzinfo=UTC).timestamp() * 1000)


async def _seed_single_page(
    session_manager: DatabaseSessionManager, user_id: int
) -> tuple[int, str]:
    file_id = 3001
    page_id = "P20260314120000000000AAAAAAAAAAAA"
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=file_id,
                    user_id=user_id,
                    storage_key="k3001",
                    file_name="Journal.note",
                    directory_id=0,
                    is_active="Y",
                    create_time=_utc_ms(2026, 3, 14),
                ),
                NotePageMetadataDO(
                    user_id=user_id,
                    file_id=file_id,
                    page_index=0,
                    page_id=page_id,
                    has_ink=True,
                    has_drawables=True,
                    page_json="{}",
                ),
            ]
        )
        await session.commit()
    return file_id, page_id


async def test_timeline_pages_signs_cached_png_when_conversion_loaded(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    assert client.app is not None
    file_id, page_id = await _seed_single_page(session_manager, test_user_id)
    png_key = get_page_png_path(file_id, page_id)
    await client.app[BLOB_STORAGE_KEY].put(CACHE_BUCKET, png_key, b"\x89PNG\r\n")

    resp = await client.post(
        "/api/extended/timeline/pages", json={}, headers=auth_headers
    )
    assert resp.status == 200
    body = await resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["imageUrl"] is not None
    assert f"/api/oss/png/{file_id}/0" in body["items"][0]["imageUrl"]


async def test_timeline_pages_omits_image_url_when_conversion_not_loaded(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    assert client.app is not None
    file_id, page_id = await _seed_single_page(session_manager, test_user_id)
    png_key = get_page_png_path(file_id, page_id)
    await client.app[BLOB_STORAGE_KEY].put(CACHE_BUCKET, png_key, b"\x89PNG\r\n")

    loader = client.app[COMPONENT_LOADER_KEY]
    with patch.object(loader, "get", return_value=None):
        resp = await client.post(
            "/api/extended/timeline/pages", json={}, headers=auth_headers
        )
    assert resp.status == 200
    body = await resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["imageUrl"] is None


async def test_timeline_days_route_returns_counts(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    await _seed_single_page(session_manager, test_user_id)

    resp = await client.post(
        "/api/extended/timeline/days",
        json={"startDate": "2026-03-01", "endDate": "2026-03-31"},
        headers=auth_headers,
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["days"] == [
        {
            "date": "2026-03-14",
            "count": 1,
            "createdCount": 1,
            "editedCount": 0,
            "datedCount": 0,
        }
    ]


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/extended/timeline/pages", {"startDate": "bad"}),
        ("/api/extended/timeline/pages", {"cursor": "bad"}),
        ("/api/extended/timeline/pages", {"limit": 500}),
        ("/api/extended/timeline/days", {"endDate": "bad"}),
        (
            "/api/extended/timeline/days",
            {"startDate": "2026-03-20", "endDate": "2026-03-10"},
        ),
    ],
)
async def test_timeline_routes_return_400_for_invalid_payloads(
    client: TestClient,
    auth_headers: dict[str, str],
    path: str,
    payload: dict[str, object],
) -> None:
    resp = await client.post(path, json=payload, headers=auth_headers)
    assert resp.status == 400


async def test_timeline_pages_gates_summary_enrichment_on_summary_component(
    client: TestClient,
    auth_headers: dict[str, str],
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    assert client.app is not None
    file_id, _ = await _seed_single_page(session_manager, test_user_id)
    async with session_manager.session() as session:
        session.add(
            SummaryDO(
                user_id=test_user_id,
                file_id=file_id,
                name="Journal",
                unique_identifier="sum-3001",
                is_summary_group=False,
                is_deleted=False,
                extra_metadata=json.dumps(
                    {
                        "segments": [
                            {
                                "date_range": "2026-03-20",
                                "summary": "Handwritten planner entry",
                                "extracted_dates": ["2026-03-20"],
                                "page_refs": [1],
                            }
                        ]
                    }
                ),
            )
        )
        await session.commit()

    resp = await client.post(
        "/api/extended/timeline/pages", json={}, headers=auth_headers
    )
    assert resp.status == 200
    items = (await resp.json())["items"]
    assert [(i["date"], i["sources"], i["summary"]) for i in items] == [
        ("2026-03-20", ["dated"], "Handwritten planner entry"),
        ("2026-03-14", ["created"], None),
    ]

    loader = client.app[COMPONENT_LOADER_KEY]
    with patch.object(loader, "get", return_value=None):
        resp_disabled = await client.post(
            "/api/extended/timeline/pages", json={}, headers=auth_headers
        )
    assert resp_disabled.status == 200
    disabled_items = (await resp_disabled.json())["items"]
    assert [(i["date"], i["sources"], i["summary"]) for i in disabled_items] == [
        ("2026-03-14", ["created"], None),
    ]
