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

from collections.abc import Mapping
from typing import Any

from . import exceptions
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
        if not isinstance(metadata, SupernoteMetadata):
            raise exceptions.ParserException("notebook metadata is missing")
        self.metadata = metadata
        self.loaded_page_number = page_number
        self.page_width = PAGE_WIDTH
        self.page_height = PAGE_HEIGHT
        if self.metadata.header.apply_equipment == EquipmentType.N5:
            self.page_width = A5X2_PAGE_WIDTH
            self.page_height = A5X2_PAGE_HEIGHT
        self.type: str = metadata.type
        self.signature: str = metadata.signature
        self.cover = Cover()
        self.keywords: list[Keyword] = [Keyword(k) for k in metadata.footer.keywords]
        self.titles: list[Title] = [Title(t) for t in metadata.footer.titles]
        self.links: list[Link] = [Link(link) for link in metadata.footer.links]
        self.pages: list[Page] = []
        for page_info in metadata.pages:
            if not isinstance(page_info, PageMetadata):
                raise exceptions.ParserException("invalid page metadata entry")
            self.pages.append(Page(page_info))

    def get_metadata(self) -> SupernoteMetadata:
        if not isinstance(self.metadata, SupernoteMetadata):
            raise exceptions.ParserException("notebook metadata is missing")
        return self.metadata

    def get_width(self) -> int:
        return self.page_width

    def get_height(self) -> int:
        return self.page_height

    def get_type(self) -> str:
        return self.type

    def get_signature(self) -> str:
        return self.signature

    def get_total_pages(self) -> int:
        return len(self.pages)

    def get_page(self, number: int) -> "Page":
        if number < 0 or number >= len(self.pages):
            raise IndexError(f"page number out of range: {number}")
        if self.loaded_page_number is not None and number != self.loaded_page_number:
            raise ValueError(
                f"Notebook was loaded with only page_number={self.loaded_page_number}; cannot access page {number}"
            )
        return self.pages[number]

    def get_cover(self) -> "Cover":
        return self.cover

    def get_keywords(self) -> list["Keyword"]:
        return self.keywords

    def get_titles(self) -> list["Title"]:
        return self.titles

    def get_links(self) -> list["Link"]:
        return self.links

    def get_fileid(self) -> str | None:
        return self.metadata.header.file_id

    def is_realtime_recognition(self) -> bool:
        return self.metadata.header.file_recogn_type == 1

    def supports_highres_grayscale(self) -> bool:
        if len(self.signature) < 8 or not self.signature[-8:].isdigit():
            return False
        return int(self.signature[-8:]) >= 20230015


