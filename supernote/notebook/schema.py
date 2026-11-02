"""Typed wire-format schema, enums, and `<KEY:VALUE>` codecs for Supernote `.note` files.

Supernote metadata blocks (Header, Footer, Page, Layer, Keyword, Title, and Link)
are stored on disk as 4-byte little-endian length-prefixed UTF-8 strings formatted
as `<KEY1:VALUE1><KEY2:VALUE2>...`.

This module provides:

- Wire-tag enums (`FileType`, `EquipmentType`, `LayerName`, `LayerProtocol`,
  `LayerType`, `PageOrientation`, `RecognitionStatus`, `LinkType`, `LinkDirection`).
- Structured value types (`Rect`, `LayerVisibility`).
- Typed block dataclasses (`HeaderMetadata`, `FooterMetadata`, `PageMetadata`,
  `LayerMetadata`, `KeywordMetadata`, `TitleMetadata`, `LinkMetadata`, and
  top-level `SupernoteMetadata`) with lossless `from_params()` / `to_params()` /
  `to_wire_dict()` round-tripping and forward-compatible `extra` storage for
  unrecognized future firmware tags.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any, Self, TypeVar
from warnings import deprecated

from . import exceptions

RawParamValue = str | list[str]
RawParamsBlock = dict[str, RawParamValue]

KEY_TYPE = "__type__"
KEY_SIGNATURE = "__signature__"
KEY_HEADER = "__header__"
KEY_FOOTER = "__footer__"
KEY_PAGES = "__pages__"
KEY_LAYERS = "__layers__"
KEY_KEYWORDS = "__keywords__"
KEY_TITLES = "__titles__"
KEY_LINKS = "__links__"

_SYNTHETIC_KEYS = frozenset(
    {
        KEY_TYPE,
        KEY_SIGNATURE,
        KEY_HEADER,
        KEY_FOOTER,
        KEY_PAGES,
        KEY_LAYERS,
        KEY_KEYWORDS,
        KEY_TITLES,
        KEY_LINKS,
    }
)

_PARAM_PATTERN = re.compile(r"<([^:<>]+):(.*?)>")

_StrEnumT = TypeVar("_StrEnumT", bound=StrEnum)
_IntEnumT = TypeVar("_IntEnumT", bound=IntEnum)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FileType(StrEnum):
    """Top-level file type recorded in `<FILE_TYPE:...>`."""

    NOTE = "NOTE"
    """Standard handwritten notebook (`.note`)."""

    MARK = "MARK"
    """Document annotation sidecar (`.mark`)."""


class EquipmentType(StrEnum):
    """Supernote hardware model identifier recorded in `<APPLY_EQUIPMENT:...>`."""

    A5 = "A5"
    """Original Linux-based Supernote A5 (`1404x1872`)."""

    A6 = "A6"
    """Original Linux-based Supernote A6 (`1404x1872`)."""

    A5X = "A5X"
    """Supernote A5 X (`1404x1872`)."""

    A6X = "A6X"
    """Supernote A6 X (`1404x1872`)."""

    N5 = "N5"
    """Supernote A5 X2 Manta (`1920x2560`)."""

    N6 = "N6"
    """Supernote A6 X2 Nomad (`1404x1872`)."""


class LayerName(StrEnum):
    """Standard X-series page layer slot names."""

    MAINLAYER = "MAINLAYER"
    """Primary handwriting layer (`layerId == 0`, non-background)."""

    LAYER1 = "LAYER1"
    """Additional handwriting layer 1."""

    LAYER2 = "LAYER2"
    """Additional handwriting layer 2."""

    LAYER3 = "LAYER3"
    """Additional handwriting layer 3."""

    BGLAYER = "BGLAYER"
    """Background/template layer."""


X_SERIES_LAYER_KEYS: tuple[LayerName, ...] = (
    LayerName.MAINLAYER,
    LayerName.LAYER1,
    LayerName.LAYER2,
    LayerName.LAYER3,
    LayerName.BGLAYER,
)


class LayerProtocol(StrEnum):
    """Bitmap compression protocol recorded in `<LAYERPROTOCOL:...>` or `<PROTOCOL:...>`."""

    RATTA_RLE = "RATTA_RLE"
    """Ratta run-length encoded bitmap stream (X and X2 series)."""

    SN_ASA_COMPRESS = "SN_ASA_COMPRESS"
    """Legacy zlib/flate-compressed `uint16` bitmap stream (A5 series)."""


class LayerType(StrEnum):
    """Layer content category recorded in `<LAYERTYPE:...>`."""

    NOTE = "NOTE"
    """Standard notebook layer."""

    MARK = "MARK"
    """Document annotation layer."""

    BACKGROUND = "BACKGROUND"
    """Background/template layer."""


class PageOrientation(StrEnum):
    """Page orientation angle code recorded in `<ORIENTATION:...>`."""

    VERTICAL = "1000"
    """Portrait (`0°`)."""

    HORIZONTAL = "1090"
    """Landscape (`90°`)."""

    VERTICAL_180 = "1180"
    """Portrait inverted (`180°`)."""

    HORIZONTAL_270 = "1270"
    """Landscape inverted (`270°`)."""


class RecognitionStatus(IntEnum):
    """Page handwriting recognition state recorded in `<RECOGNSTATUS:...>`."""

    NONE = 0
    """No recognition has been performed."""

    DONE = 1
    """Recognition completed (`RECOGNTEXT` / `RECOGNFILE` available)."""

    RUNNING = 2
    """Recognition in progress or pending update."""


class LinkType(IntEnum):
    """Link target kind recorded in `<LINKTYPE:...>`."""

    PAGE = 0
    """Jump to a notebook page (same notebook or another `.note` file)."""

    FILE = 1
    """Jump to another file."""

    DOCUMENT = 2
    """Jump to a non-note document (e.g. a `.pdf` file or page)."""

    WEB = 4
    """External web URL (`LINKFILE` holds base64-encoded URL)."""


class LinkDirection(IntEnum):
    """Link direction recorded in `<LINKINOUT:...>`."""

    OUT = 0
    """Outgoing link originating on this page."""

    IN = 1
    """Incoming backlink targeting this page."""


# ---------------------------------------------------------------------------
# Value Types & Wire Codecs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rect:
    """Axis-aligned rectangle encoded on the wire as `<left>,<top>,<width>,<height>`."""

    left: int
    """Left X coordinate in pixels."""

    top: int
    """Top Y coordinate in pixels."""

    width: int
    """Rectangle width in pixels."""

    height: int
    """Rectangle height in pixels."""

    @property
    def right(self) -> int:
        """Right edge coordinate (`left + width`)."""
        return self.left + self.width

    @property
    def bottom(self) -> int:
        """Bottom edge coordinate (`top + height`)."""
        return self.top + self.height

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        """Bounding box tuple `(left, top, right, bottom)`."""
        return (self.left, self.top, self.right, self.bottom)

    @classmethod
    def from_wire(cls, value: str, field_name: str = "RECT") -> Self:
        """Parse `<left>,<top>,<width>,<height>` string into a `Rect`."""
        if not isinstance(value, str):
            raise exceptions.ParserException(
                f"invalid rectangle parameter {field_name!r}: {value!r}"
            )
        parts = value.split(",")
        if len(parts) != 4:
            raise exceptions.ParserException(
                f"invalid rectangle parameter {field_name!r}: {value!r}"
            )
        try:
            left, top, width, height = (int(p) for p in parts)
        except ValueError as exc:
            raise exceptions.ParserException(
                f"invalid rectangle parameter {field_name!r}: {value!r}"
            ) from exc
        return cls(left=left, top=top, width=width, height=height)

    def to_wire(self) -> str:
        """Serialize back to `<left>,<top>,<width>,<height>` wire string."""
        return f"{self.left},{self.top},{self.width},{self.height}"


@dataclass(frozen=True, slots=True)
class LayerVisibility:
    """Decoded layer descriptor from a page `<LAYERINFO:...>` array."""

    layer_id: int
    """Layer identifier (`-1` or `0` with `is_background_layer=True` for `BGLAYER`, `0` for `MAINLAYER`, `1..3` for `LAYER1..3`)."""

    is_background_layer: bool
    """Whether this entry describes `BGLAYER`."""

    is_visible: bool
    """Whether this layer is currently visible."""

    name: str | None = None
    """User-facing layer display name."""

    is_allow_add: bool = False
    """Whether a layer can be added relative to this slot."""

    is_current_layer: bool = False
    """Whether this layer was selected as active on the device."""

    is_deleted: bool = False
    """Whether this layer slot is marked deleted/unused."""

    is_allow_up: bool = False
    """Whether this layer can move up in the compositing order."""

    is_allow_down: bool = False
    """Whether this layer can move down in the compositing order."""

    @property
    def layer_key(self) -> str:
        """Wire layer slot name (`BGLAYER`, `MAINLAYER`, or `LAYER<id>`)."""
        if self.is_background_layer:
            return LayerName.BGLAYER.value
        if self.layer_id == 0:
            return LayerName.MAINLAYER.value
        return f"LAYER{self.layer_id}"


def extract_parameters(metadata_text: str) -> RawParamsBlock:
    """Extract `<KEY:VALUE>` tags from a decoded metadata block string.

    Duplicate keys are aggregated into a `list[str]` in order of appearance.
    """
    params: RawParamsBlock = {}
    for match in _PARAM_PATTERN.finditer(metadata_text):
        key = match[1]
        value = match[2]
        if key in params:
            # The key is duplicated: transform {key: value} into {key: [value1, value2, ...]}
            # on first collision and append subsequent values to the list.
            existing = params[key]
            if isinstance(existing, list):
                existing.append(value)
            else:
                params[key] = [existing, value]
        else:
            params[key] = value
    return params


def encode_parameters(params: Mapping[str, object]) -> bytes:
    """Encode a mapping of `<KEY:VALUE>` parameters into UTF-8 wire bytes."""
    chunks: list[str] = []
    for key, value in params.items():
        if isinstance(value, list):
            for item in value:
                chunks.append(f"<{key}:{item}>")
        else:
            chunks.append(f"<{key}:{value}>")
    return "".join(chunks).encode("utf-8")


def parse_layer_info(raw: str | None) -> list[LayerVisibility] | None:
    """Decode `<LAYERINFO:...>` from JSON, `#`-escaped JSON, or Chauvet 3.25.39+ base64 JSON."""
    if raw is None or raw == "none":
        return None
    try:
        info_array = json.loads(raw)
    except json.JSONDecodeError:
        normalized = raw.replace("#", ":")
        try:
            info_array = json.loads(normalized)
        except json.JSONDecodeError:
            # Newer Supernote firmwares (Chauvet 3.25.39 and later) encode the layer info JSON
            # payload in base64. If parsing raw JSON fails, decode the base64 string and retry.
            # A payload that is neither valid JSON nor valid base64-encoded JSON is a corrupt
            # layer info blob, so report it as a typed parser error instead of leaking the
            # raw decode failure (binascii.Error, UnicodeDecodeError, JSONDecodeError).
            try:
                decoded_json = base64.b64decode(raw).decode("utf-8")
                info_array = json.loads(decoded_json)
            except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
                raise exceptions.ParserException(
                    f"invalid layer info payload: {exc}"
                ) from exc

    if not isinstance(info_array, list):
        raise exceptions.ParserException(
            "invalid layer info payload: expected JSON list"
        )

    entries: list[LayerVisibility] = []
    for item in info_array:
        if not isinstance(item, dict):
            raise exceptions.ParserException(
                "invalid layer info payload: expected JSON object entry"
            )
        raw_layer_id = item.get("layerId", 0)
        if not isinstance(raw_layer_id, int) or isinstance(raw_layer_id, bool):
            raise exceptions.ParserException(
                f"invalid layer info layerId: {raw_layer_id!r}"
            )
        name_val = item.get("name")
        entries.append(
            LayerVisibility(
                layer_id=raw_layer_id,
                is_background_layer=bool(item.get("isBackgroundLayer", False)),
                is_visible=bool(item.get("isVisible", False)),
                name=name_val if isinstance(name_val, str) else None,
                is_allow_add=bool(item.get("isAllowAdd", False)),
                is_current_layer=bool(item.get("isCurrentLayer", False)),
                is_deleted=bool(item.get("isDeleted", False)),
                is_allow_up=bool(item.get("isAllowUp", False)),
                is_allow_down=bool(item.get("isAllowDown", False)),
            )
        )
    return entries


def encode_layer_info(
    entries: Sequence[LayerVisibility], *, wire_escape: bool = True
) -> str:
    """Serialize `LayerVisibility` entries to JSON (optionally `#`-escaped for `<LAYERINFO:...>`)."""
    payload = [
        {
            "layerId": entry.layer_id,
            **({"name": entry.name} if entry.name is not None else {}),
            "isBackgroundLayer": entry.is_background_layer,
            "isAllowAdd": entry.is_allow_add,
            "isCurrentLayer": entry.is_current_layer,
            "isVisible": entry.is_visible,
            "isDeleted": entry.is_deleted,
            "isAllowUp": entry.is_allow_up,
            "isAllowDown": entry.is_allow_down,
        }
        for entry in entries
    ]
    serialized = json.dumps(payload, separators=(",", ":"))
    return serialized.replace(":", "#") if wire_escape else serialized


# ---------------------------------------------------------------------------
# Internal Parsing & Ordering Helpers
# ---------------------------------------------------------------------------


def _as_single_str(value: object, field_name: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    raise exceptions.ParserException(
        f"missing or invalid string parameter {field_name!r}: {value!r}"
    )


def _parse_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise exceptions.ParserException(
            f"missing or invalid integer parameter {field_name!r}"
        )
    try:
        return int(value)
    except ValueError as exc:
        raise exceptions.ParserException(
            f"invalid integer parameter {field_name!r}: {value!r}"
        ) from exc


def _parse_optional_int(params: Mapping[str, Any], key: str) -> int | None:
    if key not in params or params[key] is None:
        return None
    return _parse_int(params[key], key)


def _parse_int_default(params: Mapping[str, Any], key: str, default: int = 0) -> int:
    if key not in params or params[key] is None:
        return default
    return _parse_int(params[key], key)


def _parse_optional_str(
    params: Mapping[str, Any], key: str, *, sentinel: str | None = None
) -> str | None:
    if key not in params or params[key] is None:
        return None
    val = _as_single_str(params[key], key)
    if sentinel is not None and val == sentinel:
        return None
    return val


def _parse_str_enum(value: str, enum_cls: type[_StrEnumT]) -> _StrEnumT | str:
    try:
        return enum_cls(value)
    except ValueError:
        return value


def _parse_optional_str_enum(
    params: Mapping[str, Any],
    key: str,
    enum_cls: type[_StrEnumT],
    *,
    sentinel: str | None = None,
) -> _StrEnumT | str | None:
    raw = _parse_optional_str(params, key, sentinel=sentinel)
    if raw is None:
        return None
    return _parse_str_enum(raw, enum_cls)


def _parse_int_enum(
    value: object, enum_cls: type[_IntEnumT], field_name: str
) -> _IntEnumT | int:
    parsed = _parse_int(value, field_name)
    try:
        return enum_cls(parsed)
    except ValueError:
        return parsed


def _parse_address_list(value: object, key: str) -> list[int]:
    if isinstance(value, list):
        return [_parse_int(item, key) for item in value]
    return [_parse_int(value, key)]


def _coerce_extra(raw_extra: Mapping[str, Any], consumed: set[str]) -> RawParamsBlock:
    extra: RawParamsBlock = {}
    for key, value in raw_extra.items():
        if key in consumed or key in _SYNTHETIC_KEYS:
            continue
        if isinstance(value, list):
            extra[key] = [str(item) for item in value]
        else:
            extra[key] = str(value)
    return extra


def _order_params(
    encoded: RawParamsBlock, wire_keys: tuple[str, ...]
) -> RawParamsBlock:
    ordered: RawParamsBlock = {}
    for key in wire_keys:
        if key in encoded:
            ordered[key] = encoded[key]
    for key, value in encoded.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def _put_optional_str(
    encoded: RawParamsBlock,
    key: str,
    value: str | None,
    wire_keys: frozenset[str],
    *,
    sentinel: str | None = None,
) -> None:
    if value is not None:
        encoded[key] = str(value)
    elif sentinel is not None and key in wire_keys:
        encoded[key] = sentinel


def _put_optional_int(encoded: RawParamsBlock, key: str, value: int | None) -> None:
    if value is not None:
        encoded[key] = str(int(value))


def _put_int_default(
    encoded: RawParamsBlock,
    key: str,
    value: int,
    wire_keys: frozenset[str],
    *,
    default: int = 0,
) -> None:
    if value != default or key in wire_keys:
        encoded[key] = str(int(value))


# ---------------------------------------------------------------------------
# Block Metadata Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class HeaderMetadata:
    """File-level `<FILE_FEATURE>` header block metadata."""

    file_type: FileType | str | None = None
    """`<FILE_TYPE>` — Notebook container kind (`NOTE` or `MARK`)."""

    apply_equipment: EquipmentType | str | None = None
    """`<APPLY_EQUIPMENT>` — Device model (`A5X`, `A6X`, `N5`, `N6`)."""

    is_old_apply_equipment: int | None = None
    """`<IS_OLD_APPLY_EQUIPMENT>` — Legacy equipment migration flag (`0` or `1`)."""

    file_id: str | None = None
    """`<FILE_ID>` — Stable device-generated notebook identifier persisting across renames."""

    file_parse_type: int | None = None
    """`<FILE_PARSE_TYPE>` — Firmware parser version flag."""

    file_recogn_type: int | None = None
    """`<FILE_RECOGN_TYPE>` — Recognition mode (`0` standard, `1` real-time recognition)."""

    file_recogn_language: str | None = None
    """`<FILE_RECOGN_LANGUAGE>` — Recognition locale (e.g. `en_US`, `tr_TR`), `None` if `"none"`."""

    device_dpi: int | None = None
    """`<DEVICE_DPI>` — Hardware display DPI metadata."""

    soft_dpi: int | None = None
    """`<SOFT_DPI>` — Software rendering DPI metadata."""

    ratta_etmd: int | None = None
    """`<RATTA_ETMD>` — Electromagnetic touch/digitizer model parameter."""

    app_version: str | None = None
    """`<APP_VERSION>` — Note app version string."""

    module_label: str | None = None
    """`<MODULE_LABEL>` — Module feature label (e.g. `SNFILE_FEATURE`), `None` if `"none"`."""

    original_style: str | None = None
    """`<ORIGINAL_STYLE>` — Default template style name, `None` if `"none"`."""

    original_style_md5: str | None = None
    """`<ORIGINAL_STYLEMD5>` — MD5 digest for custom default template, `None` if `"0"`."""

    pdf_style: str | None = None
    """`<PDFSTYLE>` — Associated PDF template style, `None` if `"none"`."""

    pdf_style_md5: str | None = None
    """`<PDFSTYLEMD5>` — MD5 digest for PDF template style, `None` if `"0"`."""

    style_usage_type: int | None = None
    """`<STYLEUSAGETYPE>` — Template usage mode flag (`0` built-in, `1` image, `2` PDF)."""

    final_operation_page: int | None = None
    """`<FINALOPERATION_PAGE>` — Last active 1-based page number on device."""

    final_operation_layer: int | None = None
    """`<FINALOPERATION_LAYER>` — Last active layer index on device."""

    highlight_info: str | None = None
    """`<HIGHLIGHTINFO>` — Highlight state flag/payload."""

    horizontal_check: int | None = None
    """`<HORIZONTAL_CHECK>` — Orientation check flag."""

    antialiasing_convert: int | None = None
    """`<ANTIALIASING_CONVERT>` — Stroke antialiasing conversion level."""

    extra: RawParamsBlock = field(default_factory=dict)
    """Forward-compatible map of any unrecognized `<KEY:VALUE>` header tags."""

    _wire_keys: tuple[str, ...] = field(default=(), repr=False, compare=False)

    _KNOWN_KEYS = frozenset(
        {
            "FILE_TYPE",
            "APPLY_EQUIPMENT",
            "IS_OLD_APPLY_EQUIPMENT",
            "FILE_ID",
            "FILE_PARSE_TYPE",
            "FILE_RECOGN_TYPE",
            "FILE_RECOGN_LANGUAGE",
            "DEVICE_DPI",
            "SOFT_DPI",
            "RATTA_ETMD",
            "APP_VERSION",
            "MODULE_LABEL",
            "ORIGINAL_STYLE",
            "ORIGINAL_STYLEMD5",
            "PDFSTYLE",
            "PDFSTYLEMD5",
            "STYLEUSAGETYPE",
            "FINALOPERATION_PAGE",
            "FINALOPERATION_LAYER",
            "HIGHLIGHTINFO",
            "HORIZONTAL_CHECK",
            "ANTIALIASING_CONVERT",
        }
    )

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> Self:
        """Parse a raw `<KEY:VALUE>` header dictionary into `HeaderMetadata`."""
        wire_keys = tuple(k for k in params if k not in _SYNTHETIC_KEYS)
        return cls(
            file_type=_parse_optional_str_enum(params, "FILE_TYPE", FileType),
            apply_equipment=_parse_optional_str_enum(
                params, "APPLY_EQUIPMENT", EquipmentType
            ),
            is_old_apply_equipment=_parse_optional_int(
                params, "IS_OLD_APPLY_EQUIPMENT"
            ),
            file_id=_parse_optional_str(params, "FILE_ID", sentinel="none"),
            file_parse_type=_parse_optional_int(params, "FILE_PARSE_TYPE"),
            file_recogn_type=_parse_optional_int(params, "FILE_RECOGN_TYPE"),
            file_recogn_language=_parse_optional_str(
                params, "FILE_RECOGN_LANGUAGE", sentinel="none"
            ),
            device_dpi=_parse_optional_int(params, "DEVICE_DPI"),
            soft_dpi=_parse_optional_int(params, "SOFT_DPI"),
            ratta_etmd=_parse_optional_int(params, "RATTA_ETMD"),
            app_version=_parse_optional_str(params, "APP_VERSION"),
            module_label=_parse_optional_str(params, "MODULE_LABEL", sentinel="none"),
            original_style=_parse_optional_str(
                params, "ORIGINAL_STYLE", sentinel="none"
            ),
            original_style_md5=_parse_optional_str(
                params, "ORIGINAL_STYLEMD5", sentinel="0"
            ),
            pdf_style=_parse_optional_str(params, "PDFSTYLE", sentinel="none"),
            pdf_style_md5=_parse_optional_str(params, "PDFSTYLEMD5", sentinel="0"),
            style_usage_type=_parse_optional_int(params, "STYLEUSAGETYPE"),
            final_operation_page=_parse_optional_int(params, "FINALOPERATION_PAGE"),
            final_operation_layer=_parse_optional_int(params, "FINALOPERATION_LAYER"),
            highlight_info=_parse_optional_str(params, "HIGHLIGHTINFO"),
            horizontal_check=_parse_optional_int(params, "HORIZONTAL_CHECK"),
            antialiasing_convert=_parse_optional_int(params, "ANTIALIASING_CONVERT"),
            extra=_coerce_extra(params, set(cls._KNOWN_KEYS)),
            _wire_keys=wire_keys,
        )

    def to_params(self) -> RawParamsBlock:
        """Serialize to `<KEY:VALUE>` parameters preserving wire key order."""
        present = frozenset(self._wire_keys)
        encoded: RawParamsBlock = {}
        _put_optional_str(encoded, "FILE_TYPE", self.file_type, present)
        _put_optional_str(encoded, "APPLY_EQUIPMENT", self.apply_equipment, present)
        _put_optional_int(
            encoded, "IS_OLD_APPLY_EQUIPMENT", self.is_old_apply_equipment
        )
        _put_optional_str(encoded, "FILE_ID", self.file_id, present, sentinel="none")
        _put_optional_int(encoded, "FILE_PARSE_TYPE", self.file_parse_type)
        _put_optional_int(encoded, "FILE_RECOGN_TYPE", self.file_recogn_type)
        _put_optional_str(
            encoded,
            "FILE_RECOGN_LANGUAGE",
            self.file_recogn_language,
            present,
            sentinel="none",
        )
        _put_optional_int(encoded, "DEVICE_DPI", self.device_dpi)
        _put_optional_int(encoded, "SOFT_DPI", self.soft_dpi)
        _put_optional_int(encoded, "RATTA_ETMD", self.ratta_etmd)
        _put_optional_str(encoded, "APP_VERSION", self.app_version, present)
        _put_optional_str(
            encoded, "MODULE_LABEL", self.module_label, present, sentinel="none"
        )
        _put_optional_str(
            encoded, "ORIGINAL_STYLE", self.original_style, present, sentinel="none"
        )
        _put_optional_str(
            encoded,
            "ORIGINAL_STYLEMD5",
            self.original_style_md5,
            present,
            sentinel="0",
        )
        _put_optional_str(encoded, "PDFSTYLE", self.pdf_style, present, sentinel="none")
        _put_optional_str(
            encoded, "PDFSTYLEMD5", self.pdf_style_md5, present, sentinel="0"
        )
        _put_optional_int(encoded, "STYLEUSAGETYPE", self.style_usage_type)
        _put_optional_int(encoded, "FINALOPERATION_PAGE", self.final_operation_page)
        _put_optional_int(encoded, "FINALOPERATION_LAYER", self.final_operation_layer)
        _put_optional_str(encoded, "HIGHLIGHTINFO", self.highlight_info, present)
        _put_optional_int(encoded, "HORIZONTAL_CHECK", self.horizontal_check)
        _put_optional_int(encoded, "ANTIALIASING_CONVERT", self.antialiasing_convert)
        encoded.update(self.extra)
        return _order_params(encoded, self._wire_keys)

    def to_wire_dict(self) -> dict[str, Any]:
        """Return legacy wire-tag dictionary representation."""
        return dict(self.to_params())


@dataclass
class LayerMetadata:
    """Layer block metadata referenced from a page's `MAINLAYER` / `LAYER1..3` / `BGLAYER` slot."""

    name: LayerName | str | None = None
    """`<LAYERNAME>` — Slot identifier (`MAINLAYER`, `LAYER1..3`, `BGLAYER`)."""

    protocol: LayerProtocol | str | None = None
    """`<LAYERPROTOCOL>` — Bitmap compression codec (`RATTA_RLE`, `SN_ASA_COMPRESS`)."""

    layer_type: LayerType | str | None = None
    """`<LAYERTYPE>` — Layer content kind (`NOTE`, `MARK`, or `BACKGROUND`)."""

    bitmap_address: int = 0
    """`<LAYERBITMAP>` — Byte offset to compressed layer bitmap (`0` if empty)."""

    path_address: int = 0
    """`<LAYERPATH>` — Byte offset to per-layer stroke vector data (`0` if empty)."""

    recogn_address: int = 0
    """`<LAYERRECOGN>` — Byte offset to per-layer recognition data (`0` if empty)."""

    vector_graph_address: int = 0
    """`<LAYERVECTORGRAPH>` — Byte offset to vector graphics payload (`0` if empty)."""

    extra: RawParamsBlock = field(default_factory=dict)
    """Forward-compatible map of any unrecognized `<KEY:VALUE>` layer tags."""

    _wire_keys: tuple[str, ...] = field(default=(), repr=False, compare=False)

    _KNOWN_KEYS = frozenset(
        {
            "LAYERNAME",
            "LAYERPROTOCOL",
            "LAYERTYPE",
            "LAYERBITMAP",
            "LAYERPATH",
            "LAYERRECOGN",
            "LAYERVECTORGRAPH",
        }
    )

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> Self:
        """Parse a raw `<KEY:VALUE>` layer dictionary into `LayerMetadata`."""
        wire_keys = tuple(k for k in params if k not in _SYNTHETIC_KEYS)
        return cls(
            name=_parse_optional_str_enum(
                params, "LAYERNAME", LayerName, sentinel="none"
            ),
            protocol=_parse_optional_str_enum(
                params, "LAYERPROTOCOL", LayerProtocol, sentinel="none"
            ),
            layer_type=_parse_optional_str_enum(
                params, "LAYERTYPE", LayerType, sentinel="none"
            ),
            bitmap_address=_parse_int_default(params, "LAYERBITMAP", 0),
            path_address=_parse_int_default(params, "LAYERPATH", 0),
            recogn_address=_parse_int_default(params, "LAYERRECOGN", 0),
            vector_graph_address=_parse_int_default(params, "LAYERVECTORGRAPH", 0),
            extra=_coerce_extra(params, set(cls._KNOWN_KEYS)),
            _wire_keys=wire_keys,
        )

    def to_params(self) -> RawParamsBlock:
        """Serialize to `<KEY:VALUE>` parameters preserving wire key order."""
        present = frozenset(self._wire_keys)
        encoded: RawParamsBlock = {}
        _put_optional_str(encoded, "LAYERNAME", self.name, present, sentinel="none")
        _put_optional_str(
            encoded, "LAYERPROTOCOL", self.protocol, present, sentinel="none"
        )
        _put_optional_str(
            encoded, "LAYERTYPE", self.layer_type, present, sentinel="none"
        )
        _put_int_default(encoded, "LAYERBITMAP", self.bitmap_address, present)
        _put_int_default(encoded, "LAYERPATH", self.path_address, present)
        _put_int_default(encoded, "LAYERRECOGN", self.recogn_address, present)
        _put_int_default(
            encoded, "LAYERVECTORGRAPH", self.vector_graph_address, present
        )
        encoded.update(self.extra)
        return _order_params(encoded, self._wire_keys)

    def to_wire_dict(self) -> dict[str, Any]:
        """Return legacy wire-tag dictionary representation."""
        return dict(self.to_params())


