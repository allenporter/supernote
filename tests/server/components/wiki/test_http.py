"""HTTP integration tests for `/api/extended/wiki/*` routes."""

from __future__ import annotations

import io
import zipfile
from typing import Any
from unittest.mock import patch

from supernote.models.user import UserRegisterDTO
from supernote.server.ai.base import AIError
from supernote.server.app import create_app
from supernote.server.components.wiki.compiler import WIKI_COMPILER_KEY
from supernote.server.config import AiConfig, ModelConfig, ServerConfig
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.keys import USER_SERVICE_KEY
from supernote.server.services.user import UserService


async def _make_wiki_client(
    aiohttp_client: Any,
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
    *,
    wiki_enabled: bool = True,
) -> tuple[Any, dict[str, str], dict[str, str], dict[str, str]]:
    _ = session_manager
    server_config.mcp_enabled = False
    server_config.metrics_enabled = False
    server_config.web_enabled = False
    server_config.ai = AiConfig(text=ModelConfig(provider="fake", model="fake-wiki"))
    server_config.wiki = {"enabled": wiki_enabled}
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
    alice_id = await user_service.get_user_id("alice@example.com")
    assert alice_id is not None
    api_key, _ = await user_service.create_api_key(alice_id, "external-agent")
    return (
        client,
        {"x-access-token": t1},
        {"x-access-token": t2},
        {"Authorization": f"Bearer {api_key}"},
    )


async def test_wiki_http_disabled_returns_404(
    aiohttp_client: Any,
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
) -> None:
    client, h1, _, _ = await _make_wiki_client(
        aiohttp_client, server_config, session_manager, wiki_enabled=False
    )
    resp = await client.get("/api/extended/wiki/pages", headers=h1)
    assert resp.status == 404


async def test_wiki_http_crud_conflict_search_and_isolation(
    aiohttp_client: Any,
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
) -> None:
    client, h1, h2, _ = await _make_wiki_client(
        aiohttp_client, server_config, session_manager
    )

    assert (await client.get("/api/extended/wiki/pages")).status == 401

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
    assert page["edit_policy"] == "protected_prose"

    listed = await client.get("/api/extended/wiki/pages?page_kind=project", headers=h1)
    assert listed.status == 200
    assert [p["slug"] for p in (await listed.json())["pages"]] == ["projects/apollo"]

    conflict = await client.put(
        "/api/extended/wiki/pages/projects/apollo",
        headers=h1,
        json={"title": "Apollo", "body_md": "Stale", "expected_version": 99},
    )
    assert conflict.status == 409

    # Cross-user isolation: bob cannot read alice's page.
    assert (
        await client.get("/api/extended/wiki/pages/projects/apollo", headers=h2)
    ).status == 404

    search = await client.get("/api/extended/wiki/search?q=apollo", headers=h1)
    assert search.status == 200
    assert (await search.json())["hits"][0]["slug"] == "projects/apollo"

    revs = await client.get("/api/extended/wiki/revisions/projects/apollo", headers=h1)
    assert revs.status == 200
    assert len((await revs.json())["revisions"]) == 1

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


async def test_wiki_http_lint_compile_and_export(
    aiohttp_client: Any,
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
) -> None:
    client, h1, _, _ = await _make_wiki_client(
        aiohttp_client, server_config, session_manager
    )

    await client.put(
        "/api/extended/wiki/pages/projects/apollo",
        headers=h1,
        json={"title": "Apollo", "body_md": "See [[entities/missing]]."},
    )

    lint_run = await client.post(
        "/api/extended/wiki/compile", headers=h1, json={"mode": "lint"}
    )
    assert lint_run.status == 200
    issues = (await lint_run.json())["issues"]
    assert any(i["issue_type"] == "broken_link" for i in issues)

    listed_lint = await client.get("/api/extended/wiki/lint?status=open", headers=h1)
    assert listed_lint.status == 200
    assert len((await listed_lint.json())["issues"]) >= 1

    resolve = await client.post(
        f"/api/extended/wiki/lint/{issues[0]['issue_id']}/resolve",
        headers=h1,
        json={"status": "dismissed"},
    )
    assert resolve.status == 200
    assert (await resolve.json())["issue"]["status"] == "dismissed"

    inc = await client.post(
        "/api/extended/wiki/compile", headers=h1, json={"mode": "incremental"}
    )
    assert inc.status == 200
    assert (await inc.json())["mode"] == "incremental"

    bf = await client.post(
        "/api/extended/wiki/compile",
        headers=h1,
        json={"mode": "backfill", "max_files": 2},
    )
    assert bf.status == 200
    assert (await bf.json())["mode"] == "backfill"

    md_resp = await client.get(
        "/api/extended/wiki/export/projects/apollo.md", headers=h1
    )
    assert md_resp.status == 200
    assert "slug: projects/apollo" in await md_resp.text()

    zip_resp = await client.get("/api/extended/wiki/export.zip", headers=h1)
    assert zip_resp.status == 200
    with zipfile.ZipFile(io.BytesIO(await zip_resp.read())) as zf:
        assert zf.namelist() == ["projects/apollo.md"]


