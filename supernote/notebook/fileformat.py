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

"""Classes for Suernote file format.

The Supernote file format relies on a "Footer-first" parsing strategy.
The last 4 bytes of the file (the "Tail") contain the offset to the Footer Block.
The Footer Block then contains references (offsets) to all other metadata blocks
(Pages, Titles, Keywords, etc.) and the Header Block.
"""

import json
from typing import Any

from . import exceptions

ParamsBlock = dict[str, Any]

#### Constants

PAGE_HEIGHT = 1872
PAGE_WIDTH = 1404
A5X2_PAGE_HEIGHT = 2560
A5X2_PAGE_WIDTH = 1920


ADDRESS_SIZE = 4
LENGTH_FIELD_SIZE = 4

KEY_TYPE = "__type__"
KEY_SIGNATURE = "__signature__"
KEY_HEADER = "__header__"
KEY_FOOTER = "__footer__"
KEY_PAGES = "__pages__"
KEY_LAYERS = "__layers__"
KEY_KEYWORDS = "__keywords__"
KEY_TITLES = "__titles__"
KEY_LINKS = "__links__"


class SupernoteMetadata:
    """Represents Supernote file structure."""

    def __init__(
        self,
        type: str,
        signature: str,
        header: ParamsBlock,
        footer: ParamsBlock,
        pages: list[ParamsBlock],
    ) -> None:
        self.__note: dict[str, Any] = {}
        self.type = type
        self.signature = signature
        self.header = header
        self.footer = footer
        self.pages = pages

    @property
    def type(self) -> str:
        return self.__note[KEY_TYPE]

    @type.setter
    def type(self, value: str) -> None:
        if not isinstance(value, str):
            raise exceptions.ParserException("notebook metadata type is missing")
        self.__note[KEY_TYPE] = value

    @property
    def signature(self) -> str:
        return self.__note[KEY_SIGNATURE]

    @signature.setter
    def signature(self, value: str) -> None:
        if not isinstance(value, str):
            raise exceptions.ParserException("notebook metadata signature is missing")
        self.__note[KEY_SIGNATURE] = value

    @property
    def header(self) -> ParamsBlock:
        return self.__note[KEY_HEADER]

    @header.setter
    def header(self, value: ParamsBlock) -> None:
        if not isinstance(value, dict):
            raise exceptions.ParserException("notebook metadata header is missing")
        self.__note[KEY_HEADER] = value

    @property
    def footer(self) -> ParamsBlock:
        return self.__note[KEY_FOOTER]

    @footer.setter
    def footer(self, value: ParamsBlock) -> None:
        if not isinstance(value, dict):
            raise exceptions.ParserException("notebook metadata footer is missing")
        self.__note[KEY_FOOTER] = value

    @property
    def pages(self) -> list[ParamsBlock]:
        return self.__note[KEY_PAGES]

    @pages.setter
    def pages(self, value: list[ParamsBlock]) -> None:
        if not isinstance(value, list):
            raise exceptions.ParserException("notebook metadata pages are missing")
        self.__note[KEY_PAGES] = value

    def get_total_pages(self) -> int:
        """Returns total page number.

        Returns
        -------
        int
            total page number
        """
        return len(self.pages)

    def is_layer_supported(self, page_number: int) -> bool:
        """Returns true if the page supports layer.

        Parameters
        ----------
        page_number : int
            page number to check

        Returns
        -------
        bool
            true if the page supports layer.
        """
        if page_number < 0 or page_number >= self.get_total_pages():
            raise IndexError(f"page number out of range: {page_number}")
        return self.pages[page_number].get(KEY_LAYERS) is not None

    def to_json(self, indent: int | None = None) -> str:
        """Returns file structure as JSON format string.

        Parameters
        ----------
        indent : int
            optional indent level

        Returns
        -------
        str
            JSON format string
        """
        return json.dumps(self.__note, indent=indent, ensure_ascii=False)


