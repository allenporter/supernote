# Copyright (c) 2020 jya
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Loaded domain objects for the Supernote `.note` / `.mark` file format.

The Supernote file format relies on a "Footer-first" parsing strategy.
The last 4 bytes of the file contain the offset to the Footer Block, which
references all other metadata blocks (Header, Pages, Titles, Keywords, Links).
Wire-level metadata blocks and enums live in `supernote.notebook.schema`.
"""

import base64
import binascii
import zlib
from collections.abc import Mapping, Sequence
from typing import Any
from warnings import deprecated

import numpy as np

from . import decoder, exceptions
from .schema import (
    KEY_FOOTER,
    KEY_HEADER,
    KEY_KEYWORDS,
    KEY_LAYERS,
    KEY_LINKS,
    KEY_PAGES,
    KEY_SIGNATURE,
    KEY_TITLES,
    KEY_TYPE,
    EquipmentType,
    KeywordMetadata,
    LayerMetadata,
    LayerName,
    LayerProtocol,
    LayerType,
    LinkDirection,
    LinkMetadata,
    LinkType,
    PageMetadata,
    PageOrientation,
    RecognitionStatus,
    SupernoteMetadata,
    TitleMetadata,
    encode_layer_info,
)

ParamsBlock = dict[str, Any]

#### Constants

PAGE_HEIGHT = 1872
PAGE_WIDTH = 1404
A5X2_PAGE_HEIGHT = 2560
A5X2_PAGE_WIDTH = 1920

ADDRESS_SIZE = 4
LENGTH_FIELD_SIZE = 4


class Notebook:
    """Loaded Supernote notebook combining typed `SupernoteMetadata` and binary payloads."""

    def __init__(
        self, metadata: SupernoteMetadata, page_number: int | None = None
    ) -> None:
        self._metadata = metadata
        self.metadata = metadata
        self.loaded_page_number = page_number
        self.page_width = PAGE_WIDTH
        self.page_height = PAGE_HEIGHT
        if self._metadata.header.apply_equipment == EquipmentType.N5:
            self.page_width = A5X2_PAGE_WIDTH
            self.page_height = A5X2_PAGE_HEIGHT
        self.cover = Cover()
        self.keywords: list[Keyword] = [Keyword(k) for k in metadata.footer.keywords]
        self.titles: list[Title] = [Title(t) for t in metadata.footer.titles]
        self.links: list[Link] = [Link(link) for link in metadata.footer.links]
        self.pages: list[Page] = []
        for idx, page_info in enumerate(metadata.pages):
            if not isinstance(page_info, PageMetadata):
                raise exceptions.ParserException("invalid page metadata entry")
            self.pages.append(Page(page_info, page_number=idx, notebook=self))

    @property
    def metadata(self) -> SupernoteMetadata:
        """Typed wire-format metadata tree (`SupernoteMetadata`)."""
        if not isinstance(self._metadata, SupernoteMetadata):
            raise exceptions.ParserException("notebook metadata is missing")
        return self._metadata

    @metadata.setter
    def metadata(self, value: SupernoteMetadata) -> None:
        if not isinstance(value, SupernoteMetadata):
            raise exceptions.ParserException("notebook metadata is missing")
        self._metadata = value

    @property
    def width(self) -> int:
        """Canvas width in pixels (`1404` or `1920` for A5 X2 Manta)."""
        return self.page_width

    @width.setter
    def width(self, value: int) -> None:
        self.page_width = value

    @property
    def height(self) -> int:
        """Canvas height in pixels (`1872` or `2560` for A5 X2 Manta)."""
        return self.page_height

    @height.setter
    def height(self, value: int) -> None:
        self.page_height = value

    @property
    def type(self) -> str:
        """4-byte container prefix (`'note'` or `'mark'`)."""
        return self.metadata.type

    @type.setter
    def type(self, value: str) -> None:
        self.metadata.type = value

    @property
    def signature(self) -> str:
        """Format version signature (e.g. `'SN_FILE_VER_20230015'`)."""
        return self.metadata.signature

    @signature.setter
    def signature(self, value: str) -> None:
        self.metadata.signature = value

    @property
    def total_pages(self) -> int:
        """Total number of pages in the notebook."""
        return len(self.pages)

    @property
    def file_id(self) -> str | None:
        """Stable device-generated notebook identifier (`<FILE_ID>`)."""
        return self.metadata.header.file_id

    def page(self, number: int) -> "Page":
        """Return the `Page` at 0-based `number`, enforcing single-page load bounds."""
        if number < 0 or number >= len(self.pages):
            raise IndexError(f"page number out of range: {number}")
        if self.loaded_page_number is not None and number != self.loaded_page_number:
            raise ValueError(
                f"Notebook was loaded with only page_number={self.loaded_page_number}; cannot access page {number}"
            )
        return self.pages[number]

    def is_realtime_recognition(self) -> bool:
        """Return `True` if real-time handwriting recognition is enabled (`FILE_RECOGN_TYPE == 1`)."""
        return self.metadata.header.file_recogn_type == 1

    def supports_highres_grayscale(self) -> bool:
        """Return `True` if the format signature supports X2 high-resolution grayscale (`>= 20230015`)."""
        if len(self.signature) < 8 or not self.signature[-8:].isdigit():
            return False
        return int(self.signature[-8:]) >= 20230015

    @deprecated("Use Notebook.metadata instead")
    def get_metadata(self) -> SupernoteMetadata:
        return self.metadata

    @deprecated("Use Notebook.width instead")
    def get_width(self) -> int:
        return self.width

    @deprecated("Use Notebook.height instead")
    def get_height(self) -> int:
        return self.height

    @deprecated("Use Notebook.type instead")
    def get_type(self) -> str:
        return self.type

    @deprecated("Use Notebook.signature instead")
    def get_signature(self) -> str:
        return self.signature

    @deprecated("Use Notebook.total_pages instead")
    def get_total_pages(self) -> int:
        return self.total_pages

    @deprecated("Use Notebook.page() or Notebook.pages instead")
    def get_page(self, number: int) -> "Page":
        return self.page(number)

    @deprecated("Use Notebook.cover instead")
    def get_cover(self) -> "Cover":
        return self.cover

    @deprecated("Use Notebook.keywords instead")
    def get_keywords(self) -> list["Keyword"]:
        return self.keywords

    @deprecated("Use Notebook.titles instead")
    def get_titles(self) -> list["Title"]:
        return self.titles

    @deprecated("Use Notebook.links instead")
    def get_links(self) -> list["Link"]:
        return self.links

    @deprecated("Use Notebook.file_id instead")
    def get_fileid(self) -> str | None:
        return self.file_id


class Cover:
    """Loaded cover bitmap container."""

    def __init__(self, content: bytes | None = None) -> None:
        self.content: bytes | None = content

    @deprecated("Assign to Cover.content instead")
    def set_content(self, content: bytes | None) -> None:
        self.content = content

    @deprecated("Use Cover.content instead")
    def get_content(self) -> bytes | None:
        return self.content


class Keyword:
    """Loaded keyword entry combining `KeywordMetadata` and raw keyword bytes."""

    def __init__(
        self,
        keyword_info: KeywordMetadata | Mapping[str, Any],
        content: bytes | None = None,
    ) -> None:
        if isinstance(keyword_info, KeywordMetadata):
            self.metadata = keyword_info
        elif isinstance(keyword_info, Mapping):
            self.metadata = KeywordMetadata.from_params(keyword_info)
        else:
            raise exceptions.ParserException("invalid keyword metadata")
        self.content: bytes | None = content

    @property
    def page_number(self) -> int:
        """0-based page index where this keyword appears."""
        return self.metadata.page_index

    @page_number.setter
    def page_number(self, value: int) -> None:
        self.metadata.page_index = value

    @property
    def keyword(self) -> str | None:
        """Decoded UTF-8 keyword string."""
        return self.metadata.keyword

    @property
    def rect(self) -> tuple[int, int, int, int]:
        """Bounding box `(left, top, right, bottom)` in page coordinates."""
        if self.metadata.rect is None:
            raise exceptions.ParserException("missing KEYWORDRECT in keyword metadata")
        return self.metadata.rect.bbox

    @property
    def position_string(self) -> str:
        """4-digit zero-padded top coordinate used in footer `KEYWORD_<page4><pos4>` keys."""
        if self.metadata.rect_original is None:
            raise exceptions.ParserException(
                "missing KEYWORDRECTORI in keyword metadata"
            )
        return f"{self.metadata.rect_original.top:04d}"

    @deprecated("Assign to Keyword.content instead")
    def set_content(self, content: bytes | None) -> None:
        self.content = content

    @deprecated("Use Keyword.content instead")
    def get_content(self) -> bytes | None:
        return self.content

    @deprecated("Use Keyword.page_number instead")
    def get_page_number(self) -> int:
        return self.page_number

    @deprecated("Use Keyword.position_string instead")
    def get_position_string(self) -> str:
        return self.position_string

    @deprecated("Use Keyword.keyword instead")
    def get_keyword(self) -> str | None:
        return self.keyword

    @deprecated("Use Keyword.rect instead")
    def get_rect(self) -> tuple[int, int, int, int]:
        return self.rect


class Title:
    """Loaded heading/outline entry combining `TitleMetadata` and stroke bitmap bytes."""

    def __init__(
        self,
        title_info: TitleMetadata | Mapping[str, Any],
        content: bytes | None = None,
        page_number: int | None = None,
    ) -> None:
        if isinstance(title_info, TitleMetadata):
            self.metadata = title_info
        elif isinstance(title_info, Mapping):
            self.metadata = TitleMetadata.from_params(title_info)
        else:
            raise exceptions.ParserException("invalid title metadata")
        self.content: bytes | None = content
        if page_number is not None:
            self.metadata.page_index = page_number

    @property
    def page_number(self) -> int:
        """0-based page index where this title appears."""
        return self.metadata.page_index

    @page_number.setter
    def page_number(self, value: int) -> None:
        self.metadata.page_index = value

    @property
    def level(self) -> int | None:
        """Heading hierarchy level (`<TITLELEVEL>`)."""
        return self.metadata.level

    @property
    def style(self) -> str | None:
        """Encoded visual heading style (`<TITLESTYLE>`, e.g. `'1000254'`)."""
        return self.metadata.style

    @property
    def protocol(self) -> LayerProtocol | str | None:
        """Bitmap compression protocol (`<TITLEPROTOCOL>`)."""
        return self.metadata.protocol

    @property
    def rect(self) -> tuple[int, int, int, int]:
        """Bounding box `(left, top, right, bottom)` in page coordinates."""
        if self.metadata.rect is None:
            raise exceptions.ParserException("missing TITLERECT in title metadata")
        return self.metadata.rect.bbox

    @property
    def position_string(self) -> str:
        """8-digit `<top4><left4>` coordinate suffix used in footer `TITLE_<page4><pos8>` keys."""
        if self.metadata.rect_original is None:
            raise exceptions.ParserException("missing TITLERECTORI in title metadata")
        return (
            f"{self.metadata.rect_original.top:04d}"
            f"{self.metadata.rect_original.left:04d}"
        )

    @deprecated("Assign to Title.content instead")
    def set_content(self, content: bytes | None) -> None:
        self.content = content

    @deprecated("Use Title.content instead")
    def get_content(self) -> bytes | None:
        return self.content

    @deprecated("Assign to Title.page_number instead")
    def set_page_number(self, page_number: int) -> None:
        self.page_number = page_number

    @deprecated("Use Title.page_number instead")
    def get_page_number(self) -> int:
        return self.page_number

    @deprecated("Use Title.position_string instead")
    def get_position_string(self) -> str:
        return self.position_string


class Link:
    """Loaded hyperlink entry combining `LinkMetadata` and indicator bitmap bytes."""

    # Link Types
    TYPE_PAGE_LINK = LinkType.PAGE.value  # Internal link to another page
    TYPE_FILE_LINK = LinkType.FILE.value  # Link to another file
    TYPE_WEB_LINK = LinkType.WEB.value  # External web link

    # Link Direction
    DIRECTION_OUT = LinkDirection.OUT.value  # Outgoing link (from this page)
    DIRECTION_IN = LinkDirection.IN.value  # Incoming link (to this page)

    def __init__(
        self,
        link_info: LinkMetadata | Mapping[str, Any],
        content: bytes | None = None,
        page_number: int | None = None,
    ) -> None:
        if isinstance(link_info, LinkMetadata):
            self.metadata = link_info
        elif isinstance(link_info, Mapping):
            self.metadata = LinkMetadata.from_params(link_info)
        else:
            raise exceptions.ParserException("invalid link metadata")
        self.content: bytes | None = content
        if page_number is not None:
            self.metadata.page_index = page_number

    @property
    def page_number(self) -> int:
        """0-based page index where this link appears."""
        return self.metadata.page_index

    @page_number.setter
    def page_number(self, value: int) -> None:
        self.metadata.page_index = value

    @property
    def link_type(self) -> LinkType | int:
        """Link target category (`LinkType.PAGE`, `LinkType.FILE`, or `LinkType.WEB`)."""
        return self.metadata.link_type

    @property
    def direction(self) -> LinkDirection | int:
        """Link direction (`LinkDirection.OUT` or `LinkDirection.IN`)."""
        return self.metadata.direction

    @property
    def rect(self) -> tuple[int, int, int, int]:
        """Bounding box `(left, top, right, bottom)` in page coordinates."""
        if self.metadata.rect is None:
            raise exceptions.ParserException("missing LINKRECT in link metadata")
        return self.metadata.rect.bbox

    @property
    def position_string(self) -> str:
        """16-digit `<top4><left4><height4><width4>` suffix used in footer `LINKO_<page4><pos16>` keys."""
        if self.metadata.rect is None:
            raise exceptions.ParserException("missing LINKRECT in link metadata")
        rect = self.metadata.rect
        return f"{rect.top:04d}{rect.left:04d}{rect.height:04d}{rect.width:04d}"

    @property
    def timestamp(self) -> str | None:
        """Link creation/modification timestamp string (`<LINKTIMESTAMP>`)."""
        return self.metadata.timestamp

    @property
    def file_path(self) -> str | None:
        """Base64-encoded target file path or URL (`<LINKFILE>`)."""
        return self.metadata.file_path

    @property
    def target(self) -> str | None:
        """Decoded UTF-8 target file path or URL from `<LINKFILE>`, or `None` if unset."""
        raw = self.file_path
        if not raw or raw == "none":
            return None
        try:
            decoded = base64.b64decode(raw, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return raw
        if decoded and all(ch.isprintable() for ch in decoded):
            return decoded
        return raw

    @property
    def file_id(self) -> str | None:
        """Target notebook `<FILE_ID>` (`<LINKFILEID>`), or `None` if unset."""
        return self.metadata.file_id

    @property
    def page_id(self) -> str | None:
        """Target page `<PAGEID>`, or `None` if unset."""
        return self.metadata.page_id

    @deprecated("Assign to Link.content instead")
    def set_content(self, content: bytes | None) -> None:
        self.content = content

    @deprecated("Use Link.content instead")
    def get_content(self) -> bytes | None:
        return self.content

    @deprecated("Assign to Link.page_number instead")
    def set_page_number(self, page_number: int) -> None:
        self.page_number = page_number

    @deprecated("Use Link.page_number instead")
    def get_page_number(self) -> int:
        return self.page_number

    @deprecated("Use Link.link_type instead")
    def get_type(self) -> int:
        return int(self.link_type)

    @deprecated("Use Link.direction instead")
    def get_inout(self) -> int:
        return int(self.direction)

    @deprecated("Use Link.position_string instead")
    def get_position_string(self) -> str:
        return self.position_string

    @deprecated("Use Link.rect instead")
    def get_rect(self) -> tuple[int, int, int, int]:
        return self.rect

    @deprecated("Use Link.timestamp instead")
    def get_timestamp(self) -> str | None:
        return self.timestamp

    @deprecated("Use Link.file_path instead")
    def get_filepath(self) -> str | None:
        return self.file_path  # Base64-encoded file path or URL

    @deprecated("Use Link.file_id instead")
    def get_fileid(self) -> str | None:
        return self.file_id

    @deprecated("Use Link.page_id instead")
    def get_pageid(self) -> str | None:
        return self.page_id


class Page:
    """Loaded page combining `PageMetadata`, `Layer` objects, and page-level binary streams."""

    # Recognition Status
    RECOGNSTATUS_NONE = RecognitionStatus.NONE.value  # No recognition performed
    RECOGNSTATUS_DONE = (
        RecognitionStatus.DONE.value
    )  # Recognition complete (RECOGNTEXT available)
    RECOGNSTATUS_RUNNING = RecognitionStatus.RUNNING.value  # Recognition in progress

    # Orientation
    ORIENTATION_VERTICAL = PageOrientation.VERTICAL.value  # Portrait
    ORIENTATION_HORIZONTAL = PageOrientation.HORIZONTAL.value  # Landscape
    ORIENTATION_VERTICAL_180 = PageOrientation.VERTICAL_180.value  # Portrait flipped
    ORIENTATION_HORIZONTAL_270 = (
        PageOrientation.HORIZONTAL_270.value
    )  # Landscape flipped

    def __init__(
        self,
        page_info: PageMetadata | Mapping[str, Any],
        content: bytes | None = None,
        totalpath: bytes | None = None,
        recogn_file: bytes | None = None,
        recogn_text: bytes | None = None,
        *,
        page_number: int | None = None,
        notebook: "Notebook | None" = None,
        keywords: Sequence[Keyword] | None = None,
        titles: Sequence[Title] | None = None,
        links: Sequence[Link] | None = None,
    ) -> None:
        if isinstance(page_info, PageMetadata):
            self.metadata = page_info
        elif isinstance(page_info, Mapping):
            self.metadata = PageMetadata.from_params(page_info)
        else:
            raise exceptions.ParserException("invalid page metadata")
        self.content: bytes | None = content
        self.totalpath: bytes | None = totalpath
        self.recogn_file: bytes | None = recogn_file
        self.recogn_text: bytes | None = recogn_text
        self._page_index: int | None = page_number
        self._notebook: Notebook | None = notebook
        self._keywords: list[Keyword] = list(keywords) if keywords is not None else []
        self._titles: list[Title] = list(titles) if titles is not None else []
        self._links: list[Link] = list(links) if links is not None else []
        self.layers: list[Layer] = [
            Layer(layer_meta) for layer_meta in (self.metadata.layers or [])
        ]

    @property
    def page_number(self) -> int | None:
        """0-based index of this page within its owning `Notebook`, or `None` if standalone."""
        return self._page_index

    @property
    def page_id(self) -> str | None:
        """Stable page identifier (`<PAGEID>`)."""
        return self.metadata.page_id

    @property
    def style(self) -> str | None:
        """Page template/background style name (`<PAGESTYLE>`)."""
        return self.metadata.style

    @property
    def style_hash(self) -> str:
        """Custom template MD5 hash (`<PAGESTYLEMD5>`), or `''` if unset."""
        return self.metadata.style_md5 or ""

    @property
    def protocol(self) -> LayerProtocol | str | None:
        """Bitmap compression protocol (`RATTA_RLE`, `SN_ASA_COMPRESS`, or `None`)."""
        if self.is_layer_supported():
            if not self.layers:
                return None
            # currently MAINLAYER is only supported
            return self.layers[0].metadata.protocol
        return self.metadata.protocol

    @property
    def layer_info(self) -> str | None:
        """Normalized JSON string representation of `<LAYERINFO>`, or `None`."""
        if self.metadata.layer_info is None:
            return None
        return encode_layer_info(self.metadata.layer_info, wire_escape=False)

    @property
    def layer_order(self) -> list[str]:
        """Ordered layer slot names from `<LAYERSEQ>`."""
        return [str(item) for item in self.metadata.layer_seq]

    @property
    def recogn_status(self) -> RecognitionStatus | int:
        """Handwriting recognition status (`RecognitionStatus`)."""
        return self.metadata.recogn_status

    @property
    def orientation(self) -> PageOrientation | str:
        """Page orientation code (`PageOrientation`)."""
        return self.metadata.orientation

    def _layers_by_slot(self) -> dict[str, "Layer"]:
        layers_by_name: dict[str, Layer] = {}
        mainlayer_visited = False
        for layer in self.layers:
            if layer.name is None:
                continue
            name = str(layer.name)
            if mainlayer_visited and name == LayerName.MAINLAYER:
                name = LayerName.BGLAYER.value
            elif name == LayerName.MAINLAYER:
                mainlayer_visited = True
            layers_by_name[name] = layer
        return layers_by_name

    @property
    def layer_visibility(self) -> dict[str, bool]:
        """Layer visibility map keyed by slot name (`MAINLAYER`, `LAYER1`..`3`, `BGLAYER`)."""
        entries = self.metadata.layer_info
        if entries is None:
            return {
                name: layer.layer_type == LayerType.MARK
                for name, layer in self._layers_by_slot().items()
            }
        visibility = {entry.layer_key: entry.is_visible for entry in entries}
        # Some old files don't include MAINLAYER info, so default MAINLAYER to visible.
        if visibility.get(LayerName.MAINLAYER) is None:
            visibility[LayerName.MAINLAYER.value] = True
        return visibility

    @property
    def has_ink(self) -> bool:
        """`True` if any visible foreground layer (or legacy page bitmap) contains non-transparent pixels."""
        if not self.is_layer_supported():
            return _bitmap_has_ink(self.content, self.protocol)
        visibility = self.layer_visibility
        layers_by_name = self._layers_by_slot()
        layer_names = self.layer_order or list(layers_by_name.keys())
        for name in layer_names:
            if name == LayerName.BGLAYER or not visibility.get(name):
                continue
            layer = layers_by_name.get(name)
            if layer is not None and layer.has_ink:
                return True
        return False

    @property
    def has_hidden_ink(self) -> bool:
        """`True` if any hidden foreground layer contains non-transparent pixels."""
        if not self.is_layer_supported():
            return False
        visibility = self.layer_visibility
        layers_by_name = self._layers_by_slot()
        layer_names = self.layer_order or list(layers_by_name.keys())
        for name in layer_names:
            if name == LayerName.BGLAYER or visibility.get(name):
                continue
            layer = layers_by_name.get(name)
            if layer is not None and layer.has_ink:
                return True
        return False

    @property
    def has_textbox(self) -> bool:
        """`True` if this page contains text box data (`<PAGETEXTBOX>` > 0)."""
        return self.metadata.page_textbox_address > 0

    @property
    def has_vector_graph(self) -> bool:
        """`True` if any visible foreground layer references vector graphics data (`<LAYERVECTORGRAPH>` > 0)."""
        if not self.is_layer_supported():
            return False
        visibility = self.layer_visibility
        layers_by_name = self._layers_by_slot()
        layer_names = self.layer_order or list(layers_by_name.keys())
        for name in layer_names:
            if name == LayerName.BGLAYER or not visibility.get(name):
                continue
            layer = layers_by_name.get(name)
            if layer is not None and layer.has_vector_graph:
                return True
        return False

    @property
    def has_drawables(self) -> bool:
        """`True` if this page has visible foreground ink, text boxes, or vector graphics."""
        return self.has_ink or self.has_textbox or self.has_vector_graph

    @property
    def keywords(self) -> list[Keyword]:
        """Keywords anchored to this page."""
        if self._notebook is not None and self._page_index is not None:
            return [
                kw
                for kw in self._notebook.keywords
                if kw.page_number == self._page_index
            ]
        return list(self._keywords)

    @property
    def titles(self) -> list[Title]:
        """Heading/outline entries anchored to this page."""
        if self._notebook is not None and self._page_index is not None:
            return [
                t for t in self._notebook.titles if t.page_number == self._page_index
            ]
        return list(self._titles)

    @property
    def links(self) -> list[Link]:
        """Hyperlink entries anchored to this page."""
        if self._notebook is not None and self._page_index is not None:
            return [
                lk for lk in self._notebook.links if lk.page_number == self._page_index
            ]
        return list(self._links)

    @property
    def has_content(self) -> bool:
        """`True` if this page has foreground drawables or user-authored keywords, titles, or outgoing links."""
        return (
            self.has_drawables
            or bool(self.keywords)
            or bool(self.titles)
            or any(lk.direction == LinkDirection.OUT for lk in self.links)
        )

    def layer(self, number: int) -> "Layer":
        """Return the `Layer` at 0-based `number`."""
        if number < 0 or number >= len(self.layers):
            raise IndexError(f"layer number out of range: {number}")
        return self.layers[number]

    def is_horizontal(self) -> bool:
        """Return `True` if this page is in landscape orientation (`1090` or `1270`)."""
        return self.orientation in (
            self.ORIENTATION_HORIZONTAL,
            self.ORIENTATION_HORIZONTAL_270,
        )

    def is_layer_supported(self) -> bool:
        """Returns True if this page supports layers."""
        return self.metadata.is_layer_supported

    @deprecated("Assign to Page.content instead")
    def set_content(self, content: bytes | None) -> None:
        self.content = content

    @deprecated("Use Page.content instead")
    def get_content(self) -> bytes | None:
        return self.content

    @deprecated("Use Page.layers instead")
    def get_layers(self) -> list["Layer"]:
        return self.layers

    @deprecated("Use Page.layer() or Page.layers instead")
    def get_layer(self, number: int) -> "Layer":
        return self.layer(number)

    @deprecated("Use Page.protocol instead")
    def get_protocol(self) -> str | None:
        protocol = self.protocol
        return str(protocol) if protocol is not None else None

    @deprecated("Use Page.style instead")
    def get_style(self) -> str | None:
        return self.style

    @deprecated("Use Page.style_hash instead")
    def get_style_hash(self) -> str:
        return self.style_hash

    @deprecated("Use Page.layer_info or Page.metadata.layer_info instead")
    def get_layer_info(self) -> str | None:
        return self.layer_info

    @deprecated("Use Page.layer_order instead")
    def get_layer_order(self) -> list[str]:
        return self.layer_order

    @deprecated("Assign to Page.totalpath instead")
    def set_totalpath(self, totalpath: bytes | None) -> None:
        self.totalpath = totalpath

    @deprecated("Use Page.totalpath instead")
    def get_totalpath(self) -> bytes | None:
        return self.totalpath

    @deprecated("Use Page.page_id instead")
    def get_pageid(self) -> str | None:
        return self.page_id

    @deprecated("Use Page.recogn_status instead")
    def get_recogn_status(self) -> int:
        return int(self.recogn_status)

    @deprecated("Assign to Page.recogn_file instead")
    def set_recogn_file(self, recogn_file: bytes | None) -> None:
        self.recogn_file = recogn_file

    @deprecated("Use Page.recogn_file instead")
    def get_recogn_file(self) -> bytes | None:
        return self.recogn_file

    @deprecated("Assign to Page.recogn_text instead")
    def set_recogn_text(self, recogn_text: bytes | None) -> None:
        self.recogn_text = recogn_text

    @deprecated("Use Page.recogn_text instead")
    def get_recogn_text(self) -> bytes | None:
        return self.recogn_text

    @deprecated("Use Page.orientation instead")
    def get_orientation(self) -> str:
        return str(self.orientation)


class Layer:
    """Loaded layer combining `LayerMetadata` and compressed layer bitmap bytes."""

    def __init__(
        self,
        layer_info: LayerMetadata | Mapping[str, Any],
        content: bytes | None = None,
    ) -> None:
        if isinstance(layer_info, LayerMetadata):
            self.metadata = layer_info
        elif isinstance(layer_info, Mapping):
            self.metadata = LayerMetadata.from_params(layer_info)
        else:
            raise exceptions.ParserException("invalid layer metadata")
        self.content: bytes | None = content

    @property
    def name(self) -> LayerName | str | None:
        """Layer slot identifier (`MAINLAYER`, `LAYER1..3`, `BGLAYER`)."""
        return self.metadata.name

    @property
    def protocol(self) -> LayerProtocol | str | None:
        """Bitmap compression protocol (`RATTA_RLE`, `SN_ASA_COMPRESS`)."""
        return self.metadata.protocol

    @property
    def layer_type(self) -> LayerType | str | None:
        """Layer content kind (`NOTE` or `MARK`)."""
        return self.metadata.layer_type

    @property
    def has_ink(self) -> bool:
        """`True` if this layer's compressed bitmap contains any non-transparent pixel."""
        return _bitmap_has_ink(self.content, self.protocol)

    @property
    def has_vector_graph(self) -> bool:
        """`True` if this layer references vector graphics data (`<LAYERVECTORGRAPH>` > 0)."""
        return self.metadata.vector_graph_address > 0

    @deprecated("Assign to Layer.content instead")
    def set_content(self, content: bytes | None) -> None:
        self.content = content

    @deprecated("Use Layer.content instead")
    def get_content(self) -> bytes | None:
        return self.content

    @deprecated("Use Layer.name instead")
    def get_name(self) -> str | None:
        return str(self.name) if self.name is not None else None

    @deprecated("Use Layer.protocol instead")
    def get_protocol(self) -> str | None:
        return str(self.protocol) if self.protocol is not None else None

    @deprecated("Use Layer.layer_type instead")
    def get_type(self) -> str | None:
        return str(self.layer_type) if self.layer_type is not None else None


