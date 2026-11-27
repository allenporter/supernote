"""Unit tests for `supernote.client.wiki` (`WikiClient`)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from supernote.client.exceptions import ApiException
from supernote.client.wiki import WikiClient, _encode_slug
from supernote.models.wiki import (
    WikiLintIssueResponseVO,
    WikiPageResponseVO,
    WikiStatusResponseVO,
)


def test_encode_slug_prevents_traversal_and_encodes_segments() -> None:
    assert _encode_slug("projects/q3-plan") == "projects/q3-plan"
    assert _encode_slug("/projects/q3-plan/") == "projects/q3-plan"
    assert _encode_slug("projects/foo?bar=1#frag") == "projects/foo%3Fbar%3D1%23frag"

    for bad in ("", "   ", "/", "../status", "projects/../secret", "a/./b", "a//b"):
        with pytest.raises(ValueError):
            _encode_slug(bad)


async def test_wiki_client_raises_api_exception_on_empty_payloads() -> None:
    mock_http = MagicMock()
    mock_http.get_json = AsyncMock(
        side_effect=[WikiPageResponseVO(page=None), WikiStatusResponseVO(status=None)]
    )
    mock_http.put_json = AsyncMock(return_value=WikiPageResponseVO(page=None))
    mock_http.post_json = AsyncMock(return_value=WikiLintIssueResponseVO(issue=None))

    client = WikiClient(mock_http)
    with pytest.raises(ApiException):
        await client.get_page("projects/a")
    with pytest.raises(ApiException):
        await client.get_status()
    with pytest.raises(ApiException):
        await client.upsert_page("projects/a", title="A")
    with pytest.raises(ApiException):
        await client.resolve_lint_issue(1)
