"""HTTP request/response trace logging middleware and credential redaction helpers."""

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import web
from yarl import URL

from .config import ServerConfig

logger = logging.getLogger(__name__)

TRUNCATE_BODY_LOG = 10 * 1024

REDACTED_VALUE = "***"
REDACTED_HEADER_KEYS = frozenset(
    {"x-access-token", "authorization", "cookie", "set-cookie", "channel"}
)
URL_HEADER_KEYS = frozenset({"location", "referer"})
REDACTED_URL_QUERY_KEYS = frozenset(
    {
        "signature",
        "sign",
        "token",
        "access_token",
        "refresh_token",
        "client_secret",
        "code",
    }
)
REDACTED_BODY_KEYS = frozenset(
    {
        "password",
        "oldpassword",
        "newpassword",
        "token",
        "accesstoken",
        "access_token",
        "refreshtoken",
        "refresh_token",
        "client_secret",
        "authorization",
        "randomcode",
        "random_code",
        "validcode",
        "valid_code",
        "sign",
        "code",
        "code_verifier",
    }
)
_REDACTED_KEYS_PATTERN = "|".join(re.escape(k) for k in sorted(REDACTED_BODY_KEYS))
_JSON_STRING_SECRET_RE = re.compile(
    rf'(?i)("({_REDACTED_KEYS_PATTERN})"\s*:\s*)"(?:\\.|[^"\\])*(?:"|$)'
)
_FORM_SECRET_RE = re.compile(rf"(?i)((?:^|&)(?:{_REDACTED_KEYS_PATTERN})=)[^&]*")


async def _write_trace_log(config: ServerConfig, log_entry: dict[str, Any]) -> None:
    """Write a trace log entry to the configured trace file."""
    if not config.trace_log_file:
        return

    trace_log_path = Path(config.trace_log_file)

    def write_op() -> None:
        try:
            trace_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(trace_log_path, "a") as f:
                f.write(json.dumps(log_entry, indent=2) + "\n")
                f.flush()
        except Exception as e:
            logger.error(f"Failed to write to trace log: {e}")

    await asyncio.to_thread(write_op)


def try_parse_json(body: str | None) -> Any:
    """Attempt to parse string as JSON, returning original if parsing fails."""
    if not isinstance(body, str):
        return body
    try:
        return json.loads(body)
    except Exception:
        return body


def is_binary_content_type(content_type: str) -> bool:
    """Check if content type is likely binary."""
    binary_types = [
        "application/octet-stream",
        "application/pdf",
        "application/zip",
        "image/",
        "audio/",
        "video/",
    ]
    return any(t in content_type for t in binary_types)


def redact_url(url: URL | str) -> str:
    """Redact sensitive query parameters from a URL."""
    url_str = str(url)
    try:
        u = url if isinstance(url, URL) else URL(url_str)
        if not u.query:
            return url_str
        query = u.query.copy()
        redacted = False
        for key in list(query.keys()):
            if key.lower() in REDACTED_URL_QUERY_KEYS:
                query[key] = REDACTED_VALUE
                redacted = True
        return str(u.with_query(query)) if redacted else url_str
    except Exception:
        return url_str


def redact_request_line(request_line: str) -> str:
    """Redact sensitive query parameters in an access-log request line or URL."""
    parts = request_line.split(" ")
    if len(parts) >= 2 and parts[0].isalpha():
        method, target, *rest = parts
        return " ".join((method, redact_url(target), *rest))
    return redact_url(request_line)


class _RequestWithRedactedQuery:
    """Request view whose path and query are safe to write to the access log."""

    def __init__(self, request: Any) -> None:
        self._request = request

    def __getattr__(self, name: str) -> Any:
        return getattr(self._request, name)

    @property
    def path_qs(self) -> str:
        return redact_url(self._request.path_qs)


class RedactingAccessLogger(web.AccessLogger):
    """Access logger that redacts sensitive query parameters in the request line.

    aiohttp binds ``%r`` to ``AccessLogger._format_r``, which reads ``path_qs``.
    Wrapping the request redacts that value for the stock formatter.
    """

    def log(self, request: Any, response: Any, time: float) -> None:
        if request is not None:
            request = _RequestWithRedactedQuery(request)
        super().log(request, response, time)


