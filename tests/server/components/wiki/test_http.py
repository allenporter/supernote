"""HTTP integration tests for `/api/extended/wiki/*` routes via `WikiClient`."""

from __future__ import annotations

import io
import zipfile
from typing import Any
from unittest.mock import patch

import pytest

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.exceptions import (
    ApiException,
    BadRequestException,
    NotFoundException,
)
from supernote.client.wiki import WikiClient
from supernote.models.user import UserRegisterDTO
from supernote.server.ai.base import AIError
from supernote.server.app import create_app
from supernote.server.components.wiki.compiler import WIKI_COMPILER_KEY
from supernote.server.config import AiConfig, ModelConfig, ServerConfig
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.keys import USER_SERVICE_KEY
from supernote.server.services.user import UserService


def _wrap_wiki_client(raw_client: Any, token: str) -> WikiClient:
    class _TokenAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return token

    return WikiClient(
        Client(
            raw_client.session,
            auth=_TokenAuth(),
            host=str(raw_client.make_url("")),
        )
    )


async def _make_wiki_env(
    aiohttp_client: Any,
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
    *,
    wiki_enabled: bool = True,
) -> tuple[Any, WikiClient, WikiClient, dict[str, str], dict[str, str]]:
    _ = session_manager
    server_config.mcp_enabled = False
    server_config.metrics_enabled = False
    server_config.web_enabled = False
    server_config.ai = AiConfig(text=ModelConfig(provider="fake", model="fake-wiki"))
    server_config.wiki = {"enabled": wiki_enabled}
    app = create_app(server_config)
    raw_client = await aiohttp_client(app)
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
        raw_client,
        _wrap_wiki_client(raw_client, t1),
        _wrap_wiki_client(raw_client, t2),
        {"x-access-token": t1},
        {"Authorization": f"Bearer {api_key}"},
    )


async def test_wiki_http_disabled_returns_404(
    aiohttp_client: Any,
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
) -> None:
    _, alice_wiki, _, _, _ = await _make_wiki_env(
        aiohttp_client, server_config, session_manager, wiki_enabled=False
    )
    with pytest.raises(NotFoundException):
        await alice_wiki.list_pages()


async def test_wiki_http_crud_conflict_search_and_isolation(
    aiohttp_client: Any,
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
) -> None:
    raw_client, alice_wiki, bob_wiki, _, _ = await _make_wiki_env(
        aiohttp_client, server_config, session_manager
    )

    assert (await raw_client.get("/api/extended/wiki/pages")).status == 401

    page = await alice_wiki.upsert_page(
        "projects/apollo",
        title="Apollo",
        page_kind="project",
        summary="Moonshot",
        body_md="See [[entities/missing]].",
        aliases=["Project Apollo"],
    )
    assert page.slug == "projects/apollo"
    assert page.version == 1
    assert page.edit_policy == "protected_prose"

    listed = await alice_wiki.list_pages(page_kind="project")
    assert [p.slug for p in listed] == ["projects/apollo"]

    with pytest.raises(ApiException):
        await alice_wiki.upsert_page(
            "projects/apollo",
            title="Apollo",
            body_md="Stale",
            expected_version=99,
        )

    # Cross-user isolation: bob cannot read alice's page.
    with pytest.raises(NotFoundException):
        await bob_wiki.get_page("projects/apollo")

    hits = await alice_wiki.search("apollo")
    assert hits[0].slug == "projects/apollo"

    revs = await alice_wiki.list_revisions("projects/apollo")
    assert len(revs) == 1

    status = await alice_wiki.get_status()
    assert status.page_count == 1

    assert await alice_wiki.delete_page("projects/apollo") is True
    with pytest.raises(NotFoundException):
        await alice_wiki.get_page("projects/apollo")


async def test_wiki_http_lint_compile_and_export(
    aiohttp_client: Any,
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
) -> None:
    _, alice_wiki, _, _, _ = await _make_wiki_env(
        aiohttp_client, server_config, session_manager
    )

    await alice_wiki.upsert_page(
        "projects/apollo",
        title="Apollo",
        body_md="See [[entities/missing]].",
    )

    lint_run = await alice_wiki.compile(mode="lint")
    assert lint_run.issues is not None
    assert any(i.issue_type == "broken_link" for i in lint_run.issues)

    open_issues = await alice_wiki.list_lint_issues(status="open")
    assert len(open_issues) >= 1

    resolved = await alice_wiki.resolve_lint_issue(
        open_issues[0].issue_id, status="dismissed"
    )
    assert resolved.status == "dismissed"

    inc = await alice_wiki.compile(mode="incremental")
    assert inc.mode == "incremental"

    bf = await alice_wiki.compile(mode="backfill", max_files=2)
    assert bf.mode == "backfill"

    md_text = await alice_wiki.export_markdown("projects/apollo")
    assert "slug: projects/apollo" in md_text

    raw_zip = await alice_wiki.export_zip()
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
        assert zf.namelist() == ["projects/apollo.md"]


