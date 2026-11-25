"""Typed HTTP request body and query parameter parsing helpers.

Centralizes JSON decoding, top-level JSON object validation, and `mashumaro`
DTO deserialization so route handlers do not duplicate ad-hoc exception tuples
or accidentally turn malformed payloads into HTTP 500 responses.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from aiohttp import web
from mashumaro.mixins.dict import DataClassDictMixin

from supernote.server.exceptions import InvalidInputError

__all__ = [
    "parse_dict_dto",
    "parse_json_dto",
    "parse_json_object",
    "parse_query_dto",
]

_DTO_PARSE_ERRORS = (
    LookupError,
    ValueError,
    TypeError,
)


async def parse_json_object(
    request: web.Request,
    *,
    allow_empty: bool = False,
) -> dict[str, Any]:
    """Read and decode an HTTP request body as a JSON object (`dict`).

    Args:
        request: Incoming aiohttp request.
        allow_empty: When True, an empty or whitespace-only body resolves to `{}`.

    Raises:
        InvalidInputError: If the body is empty (when not allowed), invalid UTF-8,
            invalid JSON, or decodes to a non-object JSON value.
    """
    raw_bytes = await request.read()
    if not raw_bytes or not raw_bytes.strip():
        if allow_empty:
            return {}
        raise InvalidInputError("Invalid JSON body")
    try:
        parsed: Any = json.loads(raw_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise InvalidInputError(f"Invalid JSON body: {err}") from err
    if not isinstance(parsed, dict):
        raise InvalidInputError("Request body must be a JSON object")
    return parsed


def parse_dict_dto[T: DataClassDictMixin](
    dto_cls: type[T],
    data: object,
) -> T:
    """Deserialize a mapping into a `mashumaro` DTO, normalizing errors to `InvalidInputError`.

    Args:
        dto_cls: Target `DataClassDictMixin` (or `DataClassJSONMixin`) subclass.
        data: Raw mapping to deserialize.

    Raises:
        InvalidInputError: If `data` is not a mapping or fails `from_dict` / `__post_init__`
            validation.
    """
    if not isinstance(data, Mapping):
        raise InvalidInputError("Request body must be a JSON object")
    try:
        return dto_cls.from_dict(data)
    except _DTO_PARSE_ERRORS as err:
        raise InvalidInputError(f"Invalid request: {err}") from err


async def parse_json_dto[T: DataClassDictMixin](
    request: web.Request,
    dto_cls: type[T],
    *,
    allow_empty: bool = False,
) -> T:
    """Read a JSON object body from `request` and deserialize it into `dto_cls`.

    Args:
        request: Incoming aiohttp request.
        dto_cls: Target `DataClassDictMixin` (or `DataClassJSONMixin`) subclass.
        allow_empty: When True, an empty or whitespace-only body is treated as `{}`.

    Raises:
        InvalidInputError: On invalid JSON, non-object JSON, missing/invalid fields,
            or `__post_init__` validation failures.
    """
    parsed = await parse_json_object(request, allow_empty=allow_empty)
    return parse_dict_dto(dto_cls, parsed)


def parse_query_dto[T: DataClassDictMixin](
    request: web.Request,
    dto_cls: type[T],
) -> T:
    """Deserialize `request.query` parameters into `dto_cls`.

    Args:
        request: Incoming aiohttp request.
        dto_cls: Target `DataClassDictMixin` (or `DataClassJSONMixin`) subclass.

    Raises:
        InvalidInputError: If query parameters fail `from_dict` / `__post_init__` validation.
    """
    return parse_dict_dto(dto_cls, dict(request.query))
