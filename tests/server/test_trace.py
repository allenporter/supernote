"""Unit tests for HTTP trace redaction helpers and SanitizedAccessLogger."""

import logging
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from supernote.server.config import ServerConfig
from supernote.server.keys import CONFIG_KEY
from supernote.server.trace import (
    ACCESS_LOG_FORMAT,
    SanitizedAccessLogger,
    is_binary_content_type,
    redact_url,
    sanitize_body,
    sanitize_headers,
    trace_middleware,
    try_parse_json,
)


def test_sanitize_headers_redacts_channel_and_jwt_values() -> None:
    """Verify sanitize_headers redacts channel, auth, cookies, URLs, and embedded JWTs."""
    sample_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyQGV4YW1wbGUuY29tIn0.sig_bytes"
    headers = {
        "X-Access-Token": "secret_jwt",
        "Authorization": "Bearer secret",
        "Cookie": "sid=123",
        "Set-Cookie": "sid=456; HttpOnly",
        "channel": f"{sample_jwt}_SN12345_1700000000",
        "X-Custom-Trace": f"prefix {sample_jwt} suffix",
        "Location": "https://client.example.com/cb?code=oauth_secret&state=123",
        "Referer": "https://app.example.com/?Token=ref_tok",
        "Content-Type": "application/json",
    }
    assert sanitize_headers(headers) == {
        "X-Access-Token": "***",
        "Authorization": "***",
        "Cookie": "***",
        "Set-Cookie": "***",
        "channel": "***",
        "X-Custom-Trace": "prefix *** suffix",
        "Location": "https://client.example.com/cb?code=***&state=123",
        "Referer": "https://app.example.com/?Token=***",
        "Content-Type": "application/json",
    }


def test_redact_url_query_params_and_malformed_fallback() -> None:
    """Verify redact_url redacts sensitive query keys on valid, encoded, and malformed URLs."""
    assert (
        redact_url("/socket.io/?EIO=3&transport=polling&token=secret_jwt&sign=sio_sig")
        == "/socket.io/?EIO=3&transport=polling&token=***&sign=***"
    )
    assert (
        redact_url(
            "https://example.com/socket.io/?EIO=4&Signature=Upper&%74oken=enc&sign=sio_sig"
        )
        == "https://example.com/socket.io/?EIO=4&Signature=***&token=***&sign=***"
    )
    assert (
        redact_url("http://[::1/socket.io/?token=malformed_jwt&sign=malformed_sig")
        == "http://[::1/socket.io/?token=***&sign=***"
    )
    assert redact_url("/api/health") == "/api/health"


def test_try_parse_json_and_binary_helpers() -> None:
    """Verify JSON parsing helper and binary content-type predicate."""
    assert try_parse_json('{"ok": true}') == {"ok": True}
    assert try_parse_json("123") == 123
    assert try_parse_json("{invalid") == "{invalid"
    assert try_parse_json(None) is None
    assert is_binary_content_type("application/octet-stream") is True
    assert is_binary_content_type("image/png") is True
    assert is_binary_content_type("application/pdf") is True
    assert is_binary_content_type("application/json") is False
    assert is_binary_content_type("text/plain") is False