class Cover:
    """Loaded cover bitmap container."""

    def __init__(self, content: bytes | None = None) -> None:
        self.content: bytes | None = content

    def set_content(self, content: bytes | None) -> None:
        self.content = content

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
        self.page_number = self.metadata.page_index

    def set_content(self, content: bytes | None) -> None:
        self.content = content

    def get_content(self) -> bytes | None:
        return self.content

    def get_page_number(self) -> int:
        return self.page_number

    def get_position_string(self) -> str:
        if self.metadata.rect_original is None:
            raise exceptions.ParserException(
                "missing KEYWORDRECTORI in keyword metadata"
            )
        return f"{self.metadata.rect_original.top:04d}"

    def get_keyword(self) -> str | None:
        return self.metadata.keyword

    def get_rect(self) -> tuple[int, int, int, int]:
        if self.metadata.rect is None:
            raise exceptions.ParserException("missing KEYWORDRECT in keyword metadata")
        return self.metadata.rect.bbox


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
        self.page_number = self.metadata.page_index

    def set_content(self, content: bytes | None) -> None:
        self.content = content

    def get_content(self) -> bytes | None:
        return self.content

    def set_page_number(self, page_number: int) -> None:
        self.page_number = page_number
        self.metadata.page_index = page_number

    def get_page_number(self) -> int:
        return self.page_number

    def get_position_string(self) -> str:
        if self.metadata.rect_original is None:
            raise exceptions.ParserException("missing TITLERECTORI in title metadata")
        return (
            f"{self.metadata.rect_original.top:04d}"
            f"{self.metadata.rect_original.left:04d}"
        )


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
        self.page_number = self.metadata.page_index

    def set_content(self, content: bytes | None) -> None:
        self.content = content

    def get_content(self) -> bytes | None:
        return self.content

    def set_page_number(self, page_number: int) -> None:
        self.page_number = page_number
        self.metadata.page_index = page_number

    def get_page_number(self) -> int:
        return self.page_number

    def get_type(self) -> int:
        return int(self.metadata.link_type)

    def get_inout(self) -> int:
        return int(self.metadata.direction)

    def get_position_string(self) -> str:
        if self.metadata.rect is None:
            raise exceptions.ParserException("missing LINKRECT in link metadata")
        rect = self.metadata.rect
        return f"{rect.top:04d}{rect.left:04d}{rect.height:04d}{rect.width:04d}"

    def get_rect(self) -> tuple[int, int, int, int]:
        if self.metadata.rect is None:
            raise exceptions.ParserException("missing LINKRECT in link metadata")
        return self.metadata.rect.bbox

    def get_timestamp(self) -> str | None:
        return self.metadata.timestamp

    def get_filepath(self) -> str | None:
        return self.metadata.file_path  # Base64-encoded file path or URL

    def get_fileid(self) -> str | None:
        return self.metadata.file_id

    def get_pageid(self) -> str | None:
        return self.metadata.page_id


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
        self.layers: list[Layer] = [
            Layer(layer_meta) for layer_meta in (self.metadata.layers or [])
        ]

    def is_horizontal(self) -> bool:
        return self.get_orientation() in (
            self.ORIENTATION_HORIZONTAL,
            self.ORIENTATION_HORIZONTAL_270,
        )

    def set_content(self, content: bytes | None) -> None:
        self.content = content

    def get_content(self) -> bytes | None:
        return self.content

    def is_layer_supported(self) -> bool:
        """Returns True if this page supports layers."""
        return self.metadata.is_layer_supported

    def get_layers(self) -> list["Layer"]:
        return self.layers

    def get_layer(self, number: int) -> "Layer":
        if number < 0 or number >= len(self.layers):
            raise IndexError(f"layer number out of range: {number}")
        return self.layers[number]

    def get_protocol(self) -> str | None:
        if self.is_layer_supported():
            if not self.layers:
                return None
            # currently MAINLAYER is only supported
            protocol = self.layers[0].metadata.protocol
        else:
            protocol = self.metadata.protocol
        return str(protocol) if protocol is not None else None

    def get_style(self) -> str | None:
        return self.metadata.style

    def get_style_hash(self) -> str:
        return self.metadata.style_md5 or ""

    def get_layer_info(self) -> str | None:
        if self.metadata.layer_info is None:
            return None
        return encode_layer_info(self.metadata.layer_info, wire_escape=False)

    def get_layer_order(self) -> list[str]:
        return [str(item) for item in self.metadata.layer_seq]

    def set_totalpath(self, totalpath: bytes | None) -> None:
        self.totalpath = totalpath

    def get_totalpath(self) -> bytes | None:
        return self.totalpath

    def get_pageid(self) -> str | None:
        return self.metadata.page_id

    def get_recogn_status(self) -> int:
        return int(self.metadata.recogn_status)

    def set_recogn_file(self, recogn_file: bytes | None) -> None:
        self.recogn_file = recogn_file

    def get_recogn_file(self) -> bytes | None:
        return self.recogn_file

    def set_recogn_text(self, recogn_text: bytes | None) -> None:
        self.recogn_text = recogn_text

    def get_recogn_text(self) -> bytes | None:
        return self.recogn_text

    def get_orientation(self) -> str:
        return str(self.metadata.orientation)


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

    def set_content(self, content: bytes | None) -> None:
        self.content = content

    def get_content(self) -> bytes | None:
        return self.content

    def get_name(self) -> str | None:
        return str(self.metadata.name) if self.metadata.name is not None else None

    def get_protocol(self) -> str | None:
        return (
            str(self.metadata.protocol) if self.metadata.protocol is not None else None
        )

    def get_type(self) -> str | None:
        return (
            str(self.metadata.layer_type)
            if self.metadata.layer_type is not None
            else None
        )


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
