"""HTTP integration tests for `/api/extended/wiki/*` routes via `WikiClient`."""

from __future__ import annotations

import io
import zipfile
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.auth import ConstantAuth
from supernote.client.client import Client
from supernote.client.exceptions import (
    ApiException,
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from supernote.client.wiki import WikiClient
from supernote.models.user import UserRegisterDTO
from supernote.models.wiki import WikiSourceRefDTO
from supernote.server.ai.base import AIError
from supernote.server.components.wiki.compiler import WIKI_COMPILER_KEY
from supernote.server.config import AiConfig, ModelConfig, ServerConfig
from supernote.server.keys import USER_SERVICE_KEY
from supernote.server.services.user import UserService


@pytest.fixture
def wiki_enabled() -> bool:
    """Whether the opt-in wiki component is enabled for the test."""
    return True


@pytest.fixture
def server_config(server_config: ServerConfig, wiki_enabled: bool) -> ServerConfig:
    """Configure the wiki component with the fake text generation provider."""
    server_config.ai = AiConfig(text=ModelConfig(provider="fake", model="fake-wiki"))
    server_config.wiki = {"enabled": wiki_enabled}
    return server_config


@pytest.fixture
def wiki_client(authenticated_client: Client) -> WikiClient:
    """Create an authenticated `WikiClient` against the test server."""
    return WikiClient(authenticated_client)


@pytest.fixture
async def other_wiki_client(client: TestClient) -> WikiClient:
    """Create a `WikiClient` authenticated as a second isolated user."""
    assert client.app is not None
    user_service: UserService = client.app[USER_SERVICE_KEY]
    await user_service.create_user(
        UserRegisterDTO(email="other@example.com", password="b" * 32)
    )
    token = await user_service.create_session("other@example.com")
    return WikiClient(
        Client(client.session, auth=ConstantAuth(token), host=str(client.make_url("")))
    )


@pytest.fixture
async def api_key_wiki_client(
    client: TestClient,
    test_user_id: int,
) -> WikiClient:
    """Create a `WikiClient` authenticated with a static Bearer API key."""
    assert client.app is not None
    user_service: UserService = client.app[USER_SERVICE_KEY]
    raw_key, _ = await user_service.create_api_key(test_user_id, "external-agent")
    return WikiClient(
        Client(
            client.session, auth=ConstantAuth(raw_key), host=str(client.make_url(""))
        )
    )


@pytest.mark.parametrize("wiki_enabled", [False])
async def test_wiki_http_disabled_returns_404(wiki_client: WikiClient) -> None:
    with pytest.raises(NotFoundException):
        await wiki_client.list_pages()


async def test_wiki_http_crud_conflict_search_and_isolation(
    client: TestClient,
    wiki_client: WikiClient,
    other_wiki_client: WikiClient,
) -> None:
    assert (await client.get("/api/extended/wiki/pages")).status == 401

    page = await wiki_client.upsert_page(
        "projects/apollo",
        title="Apollo",
        page_kind="project",
        summary="Moonshot",
        body_md="See [[entities/missing]].",
        aliases=["Project Apollo"],
        claims=[{"text": "Launch in Q3"}],
        source_refs=[
            WikiSourceRefDTO(source_type="note_page", source_key="1:p1", file_id=1)
        ],
        edit_policy="protected_prose",
    )
    assert page.slug == "projects/apollo"
    assert page.version == 1
    assert page.edit_policy == "protected_prose"

    fetched = await wiki_client.get_page("projects/apollo")
    assert fetched.title == "Apollo"
    assert len(fetched.source_refs) == 1

    listed = await wiki_client.list_pages(page_kind="project")
    assert [p.slug for p in listed] == ["projects/apollo"]

    with pytest.raises(ApiException):
        await wiki_client.upsert_page(
            "projects/apollo",
            title="Apollo",
            body_md="Stale",
            expected_version=99,
        )

    # Cross-user isolation: second user cannot read primary user's page.
    with pytest.raises(NotFoundException):
        await other_wiki_client.get_page("projects/apollo")

    hits = await wiki_client.search("apollo")
    assert hits[0].slug == "projects/apollo"

    revs = await wiki_client.list_revisions("projects/apollo")
    assert len(revs) == 1

    status = await wiki_client.get_status()
    assert status.page_count == 1

    assert await wiki_client.delete_page("projects/apollo") is True
    with pytest.raises(NotFoundException):
        await wiki_client.get_page("projects/apollo")


async def test_wiki_http_lint_compile_and_export(wiki_client: WikiClient) -> None:
    await wiki_client.upsert_page(
        "projects/apollo",
        title="Apollo",
        body_md="See [[entities/missing]].",
    )

    lint_run = await wiki_client.compile(mode="lint")
    assert lint_run.issues is not None
    assert any(i.issue_type == "broken_link" for i in lint_run.issues)

    open_issues = await wiki_client.list_lint_issues(status="open")
    assert len(open_issues) >= 1

    resolved = await wiki_client.resolve_lint_issue(
        open_issues[0].issue_id, status="dismissed"
    )
    assert resolved.status == "dismissed"

    inc = await wiki_client.compile(mode="incremental")
    assert inc.mode == "incremental"

    bf = await wiki_client.compile(mode="backfill", max_files=2)
    assert bf.mode == "backfill"

    md_text = await wiki_client.export_markdown("projects/apollo")
    assert "slug: projects/apollo" in md_text

    raw_zip = await wiki_client.export_zip()
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
        assert zf.namelist() == ["projects/apollo.md"]


async def test_wiki_http_non_interactive_api_key_trust_boundaries(
    wiki_client: WikiClient,
    api_key_wiki_client: WikiClient,
) -> None:
    """API keys write as agent, cannot set edit_policy, cannot overwrite user pages, and cannot delete or trigger compile."""
    with pytest.raises(ForbiddenException):
        await api_key_wiki_client.upsert_page(
            "projects/agent-locked",
            title="Locked",
            body_md="Body",
            edit_policy="locked",
        )

    created_page = await api_key_wiki_client.upsert_page(
        "projects/agent-note",
        title="Agent Note",
        body_md="Compiled by agent",
    )
    assert created_page.last_author_kind == "agent"
    assert created_page.edit_policy == "auto"

    user_page = await wiki_client.upsert_page(
        "projects/agent-note", title="Agent Note", body_md="Human refined"
    )
    assert user_page.edit_policy == "protected_prose"

    with pytest.raises(ForbiddenException):
        await api_key_wiki_client.upsert_page(
            "projects/agent-note", title="Agent Note", body_md="Overwrite"
        )
    with pytest.raises(ForbiddenException):
        await api_key_wiki_client.delete_page("projects/agent-note")
    with pytest.raises(ForbiddenException):
        await api_key_wiki_client.compile(mode="lint")


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "   ", "body_md": "x"},
        {"title": "Ok", "body_md": "x", "source_refs": ["note_page:1:p1"]},
        {"title": "Ok", "body_md": "x", "expected_version": -1},
    ],
)
async def test_wiki_http_invalid_put_payloads_return_400(
    client: TestClient,
    auth_headers: dict[str, str],
    payload: dict[str, Any],
) -> None:
    resp = await client.put(
        "/api/extended/wiki/pages/projects/bad",
        headers=auth_headers,
        json=payload,
    )
    assert resp.status == 400