class Notebook:
    def __init__(
        self, metadata: SupernoteMetadata, page_number: int | None = None
    ) -> None:
        if not isinstance(metadata, SupernoteMetadata):
            raise exceptions.ParserException("notebook metadata is missing")
        self.metadata = metadata
        self.loaded_page_number = page_number
        self.page_width = PAGE_WIDTH
        self.page_height = PAGE_HEIGHT
        if self.metadata.header.get("APPLY_EQUIPMENT") == "N5":
            self.page_width = A5X2_PAGE_WIDTH
            self.page_height = A5X2_PAGE_HEIGHT
        self.type: str = metadata.type
        self.signature: str = metadata.signature
        self.cover = Cover()
        self.keywords: list[Keyword] = []
        keywords = metadata.footer.get(KEY_KEYWORDS)
        if isinstance(keywords, list):
            for k in keywords:
                self.keywords.append(Keyword(k))
        self.titles: list[Title] = []
        titles = metadata.footer.get(KEY_TITLES)
        if isinstance(titles, list):
            for t in titles:
                self.titles.append(Title(t))
        self.links: list[Link] = []
        links = metadata.footer.get(KEY_LINKS)
        if isinstance(links, list):
            for link in links:
                self.links.append(Link(link))
        self.pages: list[Page] = []
        for page_info in metadata.pages:
            if not isinstance(page_info, dict):
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
        file_id = self.metadata.header.get("FILE_ID")
        return file_id if isinstance(file_id, str) else None

    def is_realtime_recognition(self) -> bool:
        return self.metadata.header.get("FILE_RECOGN_TYPE") == "1"

    def supports_highres_grayscale(self) -> bool:
        if len(self.signature) < 8 or not self.signature[-8:].isdigit():
            return False
        return int(self.signature[-8:]) >= 20230015


class Cover:
    def __init__(self) -> None:
        self.content: bytes | None = None

    def set_content(self, content: bytes | None):
        self.content = content

    def get_content(self) -> bytes | None:
        return self.content


class Keyword:
    def __init__(self, keyword_info: ParamsBlock) -> None:
        if not isinstance(keyword_info, dict):
            raise exceptions.ParserException("invalid keyword metadata")
        self.metadata = keyword_info
        self.content: bytes | None = None
        raw_page = self.metadata.get("KEYWORDPAGE")
        if not isinstance(raw_page, (str, int)):
            raise exceptions.ParserException("missing KEYWORDPAGE in keyword metadata")
        try:
            self.page_number = int(raw_page) - 1
        except ValueError as exc:
            raise exceptions.ParserException(
                f"invalid KEYWORDPAGE in keyword metadata: {raw_page!r}"
            ) from exc

    def set_content(self, content: bytes | None):
        self.content = content

    def get_content(self) -> bytes | None:
        return self.content

    def get_page_number(self) -> int:
        return self.page_number

    def get_position_string(self) -> str:
        (left, top, width, height) = self.metadata["KEYWORDRECTORI"].split(",")
        return f"{int(top):04d}"

    def get_keyword(self) -> str | None:
        return (
            None if self.metadata["KEYWORD"] is None else str(self.metadata["KEYWORD"])
        )

    def get_rect(self) -> tuple[int, int, int, int]:
        (left, top, width, height) = self.metadata["KEYWORDRECT"].split(",")
        return (int(left), int(top), int(left) + int(width), int(top) + int(height))


class Title:
    def __init__(self, title_info: dict[str, str]) -> None:
        self.metadata = title_info
        self.content: bytes | None = None
        self.page_number = 0

    def set_content(self, content: bytes | None):
        self.content = content

    def get_content(self) -> bytes | None:
        return self.content

    def set_page_number(self, page_number: int) -> None:
        self.page_number = page_number

    def get_page_number(self) -> int:
        return self.page_number

    def get_position_string(self) -> str:
        (left, top, width, height) = self.metadata["TITLERECTORI"].split(",")
        return f"{int(top):04d}{int(left):04d}"


class Link:
    # Link Types
    TYPE_PAGE_LINK = 0  # Internal link to another page
    TYPE_FILE_LINK = 1  # Link to another file
    TYPE_WEB_LINK = 4  # External web link

    # Link Direction
    DIRECTION_OUT = 0  # Outgoing link (from this page)
    DIRECTION_IN = 1  # Incoming link (to this page)

    def __init__(self, link_info: dict[str, str]) -> None:
        self.metadata = link_info
        self.content: bytes | None = None
        self.page_number = 0

    def set_content(self, content: bytes | None):
        self.content = content

    def get_content(self) -> bytes | None:
        return self.content

    def set_page_number(self, page_number: int) -> None:
        self.page_number = page_number

    def get_page_number(self) -> int:
        return self.page_number

    def get_type(self) -> int:
        return int(self.metadata["LINKTYPE"])

    def get_inout(self) -> int:
        return int(self.metadata["LINKINOUT"])

    def get_position_string(self) -> str:
        (left, top, width, height) = self.metadata["LINKRECT"].split(",")
        return f"{int(top):04d}{int(left):04d}{int(height):04d}{int(width):04d}"

    def get_rect(self) -> tuple[int, int, int, int]:
        (left, top, width, height) = self.metadata["LINKRECT"].split(",")
        return (int(left), int(top), int(left) + int(width), int(top) + int(height))

    def get_timestamp(self) -> str:
        return self.metadata["LINKTIMESTAMP"]

    def get_filepath(self) -> str:
        return self.metadata["LINKFILE"]  # Base64-encoded file path or URL

    def get_fileid(self) -> str | None:
        return (
            None
            if self.metadata["LINKFILEID"] == "none"
            else self.metadata["LINKFILEID"]
        )

    def get_pageid(self) -> str | None:
        return None if self.metadata["PAGEID"] == "none" else self.metadata["PAGEID"]