@dataclass
class KeywordMetadata:
    """Keyword index block metadata referenced from a footer `KEYWORD_<page4><y4>` tag."""

    page_index: int = 0
    """0-based page index derived from 1-based `<KEYWORDPAGE>`."""

    keyword: str | None = None
    """`<KEYWORD>` — Decoded UTF-8 keyword text."""

    keyword_len: int | None = None
    """`<KEYWORDLEN>` — Recorded character/byte length of the keyword."""

    rect: Rect | None = None
    """`<KEYWORDRECT>` — Cropped keyword bounding rectangle on the page."""

    rect_original: Rect | None = None
    """`<KEYWORDRECTORI>` — Original selection rectangle (used in footer index key)."""

    seq_no: int | None = None
    """`<KEYWORDSEQNO>` — Keyword sequence number."""

    site_address: int = 0
    """`<KEYWORDSITE>` — Byte offset to raw UTF-8 keyword text data block."""

    extra: RawParamsBlock = field(default_factory=dict)
    """Forward-compatible map of any unrecognized `<KEY:VALUE>` keyword tags."""

    _wire_keys: tuple[str, ...] = field(default=(), repr=False, compare=False)

    _KNOWN_KEYS = frozenset(
        {
            "KEYWORD",
            "KEYWORDLEN",
            "KEYWORDPAGE",
            "KEYWORDRECT",
            "KEYWORDRECTORI",
            "KEYWORDSEQNO",
            "KEYWORDSITE",
        }
    )

    @property
    def keyword_page(self) -> int:
        """1-based page number as stored on the wire in `<KEYWORDPAGE>`."""
        return self.page_index + 1

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> Self:
        """Parse a raw `<KEY:VALUE>` keyword dictionary into `KeywordMetadata`."""
        raw_page = params.get("KEYWORDPAGE")
        if isinstance(raw_page, bool) or not isinstance(raw_page, (str, int)):
            raise exceptions.ParserException("missing KEYWORDPAGE in keyword metadata")
        try:
            page_index = int(raw_page) - 1
        except ValueError as exc:
            raise exceptions.ParserException(
                f"invalid KEYWORDPAGE in keyword metadata: {raw_page!r}"
            ) from exc

        wire_keys = tuple(k for k in params if k not in _SYNTHETIC_KEYS)
        rect_str = _parse_optional_str(params, "KEYWORDRECT")
        rect_ori_str = _parse_optional_str(params, "KEYWORDRECTORI")
        keyword_val: str | None = None
        if "KEYWORD" in params and params["KEYWORD"] is not None:
            keyword_val = _as_single_str(params["KEYWORD"], "KEYWORD")

        return cls(
            page_index=page_index,
            keyword=keyword_val,
            keyword_len=_parse_optional_int(params, "KEYWORDLEN"),
            rect=Rect.from_wire(rect_str, "KEYWORDRECT") if rect_str else None,
            rect_original=(
                Rect.from_wire(rect_ori_str, "KEYWORDRECTORI") if rect_ori_str else None
            ),
            seq_no=_parse_optional_int(params, "KEYWORDSEQNO"),
            site_address=_parse_int_default(params, "KEYWORDSITE", 0),
            extra=_coerce_extra(params, set(cls._KNOWN_KEYS)),
            _wire_keys=wire_keys,
        )

    def to_params(self) -> RawParamsBlock:
        """Serialize to `<KEY:VALUE>` parameters preserving wire key order."""
        present = frozenset(self._wire_keys)
        encoded: RawParamsBlock = {"KEYWORDPAGE": str(self.keyword_page)}
        if self.keyword is not None:
            encoded["KEYWORD"] = self.keyword
        _put_optional_int(encoded, "KEYWORDLEN", self.keyword_len)
        if self.rect is not None:
            encoded["KEYWORDRECT"] = self.rect.to_wire()
        if self.rect_original is not None:
            encoded["KEYWORDRECTORI"] = self.rect_original.to_wire()
        _put_optional_int(encoded, "KEYWORDSEQNO", self.seq_no)
        _put_int_default(encoded, "KEYWORDSITE", self.site_address, present)
        encoded.update(self.extra)
        return _order_params(encoded, self._wire_keys)

    def to_wire_dict(self) -> dict[str, Any]:
        """Return legacy wire-tag dictionary representation."""
        return dict(self.to_params())


