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
    assert log_path.exists()

    # Since we use indent=2, a single entry spans multiple lines.
    # In this test we only made one request, so we can just parse the whole file.
    content = log_path.read_text().strip()
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
    from supernote.server.app import try_parse_json

    # Valid JSON
    assert try_parse_json('{"a": 1}') == {"a": 1}
    # Invalid JSON
    assert try_parse_json('{"a": 1') == '{"a": 1'
    # None
    assert try_parse_json(None) is None
    # A number json string
    assert try_parse_json("123") == 123


def test_binary_content_type_check() -> None:
    from supernote.server.app import is_binary_content_type

    assert is_binary_content_type("application/octet-stream")
    assert is_binary_content_type("image/png")
    assert is_binary_content_type("application/pdf")
    assert not is_binary_content_type("application/json")
    assert not is_binary_content_type("text/plain")
    assert not is_binary_content_type("text/html")