async def test_wiki_http_non_interactive_api_key_trust_boundaries(
    aiohttp_client: Any,
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
) -> None:
    """API keys write as agent, cannot set edit_policy, cannot overwrite user pages, and cannot delete or trigger compile."""
    client, h_user, _, h_key = await _make_wiki_client(
        aiohttp_client, server_config, session_manager
    )

    # API key cannot set edit_policy even on a brand-new page.
    lock_attempt = await client.put(
        "/api/extended/wiki/pages/projects/agent-locked",
        headers=h_key,
        json={"title": "Locked", "body_md": "Body", "edit_policy": "locked"},
    )
    assert lock_attempt.status == 403

    # API key creates a normal page with author_kind="agent" and edit_policy="auto".
    created = await client.put(
        "/api/extended/wiki/pages/projects/agent-note",
        headers=h_key,
        json={"title": "Agent Note", "body_md": "Compiled by agent"},
    )
    assert created.status == 200
    created_page = (await created.json())["page"]
    assert created_page["last_author_kind"] == "agent"
    assert created_page["edit_policy"] == "auto"

    # Interactive user edits the page -> escalates to protected_prose.
    user_edit = await client.put(
        "/api/extended/wiki/pages/projects/agent-note",
        headers=h_user,
        json={"title": "Agent Note", "body_md": "Human refined"},
    )
    assert user_edit.status == 200
    assert (await user_edit.json())["page"]["edit_policy"] == "protected_prose"

    # API key is now blocked from overwriting the human-protected page.
    blocked_put = await client.put(
        "/api/extended/wiki/pages/projects/agent-note",
        headers=h_key,
        json={"title": "Agent Note", "body_md": "Overwrite"},
    )
    assert blocked_put.status == 403

    # API key is denied DELETE and POST /compile via @interactive_session_only.
    assert (
        await client.delete(
            "/api/extended/wiki/pages/projects/agent-note", headers=h_key
        )
    ).status == 403
    assert (
        await client.post(
            "/api/extended/wiki/compile", headers=h_key, json={"mode": "lint"}
        )
    ).status == 403


async def test_wiki_http_input_validation_and_upstream_errors(
    aiohttp_client: Any,
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
) -> None:
    client, h1, _, _ = await _make_wiki_client(
        aiohttp_client, server_config, session_manager
    )

    # Null title must not coerce to "None".
    assert (
        await client.put(
            "/api/extended/wiki/pages/projects/bad",
            headers=h1,
            json={"title": None, "body_md": "x"},
        )
    ).status == 400

    # Non-dict source_refs entry must be rejected instead of silently dropped.
    assert (
        await client.put(
            "/api/extended/wiki/pages/projects/bad",
            headers=h1,
            json={"title": "Ok", "body_md": "x", "source_refs": ["note_page:1:p1"]},
        )
    ).status == 400

    # Float expected_version must be rejected instead of truncated.
    assert (
        await client.put(
            "/api/extended/wiki/pages/projects/bad",
            headers=h1,
            json={"title": "Ok", "body_md": "x", "expected_version": 1.9},
        )
    ).status == 400

    # Invalid filter enums return 400.
    assert (
        await client.get("/api/extended/wiki/pages?page_kind=bogus", headers=h1)
    ).status == 400
    assert (
        await client.get("/api/extended/wiki/lint?status=bogus", headers=h1)
    ).status == 400

    # Non-object JSON body and out-of-range max_files return 400 on /compile.
    assert (
        await client.post("/api/extended/wiki/compile", headers=h1, json=["bad"])
    ).status == 400
    assert (
        await client.post(
            "/api/extended/wiki/compile",
            headers=h1,
            json={"mode": "backfill", "max_files": 0},
        )
    ).status == 400
    assert (
        await client.post(
            "/api/extended/wiki/compile", headers=h1, json={"mode": "unknown"}
        )
    ).status == 400

    # Upstream AIError or LLM parse ValueError returns 502 instead of 500.
    compiler = client.app[WIKI_COMPILER_KEY]
    with patch.object(compiler, "compile_user_delta", side_effect=AIError("503")):
        assert (
            await client.post(
                "/api/extended/wiki/compile", headers=h1, json={"mode": "incremental"}
            )
        ).status == 502
    with patch.object(
        compiler, "compile_user_delta", side_effect=ValueError("bad json")
    ):
        assert (
            await client.post(
                "/api/extended/wiki/compile", headers=h1, json={"mode": "incremental"}
            )
        ).status == 502