@dataclass
class TitleMetadata:
    """Heading/outline block metadata referenced from a footer `TITLE_<page4><pos>` tag."""

    page_index: int = 0
    """0-based page index extracted from the footer `TITLE_<page4>...` key."""

    bitmap_address: int = 0
    """`<TITLEBITMAP>` — Byte offset to RLE-compressed title stroke bitmap."""

    level: int | None = None
    """`<TITLELEVEL>` — Heading hierarchy level (`1`..`N`)."""

    protocol: LayerProtocol | str | None = None
    """`<TITLEPROTOCOL>` — Bitmap compression codec (typically `RATTA_RLE`)."""

    rect: Rect | None = None
    """`<TITLERECT>` — Tight bounding rectangle of the title strokes."""

    rect_original: Rect | None = None
    """`<TITLERECTORI>` — Original title region rectangle."""

    seq_no: int | None = None
    """`<TITLESEQNO>` — Title sequence number."""

    style: str | None = None
    """`<TITLESTYLE>` — Encoded visual style code (e.g. `1000254`)."""

    extra: RawParamsBlock = field(default_factory=dict)
    """Forward-compatible map of any unrecognized `<KEY:VALUE>` title tags."""

    _wire_keys: tuple[str, ...] = field(default=(), repr=False, compare=False)

    _KNOWN_KEYS = frozenset(
        {
            "TITLEBITMAP",
            "TITLELEVEL",
            "TITLEPROTOCOL",
            "TITLERECT",
            "TITLERECTORI",
            "TITLESEQNO",
            "TITLESTYLE",
        }
    )

    @classmethod
    def from_params(cls, params: Mapping[str, Any], *, page_index: int = 0) -> Self:
        """Parse a raw `<KEY:VALUE>` title dictionary into `TitleMetadata`."""
        wire_keys = tuple(k for k in params if k not in _SYNTHETIC_KEYS)
        rect_str = _parse_optional_str(params, "TITLERECT")
        rect_ori_str = _parse_optional_str(params, "TITLERECTORI")
        return cls(
            page_index=page_index,
            bitmap_address=_parse_int_default(params, "TITLEBITMAP", 0),
            level=_parse_optional_int(params, "TITLELEVEL"),
            protocol=_parse_optional_str_enum(
                params, "TITLEPROTOCOL", LayerProtocol, sentinel="none"
            ),
            rect=Rect.from_wire(rect_str, "TITLERECT") if rect_str else None,
            rect_original=(
                Rect.from_wire(rect_ori_str, "TITLERECTORI") if rect_ori_str else None
            ),
            seq_no=_parse_optional_int(params, "TITLESEQNO"),
            style=_parse_optional_str(params, "TITLESTYLE"),
            extra=_coerce_extra(params, set(cls._KNOWN_KEYS)),
            _wire_keys=wire_keys,
        )

    def to_params(self) -> RawParamsBlock:
        """Serialize to `<KEY:VALUE>` parameters preserving wire key order."""
        present = frozenset(self._wire_keys)
        encoded: RawParamsBlock = {}
        _put_int_default(encoded, "TITLEBITMAP", self.bitmap_address, present)
        _put_optional_int(encoded, "TITLELEVEL", self.level)
        _put_optional_str(
            encoded, "TITLEPROTOCOL", self.protocol, present, sentinel="none"
        )
        if self.rect is not None:
            encoded["TITLERECT"] = self.rect.to_wire()
        if self.rect_original is not None:
            encoded["TITLERECTORI"] = self.rect_original.to_wire()
        _put_optional_int(encoded, "TITLESEQNO", self.seq_no)
        _put_optional_str(encoded, "TITLESTYLE", self.style, present)
        encoded.update(self.extra)
        return _order_params(encoded, self._wire_keys)

    def to_wire_dict(self) -> dict[str, Any]:
        """Return legacy wire-tag dictionary representation."""
        return dict(self.to_params())


