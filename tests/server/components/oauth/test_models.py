"""Unit tests for `supernote.server.components.oauth.models`."""

from __future__ import annotations

import pytest

from supernote.server.components.oauth.models import SupernoteAccessToken


@pytest.mark.parametrize(
    ("client_id", "explicit_actor", "expected_actor"),
    [
        ("https://client.example.com", "", "oauth:https://client.example.com"),
        ("   ", "", "oauth:unknown"),
        ("https://client.example.com", "api_key:42", "api_key:42"),
        ("https://client.example.com", "user:web", "user:web"),
        ("x" * 100, "", ("oauth:" + "x" * 100)[:64]),
    ],
)
def test_supernote_access_token_canonical_actor(
    client_id: str,
    explicit_actor: str,
    expected_actor: str,
) -> None:
    """Verify SupernoteAccessToken always resolves a canonical non-empty actor."""
    kwargs: dict[str, object] = {
        "token": "tok-1",
        "user_id": 7,
        "client_id": client_id,
        "scopes": ["supernote:all"],
    }
    if explicit_actor:
        kwargs["actor"] = explicit_actor
    token = SupernoteAccessToken.model_validate(kwargs)
    assert token.actor == expected_actor