def _bitmap_has_ink(data: bytes | None, protocol: LayerProtocol | str | None) -> bool:
    """Return `True` if compressed bitmap bytes contain any non-transparent pixel."""
    if not data:
        return False
    if protocol == LayerProtocol.RATTA_RLE:
        return any(
            b != decoder.RattaRleDecoder.COLORCODE_BACKGROUND for b in data[0::2]
        )
    if protocol == LayerProtocol.SN_ASA_COMPRESS:
        try:
            raw = zlib.decompress(data)
        except zlib.error as err:
            raise exceptions.DecoderException(
                f"failed to decompress bitmap: {err}"
            ) from err
        expected_len = (
            decoder.FlateDecoder.INTERNAL_PAGE_WIDTH
            * decoder.FlateDecoder.INTERNAL_PAGE_HEIGHT
            * 2
        )
        pixels = np.frombuffer(raw, dtype=np.uint16)
        if len(raw) == expected_len:
            pixels = pixels.reshape(
                (
                    decoder.FlateDecoder.INTERNAL_PAGE_WIDTH,
                    decoder.FlateDecoder.INTERNAL_PAGE_HEIGHT,
                )
            )[:, :-16]
        return bool(np.any(pixels != decoder.FlateDecoder.COLORCODE_BACKGROUND))
    # Unknown protocol: conservatively treat non-empty bitmap as containing ink.
    return True


__all__ = [
    "A5X2_PAGE_HEIGHT",
    "A5X2_PAGE_WIDTH",
    "ADDRESS_SIZE",
    "KEY_FOOTER",
    "KEY_HEADER",
    "KEY_KEYWORDS",
    "KEY_LAYERS",
    "KEY_LINKS",
    "KEY_PAGES",
    "KEY_SIGNATURE",
    "KEY_TITLES",
    "KEY_TYPE",
    "LENGTH_FIELD_SIZE",
    "PAGE_HEIGHT",
    "PAGE_WIDTH",
    "Cover",
    "Keyword",
    "Layer",
    "Link",
    "Notebook",
    "Page",
    "ParamsBlock",
    "SupernoteMetadata",
    "Title",
]