@dataclass
class LinkMetadata:
    """Hyperlink block metadata referenced from a footer `LINK*` tag."""

    page_index: int = 0
    """0-based source page index extracted from the footer `LINKO_<page4>...` key."""

    link_type: LinkType | int = LinkType.PAGE
    """`<LINKTYPE>` — Link target kind (`0` page, `1` file, `2` document, `4` web URL)."""

    direction: LinkDirection | int = LinkDirection.OUT
    """`<LINKINOUT>` — Link direction (`0` outgoing, `1` incoming)."""

    rect: Rect | None = None
    """`<LINKRECT>` — Active link hotspot rectangle on the page."""

    rect_original: Rect | None = None
    """`<LINKRECTORI>` — Original link stroke selection rectangle if present."""

    timestamp: str | None = None
    """`<LINKTIMESTAMP>` — Link creation/modification timestamp string."""

    file_path: str | None = None
    """`<LINKFILE>` — Base64-encoded target file path or URL."""

    file_id: str | None = None
    """`<LINKFILEID>` — Target Supernote `<FILE_ID>`, or `None` when wire value is `"none"`."""

    page_id: str | None = None
    """`<PAGEID>` — Target Supernote `<PAGEID>`, or `None` when wire value is `"none"`."""

    obj_page: int | None = None
    """`<OBJPAGE>` — Target/object page number recorded by firmware (`0` when not page-specific)."""

    bitmap_address: int = 0
    """`<LINKBITMAP>` — Byte offset to link visual indicator bitmap (`0` if empty)."""

    protocol: LayerProtocol | str | None = None
    """`<LINKPROTOCAL>` (or `<LINKPROTO>`) — Optional bitmap compression codec for the link indicator."""

    style: str | None = None
    """`<LINKSTYLE>` — Optional visual style descriptor for the link indicator."""

    font_size: str | None = None
    """`<FONTSIZE>` — Font size string for typeset text/digest links (e.g. `"0"` or `"40.000000"`)."""

    font_path: str | None = None
    """`<FONTPATH>` — Base64-encoded font path for typeset links, or `None` when `"none"`."""

    full_text: str | None = None
    """`<FULLTEXT>` — Base64-encoded full text label for typeset links, or `None` when `"none"`."""

    show_text: str | None = None
    """`<SHOWTEXT>` — Base64-encoded display label for typeset links, or `None` when `"none"`."""

    anti: int | None = None
    """`<ANTI>` — Anti-aliasing flag on typeset text links (`0` or `1`)."""

    bold: int | None = None
    """`<BOLD>` — Bold style flag on typeset text links (`0` or `1`)."""

    italic: int | None = None
    """`<ITALIC>` — Italic style flag on typeset text links (`0` or `1`)."""

    extra: RawParamsBlock = field(default_factory=dict)
    """Forward-compatible map of any unrecognized `<KEY:VALUE>` link tags."""

    _wire_keys: tuple[str, ...] = field(default=(), repr=False, compare=False)

    _KNOWN_KEYS = frozenset(
        {
            "LINKTYPE",
            "LINKINOUT",
            "LINKRECT",
            "LINKRECTORI",
            "LINKTIMESTAMP",
            "LINKFILE",
            "LINKFILEID",
            "PAGEID",
            "OBJPAGE",
            "LINKBITMAP",
            "LINKPROTOCAL",
            "LINKPROTO",
            "LINKSTYLE",
            "FONTSIZE",
            "FONTPATH",
            "FULLTEXT",
            "SHOWTEXT",
            "ANTI",
            "BOLD",
            "ITALIC",
        }
    )

    @classmethod
    def from_params(cls, params: Mapping[str, Any], *, page_index: int = 0) -> Self:
        """Parse a raw `<KEY:VALUE>` link dictionary into `LinkMetadata`."""
        wire_keys = tuple(k for k in params if k not in _SYNTHETIC_KEYS)
        rect_str = _parse_optional_str(params, "LINKRECT")
        rect_ori_str = _parse_optional_str(params, "LINKRECTORI")
        link_type = (
            _parse_int_enum(params["LINKTYPE"], LinkType, "LINKTYPE")
            if "LINKTYPE" in params
            else LinkType.PAGE
        )
        direction = (
            _parse_int_enum(params["LINKINOUT"], LinkDirection, "LINKINOUT")
            if "LINKINOUT" in params
            else LinkDirection.OUT
        )
        proto_key = "LINKPROTOCAL" if "LINKPROTOCAL" in params else "LINKPROTO"
        return cls(
            page_index=page_index,
            link_type=link_type,
            direction=direction,
            rect=Rect.from_wire(rect_str, "LINKRECT") if rect_str else None,
            rect_original=(
                Rect.from_wire(rect_ori_str, "LINKRECTORI") if rect_ori_str else None
            ),
            timestamp=_parse_optional_str(params, "LINKTIMESTAMP"),
            file_path=_parse_optional_str(params, "LINKFILE"),
            file_id=_parse_optional_str(params, "LINKFILEID", sentinel="none"),
            page_id=_parse_optional_str(params, "PAGEID", sentinel="none"),
            obj_page=_parse_optional_int(params, "OBJPAGE"),
            bitmap_address=_parse_int_default(params, "LINKBITMAP", 0),
            protocol=_parse_optional_str_enum(
                params, proto_key, LayerProtocol, sentinel="none"
            ),
            style=_parse_optional_str(params, "LINKSTYLE"),
            font_size=_parse_optional_str(params, "FONTSIZE"),
            font_path=_parse_optional_str(params, "FONTPATH", sentinel="none"),
            full_text=_parse_optional_str(params, "FULLTEXT", sentinel="none"),
            show_text=_parse_optional_str(params, "SHOWTEXT", sentinel="none"),
            anti=_parse_optional_int(params, "ANTI"),
            bold=_parse_optional_int(params, "BOLD"),
            italic=_parse_optional_int(params, "ITALIC"),
            extra=_coerce_extra(params, set(cls._KNOWN_KEYS)),
            _wire_keys=wire_keys,
        )

    def to_params(self) -> RawParamsBlock:
        """Serialize to `<KEY:VALUE>` parameters preserving wire key order."""
        present = frozenset(self._wire_keys)
        encoded: RawParamsBlock = {}
        _put_int_default(
            encoded,
            "LINKTYPE",
            int(self.link_type),
            present,
            default=int(LinkType.PAGE),
        )
        _put_int_default(
            encoded,
            "LINKINOUT",
            int(self.direction),
            present,
            default=int(LinkDirection.OUT),
        )
        if self.rect is not None:
            encoded["LINKRECT"] = self.rect.to_wire()
        if self.rect_original is not None:
            encoded["LINKRECTORI"] = self.rect_original.to_wire()
        _put_optional_str(encoded, "LINKTIMESTAMP", self.timestamp, present)
        _put_optional_str(encoded, "LINKFILE", self.file_path, present)
        _put_optional_str(encoded, "LINKFILEID", self.file_id, present, sentinel="none")
        _put_optional_str(encoded, "PAGEID", self.page_id, present, sentinel="none")
        _put_optional_int(encoded, "OBJPAGE", self.obj_page)
        _put_int_default(encoded, "LINKBITMAP", self.bitmap_address, present)
        proto_key = (
            "LINKPROTO"
            if "LINKPROTO" in present and "LINKPROTOCAL" not in present
            else "LINKPROTOCAL"
        )
        _put_optional_str(encoded, proto_key, self.protocol, present, sentinel="none")
        _put_optional_str(encoded, "LINKSTYLE", self.style, present)
        _put_optional_str(encoded, "FONTSIZE", self.font_size, present)
        _put_optional_str(encoded, "FONTPATH", self.font_path, present, sentinel="none")
        _put_optional_str(encoded, "FULLTEXT", self.full_text, present, sentinel="none")
        _put_optional_str(encoded, "SHOWTEXT", self.show_text, present, sentinel="none")
        _put_optional_int(encoded, "ANTI", self.anti)
        _put_optional_int(encoded, "BOLD", self.bold)
        _put_optional_int(encoded, "ITALIC", self.italic)
        encoded.update(self.extra)
        return _order_params(encoded, self._wire_keys)

    def to_wire_dict(self) -> dict[str, Any]:
        """Return legacy wire-tag dictionary representation."""
        return dict(self.to_params())


