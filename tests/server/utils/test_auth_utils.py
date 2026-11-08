"""Tests for authentication header extraction utilities."""

from types import SimpleNamespace

from supernote.server.utils.auth_utils import get_token_from_request


def test_get_token_from_request_x_access_token() -> None:
    req = SimpleNamespace(headers={"x-access-token": "  session-tok  "})
    assert get_token_from_request(req) == "session-tok"


def test_get_token_from_request_whitespace_x_access_token_rejected() -> None:
    req = SimpleNamespace(
        headers={"x-access-token": "   ", "Authorization": "Bearer sn_12345"}
    )
    assert get_token_from_request(req) is None


def test_get_token_from_request_dual_headers_conflict_vs_match() -> None:
    matching = SimpleNamespace(
        headers={
            "x-access-token": "sn_12345",
            "Authorization": "Bearer sn_12345",
        }
    )
    assert get_token_from_request(matching) == "sn_12345"

    conflicting = SimpleNamespace(
        headers={
            "x-access-token": "session-jwt",
            "Authorization": "Bearer sn_other",
        }
    )
    assert get_token_from_request(conflicting) is None


def test_get_token_from_request_bearer_header() -> None:
    req = SimpleNamespace(headers={"Authorization": "Bearer sn_12345"})
    assert get_token_from_request(req) == "sn_12345"

    req_lower = SimpleNamespace(headers={"authorization": "bearer   sn_67890  "})
    assert get_token_from_request(req_lower) == "sn_67890"


def test_get_token_from_request_missing_or_unsupported_scheme() -> None:
    assert get_token_from_request(SimpleNamespace(headers={})) is None
    assert (
        get_token_from_request(SimpleNamespace(headers={"Authorization": "Basic abc"}))
        is None
    )
    assert (
        get_token_from_request(SimpleNamespace(headers={"Authorization": "Bearer   "}))
        is None
    )
