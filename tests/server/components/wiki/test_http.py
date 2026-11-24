"""HTTP integration tests for `/api/extended/wiki/*` routes via `WikiClient`."""

from __future__ import annotations

import io
import zipfile
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.auth import AbstractAuth
from supernote.client.client import Client
from supernote.client.exceptions import (
    ApiException,
    BadRequestException,
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

    class _OtherAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            return token

    return WikiClient(
        Client(client.session, auth=_OtherAuth(), host=str(client.make_url("")))
    )


@pytest.fixture
async def api_key_headers(
    client: TestClient,
    test_user_id: int,
) -> dict[str, str]:
    """Create a static Bearer API key header for the primary test user."""
    assert client.app is not None
    user_service: UserService = client.app[USER_SERVICE_KEY]
    raw_key, _ = await user_service.create_api_key(test_user_id, "external-agent")
    return {"Authorization": f"Bearer {raw_key}"}


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
    client: TestClient,
    wiki_client: WikiClient,
    api_key_headers: dict[str, str],
) -> None:
    """API keys write as agent, cannot set edit_policy, cannot overwrite user pages, and cannot delete or trigger compile."""
    # API key cannot set edit_policy even on a brand-new page.
    lock_attempt = await client.put(
        "/api/extended/wiki/pages/projects/agent-locked",
        headers=api_key_headers,
        json={"title": "Locked", "body_md": "Body", "edit_policy": "locked"},
    )
    assert lock_attempt.status == 403

    # API key creates a normal page with author_kind="agent" and edit_policy="auto".
    created = await client.put(
        "/api/extended/wiki/pages/projects/agent-note",
        headers=api_key_headers,
        json={"title": "Agent Note", "body_md": "Compiled by agent"},
    )
    assert created.status == 200
    created_page = (await created.json())["page"]
    assert created_page["last_author_kind"] == "agent"
    assert created_page["edit_policy"] == "auto"

    # Interactive user edits the page -> escalates to protected_prose.
    user_page = await wiki_client.upsert_page(
        "projects/agent-note", title="Agent Note", body_md="Human refined"
    )
    assert user_page.edit_policy == "protected_prose"

    # API key is now blocked from overwriting the human-protected page.
    blocked_put = await client.put(
        "/api/extended/wiki/pages/projects/agent-note",
        headers=api_key_headers,
        json={"title": "Agent Note", "body_md": "Overwrite"},
    )
    assert blocked_put.status == 403

    # API key is denied DELETE and POST /compile via @interactive_session_only.
    assert (
        await client.delete(
            "/api/extended/wiki/pages/projects/agent-note", headers=api_key_headers
        )
    ).status == 403
    assert (
        await client.post(
            "/api/extended/wiki/compile",
            headers=api_key_headers,
            json={"mode": "lint"},
        )
    ).status == 403


async def test_wiki_http_input_validation_and_upstream_errors(
    client: TestClient,
    wiki_client: WikiClient,
    auth_headers: dict[str, str],
) -> None:
    assert client.app is not None

    # Null title must not coerce to "None".
    assert (
        await client.put(
            "/api/extended/wiki/pages/projects/bad",
            headers=auth_headers,
            json={"title": None, "body_md": "x"},
        )
    ).status == 400

    # Non-dict source_refs entry must be rejected instead of silently dropped.
    assert (
        await client.put(
            "/api/extended/wiki/pages/projects/bad",
            headers=auth_headers,
            json={"title": "Ok", "body_md": "x", "source_refs": ["note_page:1:p1"]},
        )
    ).status == 400

    # Float expected_version must be rejected instead of truncated.
    assert (
        await client.put(
            "/api/extended/wiki/pages/projects/bad",
            headers=auth_headers,
            json={"title": "Ok", "body_md": "x", "expected_version": 1.9},
        )
    ).status == 400

    # Invalid filter enums return 400.
    with pytest.raises(BadRequestException):
        await wiki_client.list_pages(page_kind="bogus")
    with pytest.raises(BadRequestException):
        await wiki_client.list_lint_issues(status="bogus")

    # Resolve-lint error paths (non-int issue_id 400, missing issue 404, invalid status 400).
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

    # Non-object JSON body and out-of-range max_files return 400 on /compile.
    assert (
        await client.post(
            "/api/extended/wiki/compile", headers=auth_headers, json=["bad"]
        )
    ).status == 400
    with pytest.raises(BadRequestException):
        await wiki_client.compile(mode="backfill", max_files=0)
    with pytest.raises(BadRequestException):
        await wiki_client.compile(mode="unknown")

    # Upstream AIError or LLM parse ValueError returns 502 instead of 500.
    compiler = client.app[WIKI_COMPILER_KEY]
    with patch.object(compiler, "compile_user_delta", side_effect=AIError("503")):
        assert (
            await client.post(
                "/api/extended/wiki/compile",
                headers=auth_headers,
                json={"mode": "incremental"},
            )
        ).status == 502
    with patch.object(
        compiler, "compile_user_delta", side_effect=ValueError("bad json")
    ):
        assert (
            await client.post(
                "/api/extended/wiki/compile",
                headers=auth_headers,
                json={"mode": "incremental"},
            )
        ).status == 502
