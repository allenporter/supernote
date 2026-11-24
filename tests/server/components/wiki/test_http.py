"""HTTP integration tests for `/api/extended/wiki/*` routes."""

from __future__ import annotations

import io
import zipfile
from typing import Any

from supernote.models.user import UserRegisterDTO
from supernote.server.app import create_app
from supernote.server.config import AiConfig, ModelConfig, ServerConfig
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.keys import USER_SERVICE_KEY
from supernote.server.services.user import UserService


async def _make_wiki_client(
    aiohttp_client: Any,
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
) -> tuple[Any, dict[str, str], dict[str, str]]:
    _ = session_manager
    server_config.mcp_enabled = False
    server_config.metrics_enabled = False
    server_config.web_enabled = False
    server_config.ai = AiConfig(text=ModelConfig(provider="fake", model="fake-wiki"))
    server_config.wiki = {"enabled": True}
    app = create_app(server_config)
    client = await aiohttp_client(app)
    user_service: UserService = app[USER_SERVICE_KEY]
    await user_service.create_user(
        UserRegisterDTO(email="alice@example.com", password="a" * 32)
    )
    await user_service.create_user(
        UserRegisterDTO(email="bob@example.com", password="b" * 32)
    )
    t1 = await user_service.create_session("alice@example.com")
    t2 = await user_service.create_session("bob@example.com")
    return client, {"x-access-token": t1}, {"x-access-token": t2}


async def test_wiki_http_crud_conflict_search_lint_and_export(
    aiohttp_client: Any,
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
) -> None:
    client, h1, h2 = await _make_wiki_client(
        aiohttp_client, server_config, session_manager
    )

    # Unauthenticated request rejected.
    unauth = await client.get("/api/extended/wiki/pages")
    assert unauth.status == 401

    # Create page via PUT.
    put_resp = await client.put(
        "/api/extended/wiki/pages/projects/apollo",
        headers=h1,
        json={
            "title": "Apollo",
            "page_kind": "project",
            "summary": "Moonshot",
            "body_md": "See [[entities/missing]].",
            "aliases": ["Project Apollo"],
        },
    )
    assert put_resp.status == 200
    page = (await put_resp.json())["page"]
    assert page["slug"] == "projects/apollo"
    assert page["version"] == 1

    # Optimistic concurrency conflict returns 409.
    conflict = await client.put(
        "/api/extended/wiki/pages/projects/apollo",
        headers=h1,
        json={"title": "Apollo", "body_md": "Stale", "expected_version": 99},
    )
    assert conflict.status == 409

    # Cross-user isolation: user 2 cannot read user 1's page.
    other = await client.get("/api/extended/wiki/pages/projects/apollo", headers=h2)
    assert other.status == 404

    # Search and revisions.
    search = await client.get("/api/extended/wiki/search?q=apollo", headers=h1)
    assert search.status == 200
    assert (await search.json())["hits"][0]["slug"] == "projects/apollo"

    revs = await client.get("/api/extended/wiki/revisions/projects/apollo", headers=h1)
    assert revs.status == 200
    assert len((await revs.json())["revisions"]) == 1

    # Compile (lint mode) & resolve lint issue.
    lint_run = await client.post(
        "/api/extended/wiki/compile", headers=h1, json={"mode": "lint"}
    )
    assert lint_run.status == 200
    issues = (await lint_run.json())["issues"]
    assert any(i["issue_type"] == "broken_link" for i in issues)

    resolve = await client.post(
        f"/api/extended/wiki/lint/{issues[0]['issue_id']}/resolve",
        headers=h1,
        json={"status": "dismissed"},
    )
    assert resolve.status == 200
    assert (await resolve.json())["issue"]["status"] == "dismissed"

    # Markdown and ZIP export.
    md_resp = await client.get(
        "/api/extended/wiki/export/projects/apollo.md", headers=h1
    )
    assert md_resp.status == 200
    assert "slug: projects/apollo" in await md_resp.text()

    zip_resp = await client.get("/api/extended/wiki/export.zip", headers=h1)
    assert zip_resp.status == 200
    with zipfile.ZipFile(io.BytesIO(await zip_resp.read())) as zf:
        assert zf.namelist() == ["projects/apollo.md"]

    # Status and delete.
    status_resp = await client.get("/api/extended/wiki/status", headers=h1)
    assert status_resp.status == 200
    assert (await status_resp.json())["status"]["page_count"] == 1

    del_resp = await client.delete(
        "/api/extended/wiki/pages/projects/apollo", headers=h1
    )
    assert del_resp.status == 200
    assert (
        await client.get("/api/extended/wiki/pages/projects/apollo", headers=h1)
    ).status == 404
