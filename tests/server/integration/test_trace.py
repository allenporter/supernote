import asyncio
import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient

from supernote.server.config import parse_log_level
from supernote.server.trace import (
    is_binary_content_type,
    redact_request_line,
    redact_url,
    sanitize_body,
    sanitize_headers,
    try_parse_json,
)


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


def test_try_parse_json() -> None:
    # Valid JSON
    assert try_parse_json('{"a": 1}') == {"a": 1}
    # Invalid JSON
    assert try_parse_json('{"a": 1') == '{"a": 1'
    # None
    assert try_parse_json(None) is None
    # A number json string
    assert try_parse_json("123") == 123


def test_binary_content_type_check() -> None:
    assert is_binary_content_type("application/octet-stream")
    assert is_binary_content_type("image/png")
    assert is_binary_content_type("application/pdf")
    assert not is_binary_content_type("application/json")
    assert not is_binary_content_type("text/plain")
    assert not is_binary_content_type("text/html")


def test_sanitize_headers_and_redact_url() -> None:
    headers = {
        "X-Access-Token": "secret_jwt",
        "Authorization": "Bearer secret",
        "Cookie": "sid=123",
        "channel": "secret_jwt_EQ123_1699999999",
        "Channel": "Another.JWT_EQ999_1",
        "Location": "https://client.example.com/cb?code=oauth_secret&state=123",
        "Referer": "https://app.example.com/?Token=ref_tok",
        "Content-Type": "application/json",
    }
    assert sanitize_headers(headers) == {
        "X-Access-Token": "***",
        "Authorization": "***",
        "Cookie": "***",
        "channel": "***",
        "Channel": "***",
        "Location": "https://client.example.com/cb?code=***&state=123",
        "Referer": "https://app.example.com/?Token=***",
        "Content-Type": "application/json",
    }
    assert (
        redact_url(
            "https://example.com/api/oss/download?path=1&signature=abc&token=xyz"
        )
        == "https://example.com/api/oss/download?path=1&signature=***&token=***"
    )
    assert (
        redact_url(
            "https://example.com/socket.io/?EIO=4&Signature=Upper&%74oken=enc&sign=sio_sig"
        )
        == "https://example.com/socket.io/?EIO=4&Signature=***&token=***&sign=***"
    )
    assert (
        redact_url("https://example.com/api/health") == "https://example.com/api/health"
    )


def test_sanitize_body_nested_and_truncated() -> None:
    payload = {
        "account": "user@example.com",
        "password": "secret",
        "oldPassword": "old",
        "newPassword": "new",
        "validCode": "123456",
        "sign": "sms_sig",
        "token": None,
        "nested": [
            {
                "access_token": "tok1",
                "refresh_token": "ref1",
                "fullUploadUrl": "http://localhost/api/oss/upload?path=a&signature=sig1",
            }
        ],
    }
    sanitized = sanitize_body(payload)
    assert sanitized == {
        "account": "user@example.com",
        "password": "***",
        "oldPassword": "***",
        "newPassword": "***",
        "validCode": "***",
        "sign": "***",
        "token": None,
        "nested": [
            {
                "access_token": "***",
                "refresh_token": "***",
                "fullUploadUrl": "http://localhost/api/oss/upload?path=a&signature=***",
            }
        ],
    }

    truncated_json = '{"account": "user@example.com", "password": "raw\\"password", "token": "cut_off_secret'
    assert sanitize_body(truncated_json) == (
        '{"account": "user@example.com", "password": "***", "token": "***"'
    )
    assert (
        sanitize_body("account=user&password=secret with spaces&other=1")
        == "account=user&password=***&other=1"
    )


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
        headers={"x-access-token": "raw_header_token"},
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
        headers={"x-access-token": "debug_header_token"},
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
    assert unsafe_entry["request"]["body"]["password"] == "debug_raw_password_hash"


def test_redact_request_line_for_access_log() -> None:
    """Access-log request lines and bare path_qs must redact token/sign."""
    assert (
        redact_request_line(
            "GET /socket.io/?EIO=4&token=device_jwt&sign=sio_sig HTTP/1.1"
        )
        == "GET /socket.io/?EIO=4&token=***&sign=*** HTTP/1.1"
    )
    assert (
        redact_url("/socket.io/?EIO=4&token=device_jwt&sign=sio_sig")
        == "/socket.io/?EIO=4&token=***&sign=***"
    )


def test_parse_log_level_names() -> None:
    assert parse_log_level("debug") == "DEBUG"
    assert parse_log_level("WARNING") == "WARNING"
    assert parse_log_level("nope") == "INFO"
    assert parse_log_level(None) == "INFO"
    assert parse_log_level("bogus", default="ERROR") == "ERROR"