async def test_wiki_http_non_interactive_api_key_trust_boundaries(
    aiohttp_client: Any,
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
) -> None:
    """API keys write as agent, cannot set edit_policy, cannot overwrite user pages, and cannot delete or trigger compile."""
    raw_client, alice_wiki, _, _, h_key = await _make_wiki_env(
        aiohttp_client, server_config, session_manager
    )

    # API key cannot set edit_policy even on a brand-new page.
    lock_attempt = await raw_client.put(
        "/api/extended/wiki/pages/projects/agent-locked",
        headers=h_key,
        json={"title": "Locked", "body_md": "Body", "edit_policy": "locked"},
    )
    assert lock_attempt.status == 403

    # API key creates a normal page with author_kind="agent" and edit_policy="auto".
    created = await raw_client.put(
        "/api/extended/wiki/pages/projects/agent-note",
        headers=h_key,
        json={"title": "Agent Note", "body_md": "Compiled by agent"},
    )
    assert created.status == 200
    created_page = (await created.json())["page"]
    assert created_page["last_author_kind"] == "agent"
    assert created_page["edit_policy"] == "auto"

    # Interactive user edits the page -> escalates to protected_prose.
    user_page = await alice_wiki.upsert_page(
        "projects/agent-note", title="Agent Note", body_md="Human refined"
    )
    assert user_page.edit_policy == "protected_prose"

    # API key is now blocked from overwriting the human-protected page.
    blocked_put = await raw_client.put(
        "/api/extended/wiki/pages/projects/agent-note",
        headers=h_key,
        json={"title": "Agent Note", "body_md": "Overwrite"},
    )
    assert blocked_put.status == 403

    # API key is denied DELETE and POST /compile via @interactive_session_only.
    assert (
        await raw_client.delete(
            "/api/extended/wiki/pages/projects/agent-note", headers=h_key
        )
    ).status == 403
    assert (
        await raw_client.post(
            "/api/extended/wiki/compile", headers=h_key, json={"mode": "lint"}
        )
    ).status == 403


async def test_wiki_http_input_validation_and_upstream_errors(
    aiohttp_client: Any,
    server_config: ServerConfig,
    session_manager: DatabaseSessionManager,
) -> None:
    raw_client, alice_wiki, _, h1, _ = await _make_wiki_env(
        aiohttp_client, server_config, session_manager
    )

    # Null title must not coerce to "None".
    assert (
        await raw_client.put(
            "/api/extended/wiki/pages/projects/bad",
            headers=h1,
            json={"title": None, "body_md": "x"},
        )
    ).status == 400

    # Non-dict source_refs entry must be rejected instead of silently dropped.
    assert (
        await raw_client.put(
            "/api/extended/wiki/pages/projects/bad",
            headers=h1,
            json={"title": "Ok", "body_md": "x", "source_refs": ["note_page:1:p1"]},
        )
    ).status == 400

    # Float expected_version must be rejected instead of truncated.
    assert (
        await raw_client.put(
            "/api/extended/wiki/pages/projects/bad",
            headers=h1,
            json={"title": "Ok", "body_md": "x", "expected_version": 1.9},
        )
    ).status == 400

    # Invalid filter enums return 400.
    with pytest.raises(BadRequestException):
        await alice_wiki.list_pages(page_kind="bogus")
    with pytest.raises(BadRequestException):
        await alice_wiki.list_lint_issues(status="bogus")

    # Non-object JSON body and out-of-range max_files return 400 on /compile.
    assert (
        await raw_client.post("/api/extended/wiki/compile", headers=h1, json=["bad"])
    ).status == 400
    with pytest.raises(BadRequestException):
        await alice_wiki.compile(mode="backfill", max_files=0)
    with pytest.raises(BadRequestException):
        await alice_wiki.compile(mode="unknown")

    # Upstream AIError or LLM parse ValueError returns 502 instead of 500.
    compiler = raw_client.app[WIKI_COMPILER_KEY]
    with patch.object(compiler, "compile_user_delta", side_effect=AIError("503")):
        assert (
            await raw_client.post(
                "/api/extended/wiki/compile", headers=h1, json={"mode": "incremental"}
            )
        ).status == 502
    with patch.object(
        compiler, "compile_user_delta", side_effect=ValueError("bad json")
    ):
        assert (
            await raw_client.post(
                "/api/extended/wiki/compile", headers=h1, json={"mode": "incremental"}
            )
        ).status == 502