@dataclass
class PageMetadata:
    """Per-page metadata block referenced from a footer `PAGE` or `PAGE<N>` tag."""

    page_id: str | None = None
    """`<PAGEID>` — Stable device-generated page identifier."""

    style: str | None = None
    """`<PAGESTYLE>` — Built-in (`style_*`) or custom (`user_*`) template name."""

    style_md5: str | None = None
    """`<PAGESTYLEMD5>` — MD5 digest for custom `user_*` templates, `None` when `"0"`."""

    orientation: PageOrientation | str = PageOrientation.VERTICAL
    """`<ORIENTATION>` — Page rotation (`1000`, `1090`, `1180`, `1270`)."""

    main_layer_address: int = 0
    """`<MAINLAYER>` — Byte offset to `MAINLAYER` metadata block."""

    layer1_address: int = 0
    """`<LAYER1>` — Byte offset to `LAYER1` metadata block."""

    layer2_address: int = 0
    """`<LAYER2>` — Byte offset to `LAYER2` metadata block."""

    layer3_address: int = 0
    """`<LAYER3>` — Byte offset to `LAYER3` metadata block."""

    bg_layer_address: int = 0
    """`<BGLAYER>` — Byte offset to `BGLAYER` metadata block."""

    layer_info: list[LayerVisibility] | None = None
    """`<LAYERINFO>` — Eagerly decoded layer visibility/metadata array (`None` if `"none"`)."""

    layer_seq: list[LayerName | str] = field(default_factory=list)
    """`<LAYERSEQ>` — Ordered layer compositing sequence (top-to-bottom)."""

    layer_switch: int | None = None
    """`<LAYERSWITCH>` — Layer feature state flag."""

    totalpath_address: int = 0
    """`<TOTALPATH>` — Byte offset to vector stroke data block (`0` if absent)."""

    recogn_status: RecognitionStatus | int = RecognitionStatus.NONE
    """`<RECOGNSTATUS>` — Handwriting recognition status (`0` none, `1` done, `2` running)."""

    recogn_text_address: int = 0
    """`<RECOGNTEXT>` — Byte offset to base64 JSON recognition text block (`0` if absent)."""

    recogn_file_address: int = 0
    """`<RECOGNFILE>` — Byte offset to binary MyScript recognition `.ak` data (`0` if absent)."""

    recogn_file_status: int | None = None
    """`<RECOGNFILESTATUS>` — Recognition file readiness flag (`0` or `1`)."""

    recogn_type: int | None = None
    """`<RECOGNTYPE>` — Page-level recognition mode flag."""

    recogn_language: str | None = None
    """`<RECOGNLANGUAGE>` — Page-level recognition locale, `None` when `"none"`."""

    disable: str | None = None
    """`<DISABLE>` — Disabled feature flags, `None` when `"none"`."""

    external_link_info_address: int = 0
    """`<EXTERNALLINKINFO>` — Byte offset to external link table (`0` if absent)."""

    id_table_address: int = 0
    """`<IDTABLE>` — Byte offset to stroke/object ID table (`0` if absent)."""

    page_textbox_address: int = 0
    """`<PAGETEXTBOX>` — Byte offset to text box data (`0` if absent)."""

    thumbnail_type: int | None = None
    """`<THUMBNAILTYPE>` — Thumbnail format flag."""

    five_star: list[str] = field(default_factory=list)
    """`<FIVESTAR>` — 5-pointed star mark geometry descriptors (`"x1,y1,...,x5,y5,flag"`)."""

    data_address: int | None = None
    """`<DATA>` — Legacy A5 non-layered page bitmap offset (`None` on X-series pages)."""

    protocol: LayerProtocol | str | None = None
    """`<PROTOCOL>` — Legacy A5 non-layered page compression codec."""

    layers: list[LayerMetadata] | None = None
    """Parsed `LayerMetadata` blocks for X-series pages, or `None` for non-layered A5 pages."""

    extra: RawParamsBlock = field(default_factory=dict)
    """Forward-compatible map of any unrecognized `<KEY:VALUE>` page tags."""

    _wire_keys: tuple[str, ...] = field(default=(), repr=False, compare=False)
    _wire_layer_info: tuple[str, tuple[LayerVisibility, ...]] | None = field(
        default=None, repr=False, compare=False
    )

    _KNOWN_KEYS = frozenset(
        {
            "PAGEID",
            "PAGESTYLE",
            "PAGESTYLEMD5",
            "ORIENTATION",
            "MAINLAYER",
            "LAYER1",
            "LAYER2",
            "LAYER3",
            "BGLAYER",
            "LAYERINFO",
            "LAYERSEQ",
            "LAYERSWITCH",
            "TOTALPATH",
            "RECOGNSTATUS",
            "RECOGNTEXT",
            "RECOGNFILE",
            "RECOGNFILESTATUS",
            "RECOGNTYPE",
            "RECOGNLANGUAGE",
            "DISABLE",
            "EXTERNALLINKINFO",
            "IDTABLE",
            "PAGETEXTBOX",
            "THUMBNAILTYPE",
            "FIVESTAR",
            "DATA",
            "PROTOCOL",
        }
    )

    @property
    def is_layer_supported(self) -> bool:
        """Return `True` if this page uses X-series multi-layer metadata."""
        return self.layers is not None

    @classmethod
    def from_params(
        cls,
        params: Mapping[str, Any],
        *,
        layers: Sequence[LayerMetadata | Mapping[str, Any]] | None = None,
    ) -> Self:
        """Parse a raw `<KEY:VALUE>` page dictionary into `PageMetadata`."""
        wire_keys = tuple(k for k in params if k not in _SYNTHETIC_KEYS)

        raw_orientation = _parse_optional_str(params, "ORIENTATION")
        orientation: PageOrientation | str = (
            _parse_str_enum(raw_orientation, PageOrientation)
            if raw_orientation is not None
            else PageOrientation.VERTICAL
        )

        recogn_status: RecognitionStatus | int = RecognitionStatus.NONE
        if "RECOGNSTATUS" in params and params["RECOGNSTATUS"] is not None:
            raw_status = params["RECOGNSTATUS"]
            if isinstance(raw_status, bool) or not isinstance(raw_status, (str, int)):
                raise exceptions.ParserException(
                    f"invalid page RECOGNSTATUS: {raw_status!r}"
                )
            try:
                status_int = int(raw_status)
            except ValueError as exc:
                raise exceptions.ParserException(
                    f"invalid page RECOGNSTATUS: {raw_status!r}"
                ) from exc
            try:
                recogn_status = RecognitionStatus(status_int)
            except ValueError:
                recogn_status = status_int

        raw_layer_info_str = _parse_optional_str(params, "LAYERINFO")
        parsed_layer_info = parse_layer_info(raw_layer_info_str)
        wire_layer_info: tuple[str, tuple[LayerVisibility, ...]] | None = None
        if raw_layer_info_str is not None and parsed_layer_info is not None:
            wire_layer_info = (raw_layer_info_str, tuple(parsed_layer_info))

        raw_seq = _parse_optional_str(params, "LAYERSEQ", sentinel="none")
        layer_seq: list[LayerName | str] = []
        if raw_seq:
            layer_seq = [
                _parse_str_enum(part, LayerName) for part in raw_seq.split(",") if part
            ]

        raw_layers_input = layers if layers is not None else params.get(KEY_LAYERS)
        parsed_layers: list[LayerMetadata] | None = None
        if raw_layers_input is not None:
            if not isinstance(raw_layers_input, Sequence) or isinstance(
                raw_layers_input, (str, bytes)
            ):
                raise exceptions.ParserException("invalid page layers metadata")
            parsed_layers = []
            for item in raw_layers_input:
                if isinstance(item, LayerMetadata):
                    parsed_layers.append(item)
                elif isinstance(item, Mapping):
                    parsed_layers.append(LayerMetadata.from_params(item))
                else:
                    raise exceptions.ParserException("invalid layer metadata")

        five_star: list[str] = []
        if "FIVESTAR" in params and params["FIVESTAR"] is not None:
            raw_five_star = params["FIVESTAR"]
            if isinstance(raw_five_star, list):
                five_star = [_as_single_str(item, "FIVESTAR") for item in raw_five_star]
            else:
                single_five_star = _as_single_str(raw_five_star, "FIVESTAR")
                if single_five_star != "none":
                    five_star = [single_five_star]

        return cls(
            page_id=_parse_optional_str(params, "PAGEID", sentinel="none"),
            style=_parse_optional_str(params, "PAGESTYLE", sentinel="none"),
            style_md5=_parse_optional_str(params, "PAGESTYLEMD5", sentinel="0"),
            orientation=orientation,
            main_layer_address=_parse_int_default(params, "MAINLAYER", 0),
            layer1_address=_parse_int_default(params, "LAYER1", 0),
            layer2_address=_parse_int_default(params, "LAYER2", 0),
            layer3_address=_parse_int_default(params, "LAYER3", 0),
            bg_layer_address=_parse_int_default(params, "BGLAYER", 0),
            layer_info=parsed_layer_info,
            layer_seq=layer_seq,
            layer_switch=_parse_optional_int(params, "LAYERSWITCH"),
            totalpath_address=_parse_int_default(params, "TOTALPATH", 0),
            recogn_status=recogn_status,
            recogn_text_address=_parse_int_default(params, "RECOGNTEXT", 0),
            recogn_file_address=_parse_int_default(params, "RECOGNFILE", 0),
            recogn_file_status=_parse_optional_int(params, "RECOGNFILESTATUS"),
            recogn_type=_parse_optional_int(params, "RECOGNTYPE"),
            recogn_language=_parse_optional_str(
                params, "RECOGNLANGUAGE", sentinel="none"
            ),
            disable=_parse_optional_str(params, "DISABLE", sentinel="none"),
            external_link_info_address=_parse_int_default(
                params, "EXTERNALLINKINFO", 0
            ),
            id_table_address=_parse_int_default(params, "IDTABLE", 0),
            page_textbox_address=_parse_int_default(params, "PAGETEXTBOX", 0),
            thumbnail_type=_parse_optional_int(params, "THUMBNAILTYPE"),
            five_star=five_star,
            data_address=_parse_optional_int(params, "DATA"),
            protocol=_parse_optional_str_enum(
                params, "PROTOCOL", LayerProtocol, sentinel="none"
            ),
            layers=parsed_layers,
            extra=_coerce_extra(params, set(cls._KNOWN_KEYS)),
            _wire_keys=wire_keys,
            _wire_layer_info=wire_layer_info,
        )

    def to_params(self) -> RawParamsBlock:
        """Serialize page-level `<KEY:VALUE>` parameters preserving wire key order."""
        present = frozenset(self._wire_keys)
        encoded: RawParamsBlock = {}
        _put_optional_str(encoded, "PAGEID", self.page_id, present)
        _put_optional_str(encoded, "PAGESTYLE", self.style, present)
        _put_optional_str(
            encoded, "PAGESTYLEMD5", self.style_md5, present, sentinel="0"
        )
        if self.orientation != PageOrientation.VERTICAL or "ORIENTATION" in present:
            encoded["ORIENTATION"] = str(self.orientation)
        _put_int_default(encoded, "MAINLAYER", self.main_layer_address, present)
        _put_int_default(encoded, "LAYER1", self.layer1_address, present)
        _put_int_default(encoded, "LAYER2", self.layer2_address, present)
        _put_int_default(encoded, "LAYER3", self.layer3_address, present)
        _put_int_default(encoded, "BGLAYER", self.bg_layer_address, present)

        if self.layer_info is not None:
            if (
                self._wire_layer_info is not None
                and tuple(self.layer_info) == self._wire_layer_info[1]
            ):
                encoded["LAYERINFO"] = self._wire_layer_info[0]
            else:
                encoded["LAYERINFO"] = encode_layer_info(
                    self.layer_info, wire_escape=True
                )
        elif "LAYERINFO" in present:
            encoded["LAYERINFO"] = "none"

        if self.layer_seq:
            encoded["LAYERSEQ"] = ",".join(str(item) for item in self.layer_seq)
        elif "LAYERSEQ" in present:
            encoded["LAYERSEQ"] = "none"

        _put_optional_int(encoded, "LAYERSWITCH", self.layer_switch)
        _put_int_default(encoded, "TOTALPATH", self.totalpath_address, present)
        _put_int_default(
            encoded,
            "RECOGNSTATUS",
            int(self.recogn_status),
            present,
            default=int(RecognitionStatus.NONE),
        )
        _put_int_default(encoded, "RECOGNTEXT", self.recogn_text_address, present)
        _put_int_default(encoded, "RECOGNFILE", self.recogn_file_address, present)
        _put_optional_int(encoded, "RECOGNFILESTATUS", self.recogn_file_status)
        _put_optional_int(encoded, "RECOGNTYPE", self.recogn_type)
        _put_optional_str(
            encoded, "RECOGNLANGUAGE", self.recogn_language, present, sentinel="none"
        )
        _put_optional_str(encoded, "DISABLE", self.disable, present, sentinel="none")
        _put_int_default(
            encoded, "EXTERNALLINKINFO", self.external_link_info_address, present
        )
        _put_int_default(encoded, "IDTABLE", self.id_table_address, present)
        _put_int_default(encoded, "PAGETEXTBOX", self.page_textbox_address, present)
        _put_optional_int(encoded, "THUMBNAILTYPE", self.thumbnail_type)
        if self.five_star:
            encoded["FIVESTAR"] = (
                self.five_star[0] if len(self.five_star) == 1 else list(self.five_star)
            )
        elif "FIVESTAR" in present:
            encoded["FIVESTAR"] = "none"
        _put_optional_int(encoded, "DATA", self.data_address)
        _put_optional_str(encoded, "PROTOCOL", self.protocol, present, sentinel="none")
        encoded.update(self.extra)
        return _order_params(encoded, self._wire_keys)

    def to_wire_dict(self) -> dict[str, Any]:
        """Return legacy wire-tag dictionary (including `__layers__`) for hashing and JSON analysis."""
        result: dict[str, Any] = dict(self.to_params())
        if self.layers is not None:
            result[KEY_LAYERS] = [layer.to_wire_dict() for layer in self.layers]
        return result


