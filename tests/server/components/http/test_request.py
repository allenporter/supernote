"""Unit tests for `supernote.server.components.http.request`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from aiohttp import web
from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from supernote.models.base import ErrorCode
from supernote.server.components.http import (
    parse_dict_dto,
    parse_json_dto,
    parse_json_object,
    parse_query_dto,
)
from supernote.server.exceptions import InvalidInputError


@dataclass
class _NestedItem(DataClassJSONMixin):
    count: int


@dataclass
class _SampleDTO(DataClassJSONMixin):
    file_id: int = field(metadata=field_options(alias="fileId"))
    title: str = "default"
    nested: _NestedItem | None = None

    class Config(BaseConfig):
        serialize_by_alias = True

    def __post_init__(self) -> None:
        if self.file_id < 0:
            raise ValueError("fileId must be non-negative")
        if self.title == "bad-type":
            raise TypeError("unexpected title type")
        if self.title == "direct-error":
            raise InvalidInputError("direct domain error")


@dataclass
class _AllDefaultsDTO(DataClassJSONMixin):
    limit: int = 10


@dataclass
class _QueryDTO(DataClassJSONMixin):
    page: int
    label: str = "all"


def test_parse_dict_dto_valid() -> None:
    dto = parse_dict_dto(
        _SampleDTO,
        {"fileId": 42, "title": "notes", "nested": {"count": 3}},
    )
    assert dto == _SampleDTO(file_id=42, title="notes", nested=_NestedItem(count=3))


@pytest.mark.parametrize("bad_data", [[], None, "hello", 123, True])
def test_parse_dict_dto_rejects_non_mapping(bad_data: object) -> None:
    with pytest.raises(InvalidInputError, match="JSON object") as exc_info:
        parse_dict_dto(_SampleDTO, bad_data)
    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code == ErrorCode.BAD_REQUEST.value


def test_parse_dict_dto_normalizes_missing_and_invalid_fields() -> None:
    with pytest.raises(InvalidInputError, match="Invalid request:"):
        parse_dict_dto(_SampleDTO, {})

    with pytest.raises(InvalidInputError, match="Invalid request:"):
        parse_dict_dto(_SampleDTO, {"fileId": "not-an-int"})

    with pytest.raises(InvalidInputError, match="Invalid request:"):
        parse_dict_dto(_SampleDTO, {"fileId": 1, "nested": "not-a-dict"})


def test_parse_dict_dto_normalizes_post_init_errors() -> None:
    with pytest.raises(InvalidInputError, match="fileId must be non-negative"):
        parse_dict_dto(_SampleDTO, {"fileId": -1})

    with pytest.raises(InvalidInputError, match="unexpected title type"):
        parse_dict_dto(_SampleDTO, {"fileId": 1, "title": "bad-type"})

    with pytest.raises(InvalidInputError, match="^direct domain error$"):
        parse_dict_dto(_SampleDTO, {"fileId": 1, "title": "direct-error"})


async def test_parse_json_object_and_dto_over_http(aiohttp_client: Any) -> None:
    app = web.Application()

    async def handle_strict(request: web.Request) -> web.Response:
        try:
            dto = await parse_json_dto(request, _SampleDTO)
            return web.json_response(dto.to_dict())
        except InvalidInputError as err:
            return err.to_response()

    async def handle_optional(request: web.Request) -> web.Response:
        try:
            dto = await parse_json_dto(request, _AllDefaultsDTO, allow_empty=True)
            return web.json_response(dto.to_dict())
        except InvalidInputError as err:
            return err.to_response()

    async def handle_raw(request: web.Request) -> web.Response:
        try:
            obj = await parse_json_object(request, allow_empty=True)
            return web.json_response(obj)
        except InvalidInputError as err:
            return err.to_response()

    app.router.add_post("/strict", handle_strict)
    app.router.add_post("/optional", handle_optional)
    app.router.add_post("/raw", handle_raw)

    client = await aiohttp_client(app)

    # Valid payload
    resp = await client.post("/strict", json={"fileId": 7, "title": "ok"})
    assert resp.status == 200
    assert await resp.json() == {"fileId": 7, "title": "ok", "nested": None}

    # Empty & whitespace bodies rejected when allow_empty=False
    for body in (b"", b"   \n\t "):
        resp = await client.post("/strict", data=body)
        assert resp.status == 400
        payload = await resp.json()
        assert payload["success"] is False

    # Invalid JSON & invalid UTF-8
    for body in (b"{not-json", b"\xff\xfe"):
        resp = await client.post("/strict", data=body)
        assert resp.status == 400
        payload = await resp.json()
        assert payload["success"] is False

    # Non-object JSON values
    for body in (b"[]", b"null", b'"string"', b"123", b"true"):
        resp = await client.post("/strict", data=body)
        assert resp.status == 400
        payload = await resp.json()
        assert payload["success"] is False
        assert "JSON object" in payload["errorMsg"]

    # Missing / invalid fields
    resp = await client.post("/strict", json={"title": "missing-file-id"})
    assert resp.status == 400

    # allow_empty=True accepts empty / whitespace body
    resp = await client.post("/optional", data=b"")
    assert resp.status == 200
    assert await resp.json() == {"limit": 10}

    resp = await client.post("/raw", data=b"   ")
    assert resp.status == 200
    assert await resp.json() == {}


async def test_parse_query_dto_over_http(aiohttp_client: Any) -> None:
    app = web.Application()

    async def handle_query(request: web.Request) -> web.Response:
        try:
            dto = parse_query_dto(request, _QueryDTO)
            return web.json_response(dto.to_dict())
        except InvalidInputError as err:
            return err.to_response()

    app.router.add_get("/items", handle_query)
    client = await aiohttp_client(app)

    resp = await client.get("/items?page=2&label=work")
    assert resp.status == 200
    assert await resp.json() == {"page": 2, "label": "work"}

    resp = await client.get("/items?page=abc")
    assert resp.status == 400
    payload = await resp.json()
    assert payload["success"] is False

    resp = await client.get("/items")
    assert resp.status == 400
