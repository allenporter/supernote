import asyncio
import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient


@pytest.fixture
def mock_trace_log(tmp_path: Path) -> str:
    """Enable trace log for this module."""
    log_file = tmp_path / "trace.log"
    return str(log_file)


async def test_trace_logging(
    client: TestClient,
    mock_trace_log: str,
) -> None:
    """Verify that requests and responses are logged to the trace log."""

    # Make a simple request
    resp = await client.get("/api/file/query/server")
    assert resp.status == 200
    resp_text = await resp.text()

    # Check trace log
    log_path = Path(mock_trace_log)
    content = ""
    # Wait for the async file write thread to finish writing and flushing
    for _ in range(20):
        if log_path.exists():
            content = log_path.read_text().strip()
            if "/api/file/query/server" in content:
                break
        await asyncio.sleep(0.05)

    assert log_path.exists()
    entry = json.loads(content)

    # Check request fields
    assert "request" in entry
    assert entry["request"]["method"] == "GET"
    assert "/api/file/query/server" in entry["request"]["url"]

    # Check response fields
    assert "response" in entry
    assert entry["response"]["status"] == 200
    assert "headers" in entry["response"]

    # Check response body match
    logged_body = entry["response"]["body"]
    assert isinstance(logged_body, dict)  # Should be parsed as dict
    assert logged_body == json.loads(resp_text)


def _parse_trace_entries(content: str) -> list[dict]:
    decoder = json.JSONDecoder()
    entries: list[dict] = []
    idx = 0
    length = len(content)
    while idx < length:
        while idx < length and content[idx].isspace():
            idx += 1
        if idx >= length:
            break
        obj, idx = decoder.raw_decode(content, idx)
        entries.append(obj)
    return entries


async def test_trace_logging_redacts_json_credentials_and_tokens(
    client: TestClient,
    mock_trace_log: str,
    create_test_user: None,
) -> None:
    """Verify trace log redacts passwords, tokens, randomCode, headers, and URL signatures."""
    secret_password_hash = "0123456789abcdef0123456789abcdef"
    await client.post(
        "/api/official/user/account/login/new?signature=raw_sig_secret&token=raw_url_token",
        headers={
            "x-access-token": "raw_header_token",
            "channel": "raw_channel_jwt_TEST_EQ_1234567890",
        },
        json={
            "account": "test@example.com",
            "password": secret_password_hash,
            "equipmentNo": "TEST_EQ",
            "timestamp": "1234567890",
            "loginMethod": "1",
        },
    )

    log_path = Path(mock_trace_log)
    raw_log = ""
    for _ in range(20):
        if log_path.exists():
            raw_log = log_path.read_text()
            if "/api/official/user/account/login/new" in raw_log:
                break
        await asyncio.sleep(0.05)

    assert secret_password_hash not in raw_log
    assert "raw_sig_secret" not in raw_log
    assert "raw_url_token" not in raw_log
    assert "raw_header_token" not in raw_log
    assert "raw_channel_jwt_TEST_EQ_1234567890" not in raw_log

    entries = _parse_trace_entries(raw_log)
    login_entry = next(
        e
        for e in entries
        if "/api/official/user/account/login/new" in e["request"]["url"]
    )
    assert "signature=%2A%2A%2A" in login_entry["request"]["url"] or (
        "signature=***" in login_entry["request"]["url"]
    )
    assert login_entry["request"]["headers"].get("x-access-token") == "***"
    assert login_entry["request"]["headers"].get("channel") == "***"
    assert login_entry["request"]["body"]["account"] == "test@example.com"
    assert login_entry["request"]["body"]["password"] == "***"


async def test_trace_logging_redacts_form_encoded_secrets(
    client: TestClient,
    mock_trace_log: str,
) -> None:
    """Verify trace log redacts URL-encoded form fields like password and client_secret."""
    await client.post(
        "/api/file/query/server",
        data="email=test%40example.com&password=super_secret_pw&client_secret=top_secret_client",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    log_path = Path(mock_trace_log)
    raw_log = ""
    for _ in range(20):
        if log_path.exists():
            raw_log = log_path.read_text()
            if "test%40example.com" in raw_log:
                break
        await asyncio.sleep(0.05)

    assert "super_secret_pw" not in raw_log
    assert "top_secret_client" not in raw_log
    entries = _parse_trace_entries(raw_log)
    form_entry = next(
        e
        for e in entries
        if isinstance(e["request"]["body"], str)
        and "test%40example.com" in e["request"]["body"]
    )
    assert (
        form_entry["request"]["body"]
        == "email=test%40example.com&password=***&client_secret=***"
    )


async def test_trace_logging_unsafe_mode_preserves_raw_tokens(
    client: TestClient,
    mock_trace_log: str,
) -> None:
    """Verify trace_log_unsafe=True logs raw unredacted headers, URLs, and bodies for debugging."""
    client.app["config"].trace_log_unsafe = True
    await client.post(
        "/api/official/user/account/login/new?token=debug_query_token",
        headers={
            "x-access-token": "debug_header_token",
            "channel": "debug_channel_jwt_TEST_EQ_1234567890",
        },
        json={
            "account": "test@example.com",
            "password": "debug_raw_password_hash",
            "equipmentNo": "TEST_EQ",
            "timestamp": "1234567890",
            "loginMethod": "1",
        },
    )

    log_path = Path(mock_trace_log)
    raw_log = ""
    for _ in range(20):
        if log_path.exists():
            raw_log = log_path.read_text()
            if "debug_raw_password_hash" in raw_log:
                break
        await asyncio.sleep(0.05)

    entries = _parse_trace_entries(raw_log)
    unsafe_entry = next(
        e for e in entries if "debug_query_token" in e["request"]["url"]
    )
    assert (
        unsafe_entry["request"]["headers"].get("x-access-token") == "debug_header_token"
    )
    assert (
        unsafe_entry["request"]["headers"].get("channel")
        == "debug_channel_jwt_TEST_EQ_1234567890"
    )
    assert unsafe_entry["request"]["body"]["password"] == "debug_raw_password_hash"