@dataclass
class FooterMetadata:
    """File-level footer directory block pointed to by the trailing 4-byte file offset."""

    file_feature_address: int | None = None
    """`<FILE_FEATURE>` — Byte offset to the `HeaderMetadata` block."""

    page_addresses: dict[str, int] = field(default_factory=dict)
    """`PAGE1..N` — Mapping of X-series page keys to page metadata block byte offsets."""

    legacy_page_addresses: list[int] = field(default_factory=list)
    """`<PAGE>` — Ordered list of page metadata block offsets for legacy A5 files."""

    cover_addresses: dict[str, int] = field(default_factory=dict)
    """`COVER_0..2` — Mapping of cover slot keys to cover bitmap byte offsets."""

    style_addresses: dict[str, list[int]] = field(default_factory=dict)
    """`STYLE_*` — Mapping of template style keys to shared style bitmap offsets."""

    pdf_style_list_address: int | None = None
    """`<PDFSTYLELIST>` — Byte offset to comma-separated base64 PDF template style names block."""

    keyword_addresses: dict[str, list[int]] = field(default_factory=dict)
    """`KEYWORD_*` — Mapping of positional keyword keys to keyword metadata block offsets."""

    title_addresses: dict[str, list[int]] = field(default_factory=dict)
    """`TITLE_*` — Mapping of positional title keys to title metadata block offsets."""

    link_addresses: dict[str, list[int]] = field(default_factory=dict)
    """`LINK*` — Mapping of positional link keys to link metadata block offsets."""

    dirty: int | None = None
    """`<DIRTY>` — Notebook dirty/sync state counter."""

    keywords: list[KeywordMetadata] = field(default_factory=list)
    """Parsed `KeywordMetadata` blocks referenced by `keyword_addresses`."""

    titles: list[TitleMetadata] = field(default_factory=list)
    """Parsed `TitleMetadata` blocks referenced by `title_addresses`."""

    links: list[LinkMetadata] = field(default_factory=list)
    """Parsed `LinkMetadata` blocks referenced by `link_addresses`."""

    extra: RawParamsBlock = field(default_factory=dict)
    """Forward-compatible map of any unrecognized `<KEY:VALUE>` footer tags."""

    _wire_keys: tuple[str, ...] = field(default=(), repr=False, compare=False)

    @property
    def cover_address(self) -> int:
        """Resolved cover bitmap offset (`COVER_2` preferred over `COVER_1`, else `0`)."""
        if "COVER_2" in self.cover_addresses:
            return self.cover_addresses["COVER_2"]
        if "COVER_1" in self.cover_addresses:
            return self.cover_addresses["COVER_1"]
        return 0

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> Self:
        """Parse a raw `<KEY:VALUE>` footer dictionary into `FooterMetadata`."""
        wire_keys = tuple(k for k in params if k not in _SYNTHETIC_KEYS)
        file_feature_address = _parse_optional_int(params, "FILE_FEATURE")
        pdf_style_list_address = _parse_optional_int(params, "PDFSTYLELIST")
        dirty = _parse_optional_int(params, "DIRTY")

        page_addresses: dict[str, int] = {}
        legacy_page_addresses: list[int] = []
        cover_addresses: dict[str, int] = {}
        style_addresses: dict[str, list[int]] = {}
        keyword_addresses: dict[str, list[int]] = {}
        title_addresses: dict[str, list[int]] = {}
        link_addresses: dict[str, list[int]] = {}
        extra: RawParamsBlock = {}

        for key, value in params.items():
            if key in _SYNTHETIC_KEYS or key in (
                "FILE_FEATURE",
                "PDFSTYLELIST",
                "DIRTY",
            ):
                continue
            if key == "PAGE":
                legacy_page_addresses = _parse_address_list(value, key)
            elif key.startswith("PAGE"):
                page_addresses[key] = _parse_int(value, key)
            elif key.startswith("COVER_"):
                cover_addresses[key] = _parse_int(value, key)
            elif key.startswith("STYLE_"):
                style_addresses[key] = _parse_address_list(value, key)
            elif key.startswith("KEYWORD_"):
                keyword_addresses[key] = _parse_address_list(value, key)
            elif key.startswith("TITLE_"):
                title_addresses[key] = _parse_address_list(value, key)
            elif key.startswith("LINK"):
                link_addresses[key] = _parse_address_list(value, key)
            elif isinstance(value, list):
                extra[key] = [str(item) for item in value]
            else:
                extra[key] = str(value)

        keywords = [
            item
            if isinstance(item, KeywordMetadata)
            else KeywordMetadata.from_params(item)
            for item in (params.get(KEY_KEYWORDS) or [])
        ]
        titles = [
            item if isinstance(item, TitleMetadata) else TitleMetadata.from_params(item)
            for item in (params.get(KEY_TITLES) or [])
        ]
        links = [
            item if isinstance(item, LinkMetadata) else LinkMetadata.from_params(item)
            for item in (params.get(KEY_LINKS) or [])
        ]

        return cls(
            file_feature_address=file_feature_address,
            page_addresses=page_addresses,
            legacy_page_addresses=legacy_page_addresses,
            cover_addresses=cover_addresses,
            style_addresses=style_addresses,
            pdf_style_list_address=pdf_style_list_address,
            keyword_addresses=keyword_addresses,
            title_addresses=title_addresses,
            link_addresses=link_addresses,
            dirty=dirty,
            keywords=keywords,
            titles=titles,
            links=links,
            extra=extra,
            _wire_keys=wire_keys,
        )

    def to_params(self) -> RawParamsBlock:
        """Serialize footer `<KEY:VALUE>` parameters preserving wire key order."""
        encoded: RawParamsBlock = {}
        _put_optional_int(encoded, "FILE_FEATURE", self.file_feature_address)
        if self.legacy_page_addresses:
            if len(self.legacy_page_addresses) == 1:
                encoded["PAGE"] = str(self.legacy_page_addresses[0])
            else:
                encoded["PAGE"] = [str(a) for a in self.legacy_page_addresses]
        for key, addr in self.page_addresses.items():
            encoded[key] = str(addr)
        for key, addrs in self.title_addresses.items():
            encoded[key] = str(addrs[0]) if len(addrs) == 1 else [str(a) for a in addrs]
        for key, addrs in self.keyword_addresses.items():
            encoded[key] = str(addrs[0]) if len(addrs) == 1 else [str(a) for a in addrs]
        for key, addrs in self.link_addresses.items():
            encoded[key] = str(addrs[0]) if len(addrs) == 1 else [str(a) for a in addrs]
        for key, addr in self.cover_addresses.items():
            encoded[key] = str(addr)
        for key, addrs in self.style_addresses.items():
            encoded[key] = str(addrs[0]) if len(addrs) == 1 else [str(a) for a in addrs]
        _put_optional_int(encoded, "PDFSTYLELIST", self.pdf_style_list_address)
        _put_optional_int(encoded, "DIRTY", self.dirty)
        encoded.update(self.extra)
        return _order_params(encoded, self._wire_keys)

    def to_wire_dict(self) -> dict[str, Any]:
        """Return legacy wire-tag dictionary (including `__keywords__`, `__titles__`, `__links__`)."""
        result: dict[str, Any] = dict(self.to_params())
        if self.keywords:
            result[KEY_KEYWORDS] = [kw.to_wire_dict() for kw in self.keywords]
        if self.titles:
            result[KEY_TITLES] = [t.to_wire_dict() for t in self.titles]
        if self.links:
            result[KEY_LINKS] = [link.to_wire_dict() for link in self.links]
        return result