class Page:
    # Recognition Status
    RECOGNSTATUS_NONE = 0  # No recognition performed
    RECOGNSTATUS_DONE = 1  # Recognition complete (RECOGNTEXT available)
    RECOGNSTATUS_RUNNING = 2  # Recognition in progress

    # Orientation
    ORIENTATION_VERTICAL = "1000"  # Portrait
    ORIENTATION_HORIZONTAL = "1090"  # Landscape
    ORIENTATION_VERTICAL_180 = "1180"  # Portrait flipped
    ORIENTATION_HORIZONTAL_270 = "1270"  # Landscape flipped

    def is_horizontal(self) -> bool:
        return self.get_orientation() in (
            self.ORIENTATION_HORIZONTAL,
            self.ORIENTATION_HORIZONTAL_270,
        )

    def __init__(self, page_info: ParamsBlock) -> None:
        if not isinstance(page_info, dict):
            raise exceptions.ParserException("invalid page metadata")
        self.metadata = page_info
        self.content: bytes | None = None
        self.totalpath: bytes | None = None
        self.recogn_file: bytes | None = None
        self.recogn_text: bytes | None = None
        self.layers: list[Layer] = []
        layers = page_info.get(KEY_LAYERS)
        if isinstance(layers, list):
            for layer_info in layers:
                if not isinstance(layer_info, dict):
                    raise exceptions.ParserException("invalid layer metadata")
                self.layers.append(Layer(layer_info))

    def set_content(self, content: bytes | None) -> None:
        self.content = content

    def get_content(self) -> bytes | None:
        return self.content

    def is_layer_supported(self) -> bool:
        """Returns True if this page supports layer.

        Returns
        -------
        bool
            True if this page supports layer.
        """
        return self.metadata.get(KEY_LAYERS) is not None

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
            protocol = self.get_layer(0).metadata.get("LAYERPROTOCOL")
        else:
            protocol = self.metadata.get("PROTOCOL")
        return protocol if isinstance(protocol, str) else None

    def get_style(self) -> str | None:
        style = self.metadata.get("PAGESTYLE")
        return style if isinstance(style, str) else None

    def get_style_hash(self) -> str:
        hashcode = self.metadata.get("PAGESTYLEMD5")
        if not isinstance(hashcode, str) or hashcode == "0":
            return ""
        return hashcode

    def get_layer_info(self) -> str | None:
        info = self.metadata.get("LAYERINFO")
        if not isinstance(info, str) or info == "none":
            return None
        return info.replace("#", ":")

    def get_layer_order(self) -> list[str]:
        seq = self.metadata.get("LAYERSEQ")
        if not isinstance(seq, str):
            return []
        return seq.split(",")

    def set_totalpath(self, totalpath: bytes | None) -> None:
        self.totalpath = totalpath

    def get_totalpath(self) -> bytes | None:
        return self.totalpath

    def get_pageid(self) -> str | None:
        page_id = self.metadata.get("PAGEID")
        return page_id if isinstance(page_id, str) else None

    def get_recogn_status(self) -> int:
        status = self.metadata.get("RECOGNSTATUS")
        if status is None:
            return self.RECOGNSTATUS_NONE
        if not isinstance(status, (str, int)):
            raise exceptions.ParserException(f"invalid page RECOGNSTATUS: {status!r}")
        try:
            return int(status)
        except ValueError as exc:
            raise exceptions.ParserException(
                f"invalid page RECOGNSTATUS: {status!r}"
            ) from exc

    def set_recogn_file(self, recogn_file):
        self.recogn_file = recogn_file

    def get_recogn_file(self):
        return self.recogn_file

    def set_recogn_text(self, recogn_text):
        self.recogn_text = recogn_text

    def get_recogn_text(self):
        return self.recogn_text

    def get_orientation(self):
        return self.metadata.get("ORIENTATION", self.ORIENTATION_VERTICAL)


class Layer:
    def __init__(self, layer_info):
        self.metadata = layer_info
        self.content = None

    def set_content(self, content):
        self.content = content

    def get_content(self):
        return self.content

    def get_name(self):
        return self.metadata.get("LAYERNAME")

    def get_protocol(self):
        return self.metadata.get("LAYERPROTOCOL")

    def get_type(self):
        return self.metadata.get("LAYERTYPE")