def sanitize_headers(headers: dict[str, Any]) -> dict[str, Any]:
    """Redact authentication, cookie, and URL-bearing headers case-insensitively."""
    sanitized: dict[str, Any] = {}
    for k, v in headers.items():
        key_lower = k.lower()
        if key_lower in REDACTED_HEADER_KEYS:
            sanitized[k] = REDACTED_VALUE
        elif key_lower in URL_HEADER_KEYS and isinstance(v, str):
            sanitized[k] = redact_url(v)
        else:
            sanitized[k] = v
    return sanitized


def sanitize_body(body: Any) -> Any:
    """Recursively redact sensitive credentials and tokens from parsed or raw bodies."""
    if isinstance(body, dict):
        return {
            k: (
                REDACTED_VALUE
                if isinstance(k, str)
                and k.lower() in REDACTED_BODY_KEYS
                and v is not None
                else sanitize_body(v)
            )
            for k, v in body.items()
        }
    if isinstance(body, list):
        return [sanitize_body(item) for item in body]
    if isinstance(body, str):
        if body.startswith(("http://", "https://", "/")):
            return redact_url(body)
        redacted = _JSON_STRING_SECRET_RE.sub(rf'\1"{REDACTED_VALUE}"', body)
        return _FORM_SECRET_RE.sub(rf"\1{REDACTED_VALUE}", redacted)
    return body


async def _capture_request_body(
    request: web.Request, fallback: str | None = None
) -> str | None:
    """Capture and truncate request body safely after handler execution."""
    if "/api/oss/upload" in request.path:
        return "<multipart upload skipped>"
    if request.body_exists and not request.content_type.startswith("multipart/"):
        try:
            body_bytes = await request.read()
            req_body_str = body_bytes.decode("utf-8", errors="replace")
            if len(req_body_str) > TRUNCATE_BODY_LOG:
                req_body_str = req_body_str[:TRUNCATE_BODY_LOG] + "... (truncated)"
            return req_body_str
        except Exception:
            return fallback or "<error reading body>"
    return fallback


@web.middleware
async def trace_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Middleware that writes HTTP request and response traces to disk."""
    config: ServerConfig = request.app["config"]
    unsafe = config.trace_log_unsafe

    try:
        response = await handler(request)
        req_body_str = await _capture_request_body(request)

        res_body_str = None
        if isinstance(response, web.Response) and response.body:
            if is_binary_content_type(response.content_type):
                res_body_str = "<binary data>"
            else:
                try:
                    if isinstance(response.body, bytes):
                        res_body_str = response.body.decode("utf-8", errors="replace")
                        if len(res_body_str) > TRUNCATE_BODY_LOG:
                            res_body_str = (
                                res_body_str[:TRUNCATE_BODY_LOG] + "... (truncated)"
                            )
                except Exception:
                    res_body_str = "<error reading response>"

        parsed_req_body = try_parse_json(req_body_str)
        parsed_res_body = try_parse_json(res_body_str)
        log_entry = {
            "timestamp": time.time(),
            "request": {
                "method": request.method,
                "url": str(request.url) if unsafe else redact_url(request.url),
                "headers": (
                    dict(request.headers)
                    if unsafe
                    else sanitize_headers(dict(request.headers))
                ),
                "body": parsed_req_body if unsafe else sanitize_body(parsed_req_body),
            },
            "response": {
                "status": response.status,
                "headers": (
                    dict(response.headers)
                    if unsafe
                    else sanitize_headers(dict(response.headers))
                ),
                "body": parsed_res_body if unsafe else sanitize_body(parsed_res_body),
            },
        }
        await _write_trace_log(config, log_entry)
        return response

    except Exception as e:
        logger.exception(f"Error handling request: {e}")
        req_body_str = await _capture_request_body(request, fallback="<unknown>")
        parsed_req_body = try_parse_json(req_body_str)

        log_entry = {
            "timestamp": time.time(),
            "request": {
                "method": request.method,
                "url": str(request.url) if unsafe else redact_url(request.url),
                "headers": (
                    dict(request.headers)
                    if unsafe
                    else sanitize_headers(dict(request.headers))
                ),
                "body": parsed_req_body if unsafe else sanitize_body(parsed_req_body),
            },
            "error": str(e),
            "status": 500,
        }
        await _write_trace_log(config, log_entry)
        raise