def test_sanitize_body_redacts_nested_and_raw_strings() -> None:
    """Verify sanitize_body redacts sensitive fields across dicts, lists, and raw/truncated payloads."""
    sample_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyQGV4YW1wbGUuY29tIn0.sig_bytes"
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
                "socketUrl": "/socket.io/?token=url_tok",
            }
        ],
    }
    assert sanitize_body(payload) == {
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
                "socketUrl": "/socket.io/?token=***",
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
    assert (
        sanitize_body(f"Error connecting to ?token=err_secret with {sample_jwt}")
        == "Error connecting to ?token=*** with ***"
    )


async def test_sanitized_access_logger_redacts_and_supports_unsafe_mode(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify SanitizedAccessLogger redacts URL tokens and headers using ACCESS_LOG_FORMAT."""
    config = ServerConfig(trace_log_unsafe=False)
    app = web.Application()
    app[CONFIG_KEY] = config

    async def ok_handler(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    app.router.add_get("/socket.io/", ok_handler)

    access_logger = logging.getLogger("test.aiohttp.access")
    server = TestServer(app)
    embedded_jwt = (
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkZXZpY2VAZXhhbXBsZS5jb20ifQ.raw_sig_part"
    )

    with caplog.at_level(logging.INFO, logger="test.aiohttp.access"):
        await server.start_server(
            access_log_class=SanitizedAccessLogger,
            access_log=access_logger,
            access_log_format=ACCESS_LOG_FORMAT,
        )
        async with TestClient(server) as test_client:
            resp = await test_client.get(
                "/socket.io/?EIO=3&transport=polling&token=raw_sio_jwt&sign=raw_sio_sig",
                headers={
                    "Referer": "https://app.example.com/?token=raw_ref_jwt",
                    "User-Agent": f"SupernoteClient/1.0 {embedded_jwt}",
                },
            )
            assert resp.status == 200
            await resp.text()

            assert len(caplog.records) == 1
            redacted_record = caplog.records[0]
            redacted_msg = redacted_record.getMessage()
            assert "raw_sio_jwt" not in redacted_msg
            assert "raw_sio_sig" not in redacted_msg
            assert "raw_ref_jwt" not in redacted_msg
            assert embedded_jwt not in redacted_msg
            assert (
                "GET /socket.io/?EIO=3&transport=polling&token=***&sign=*** HTTP/1.1"
                in redacted_msg
            )
            assert '"https://app.example.com/?token=***"' in redacted_msg
            assert '"SupernoteClient/1.0 ***"' in redacted_msg
            assert redacted_record.__dict__["first_request_line"] == (
                "GET /socket.io/?EIO=3&transport=polling&token=***&sign=*** HTTP/1.1"
            )
            assert redacted_record.__dict__["request_header"] == {
                "Referer": "https://app.example.com/?token=***",
                "User-Agent": "SupernoteClient/1.0 ***",
            }

            caplog.clear()
            config.trace_log_unsafe = True
            resp_unsafe = await test_client.get(
                "/socket.io/?EIO=3&transport=polling&token=raw_sio_jwt&sign=raw_sio_sig",
                headers={
                    "Referer": "https://app.example.com/?token=raw_ref_jwt",
                    "User-Agent": f"SupernoteClient/1.0 {embedded_jwt}",
                },
            )
            assert resp_unsafe.status == 200
            await resp_unsafe.text()

            assert len(caplog.records) == 1
            unsafe_msg = caplog.records[0].getMessage()
            assert "token=raw_sio_jwt&sign=raw_sio_sig" in unsafe_msg
            assert "https://app.example.com/?token=raw_ref_jwt" in unsafe_msg
            assert embedded_jwt in unsafe_msg


async def test_trace_redacts_static_sn_api_keys_across_response_bodies_and_preserve_task_keys(
    tmp_path: Path,
) -> None:
    """Verify sn_<32_hex> secrets are scrubbed from POST /api/extended/keys responses without breaking SystemTaskVO.key."""
    raw_api_key = "sn_0123456789abcdef0123456789abcdef"

    # Parsed JSON response body from CreateApiKeyResponseVO
    create_key_body = {
        "success": True,
        "id": "a1b2c3d4e5f67890",
        "name": "Obsidian Sync",
        "key": raw_api_key,
        "createdAt": 1700000000,
    }
    assert sanitize_body(create_key_body) == {
        "success": True,
        "id": "a1b2c3d4e5f67890",
        "name": "Obsidian Sync",
        "key": "***",
        "createdAt": 1700000000,
    }

    # Non-secret SystemTaskVO "key" values remain untouched
    task_body = {"tasks": [{"id": 1, "fileId": 10, "key": "page_0"}]}
    assert sanitize_body(task_body) == task_body

    # Inline sn_... keys in custom headers, URLs, and error strings are scrubbed
    assert sanitize_headers({"X-Debug": f"leaked {raw_api_key} here"}) == {
        "X-Debug": "leaked *** here"
    }
    assert (
        redact_url(f"https://example.com/callback?custom={raw_api_key}")
        == "https://example.com/callback?custom=***"
    )
    assert sanitize_body(f"Auth error for {raw_api_key}") == "Auth error for ***"

    # End-to-end trace_middleware disk output never contains raw_api_key
    trace_file = tmp_path / "trace.jsonl"
    config = ServerConfig(trace_log_file=str(trace_file), trace_log_unsafe=False)
    app = web.Application(middlewares=[trace_middleware])
    app[CONFIG_KEY] = config

    async def mint_key_handler(_request: web.Request) -> web.Response:
        return web.json_response(create_key_body)

    app.router.add_post("/api/extended/keys", mint_key_handler)

    server = TestServer(app)
    await server.start_server()
    try:
        async with TestClient(server) as test_client:
            resp = await test_client.post(
                "/api/extended/keys", json={"name": "Obsidian Sync"}
            )
            assert resp.status == 200
            # Caller still receives the real key over HTTP
            assert (await resp.json())["key"] == raw_api_key
    finally:
        await server.close()

    disk_contents = trace_file.read_text(encoding="utf-8")
    assert raw_api_key not in disk_contents
    assert '"key": "***"' in disk_contents