async def test_wiki_http_invalid_filter_enums_return_400(
    wiki_client: WikiClient,
) -> None:
    with pytest.raises(BadRequestException):
        await wiki_client.list_pages(page_kind="bogus")
    with pytest.raises(BadRequestException):
        await wiki_client.list_lint_issues(status="bogus")


@pytest.mark.parametrize(
    ("mode", "max_files"),
    [
        ("backfill", 0),
        ("unknown", None),
    ],
)
async def test_wiki_http_invalid_compile_params_return_400(
    wiki_client: WikiClient,
    mode: str,
    max_files: int | None,
) -> None:
    with pytest.raises(BadRequestException):
        await wiki_client.compile(mode=mode, max_files=max_files)


async def test_wiki_http_not_found_endpoints(
    client: TestClient,
    wiki_client: WikiClient,
    auth_headers: dict[str, str],
) -> None:
    assert (
        await client.post(
            "/api/extended/wiki/lint/not-an-int/resolve", headers=auth_headers
        )
    ).status == 400
    with pytest.raises(NotFoundException):
        await wiki_client.resolve_lint_issue(999999)
    with pytest.raises(NotFoundException):
        await wiki_client.delete_page("projects/does-not-exist")
    with pytest.raises(NotFoundException):
        await wiki_client.list_revisions("projects/does-not-exist")
    with pytest.raises(NotFoundException):
        await wiki_client.export_markdown("projects/does-not-exist")


@pytest.mark.parametrize("exc", [AIError("503"), ValueError("bad json")])
async def test_wiki_http_upstream_compile_errors_return_502(
    client: TestClient,
    auth_headers: dict[str, str],
    exc: Exception,
) -> None:
    assert client.app is not None
    compiler = client.app[WIKI_COMPILER_KEY]
    with patch.object(compiler, "compile_user_delta", side_effect=exc):
        resp = await client.post(
            "/api/extended/wiki/compile",
            headers=auth_headers,
            json={"mode": "incremental"},
        )
        assert resp.status == 502