class SupernoteMetadata:
    """Typed structural metadata tree for a Supernote `.note` or `.mark` file.

    Returned by `parse_metadata()` without loading compressed bitmap payloads into memory,
    and attached to `Notebook.metadata` when loaded via `load()` / `load_notebook()`.
    """

    def __init__(
        self,
        type: str,
        signature: str,
        header: HeaderMetadata | Mapping[str, Any],
        footer: FooterMetadata | Mapping[str, Any],
        pages: Sequence[PageMetadata | Mapping[str, Any]],
    ) -> None:
        self._type = ""
        self._signature = ""
        self._header = HeaderMetadata()
        self._footer = FooterMetadata()
        self._pages: list[PageMetadata] = []

        self.type = type
        self.signature = signature
        self.header = header  # type: ignore[assignment]
        self.footer = footer  # type: ignore[assignment]
        self.pages = pages  # type: ignore[assignment]

    @property
    def type(self) -> str:
        """4-byte container prefix (e.g. `'note'` or `'mark'`)."""
        return self._type

    @type.setter
    def type(self, value: str) -> None:
        if not isinstance(value, str):
            raise exceptions.ParserException("notebook metadata type is missing")
        self._type = value

    @property
    def signature(self) -> str:
        """Format version signature (e.g. `'SN_FILE_VER_20230015'`)."""
        return self._signature

    @signature.setter
    def signature(self, value: str) -> None:
        if not isinstance(value, str):
            raise exceptions.ParserException("notebook metadata signature is missing")
        self._signature = value

    @property
    def header(self) -> HeaderMetadata:
        """Parsed `<FILE_FEATURE>` header block."""
        return self._header

    @header.setter
    def header(self, value: HeaderMetadata | Mapping[str, Any]) -> None:
        if isinstance(value, HeaderMetadata):
            self._header = value
        elif isinstance(value, Mapping):
            self._header = HeaderMetadata.from_params(value)
        else:
            raise exceptions.ParserException("notebook metadata header is missing")

    @property
    def footer(self) -> FooterMetadata:
        """Parsed footer directory block (including keyword, title, and link metadata)."""
        return self._footer

    @footer.setter
    def footer(self, value: FooterMetadata | Mapping[str, Any]) -> None:
        if isinstance(value, FooterMetadata):
            self._footer = value
        elif isinstance(value, Mapping):
            self._footer = FooterMetadata.from_params(value)
        else:
            raise exceptions.ParserException("notebook metadata footer is missing")

    @property
    def pages(self) -> list[PageMetadata]:
        """Ordered list of parsed per-page metadata blocks."""
        return self._pages

    @pages.setter
    def pages(self, value: Sequence[PageMetadata | Mapping[str, Any]]) -> None:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise exceptions.ParserException("notebook metadata pages are missing")
        coerced: list[PageMetadata] = []
        for entry in value:
            if isinstance(entry, PageMetadata):
                coerced.append(entry)
            elif isinstance(entry, Mapping):
                coerced.append(PageMetadata.from_params(entry))
            else:
                raise exceptions.ParserException("invalid page metadata entry")
        self._pages = coerced

    @property
    def total_pages(self) -> int:
        """Total number of pages in the notebook."""
        return len(self._pages)

    @deprecated("Use SupernoteMetadata.total_pages instead")
    def get_total_pages(self) -> int:
        """Return total page count."""
        return self.total_pages

    def is_layer_supported(self, page_number: int) -> bool:
        """Return `True` if `page_number` uses X-series multi-layer metadata."""
        if page_number < 0 or page_number >= len(self._pages):
            raise IndexError(f"page number out of range: {page_number}")
        return self._pages[page_number].is_layer_supported

    def to_wire_dict(self) -> dict[str, Any]:
        """Return legacy wire-tag dictionary (`__type__`, `__header__`, etc.)."""
        return {
            KEY_TYPE: self._type,
            KEY_SIGNATURE: self._signature,
            KEY_HEADER: self._header.to_wire_dict(),
            KEY_FOOTER: self._footer.to_wire_dict(),
            KEY_PAGES: [page.to_wire_dict() for page in self._pages],
        }

    def to_dict(self) -> dict[str, Any]:
        """Return structured Pythonic dictionary representation."""

        def _public_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            return {k: v for k, v in pairs if not k.startswith("_")}

        return {
            "type": self._type,
            "signature": self._signature,
            "header": dataclasses.asdict(self._header, dict_factory=_public_fields),
            "footer": dataclasses.asdict(self._footer, dict_factory=_public_fields),
            "pages": [
                dataclasses.asdict(page, dict_factory=_public_fields)
                for page in self._pages
            ],
        }

    def to_json(self, **kwargs: Any) -> str:
        """Serialize wire-tag structure as a JSON string (used by `supernote analyze`)."""
        kwargs.setdefault("ensure_ascii", False)
        return json.dumps(self.to_wire_dict(), **kwargs)


__all__ = [
    "EquipmentType",
    "FileType",
    "FooterMetadata",
    "HeaderMetadata",
    "KeywordMetadata",
    "LayerMetadata",
    "LayerName",
    "LayerProtocol",
    "LayerType",
    "LayerVisibility",
    "LinkDirection",
    "LinkMetadata",
    "LinkType",
    "PageMetadata",
    "PageOrientation",
    "RawParamValue",
    "RawParamsBlock",
    "RecognitionStatus",
    "Rect",
    "SupernoteMetadata",
    "TitleMetadata",
    "encode_layer_info",
    "encode_parameters",
    "extract_parameters",
    "parse_layer_info",
]
