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

ParamsBlock = dict[str, str | list[str]]

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

    def __init__(self) -> None:
        self.__note = {
            KEY_TYPE: None,
            KEY_SIGNATURE: None,
            KEY_HEADER: None,
            KEY_FOOTER: None,
            KEY_PAGES: None,
        }

    @property
    def type(self) -> str | None:
        return self.__note[KEY_TYPE]

    @type.setter
    def type(self, value: str | None):
        self.__note[KEY_TYPE] = value

    @property
    def signature(self) -> str | None:
        return self.__note[KEY_SIGNATURE]

    @signature.setter
    def signature(self, value: str | None):
        self.__note[KEY_SIGNATURE] = value

    @property
    def header(self) -> dict[str, str] | None:
        return self.__note[KEY_HEADER]

    @header.setter
    def header(self, value: dict[str, str] | None):
        self.__note[KEY_HEADER] = value

    @property
    def footer(self) -> dict[str, str] | None:
        return self.__note[KEY_FOOTER]

    @footer.setter
    def footer(self, value: dict[str, str] | None):
        self.__note[KEY_FOOTER] = value

    @property
    def pages(self) -> list[ParamsBlock] | None:
        return self.__note[KEY_PAGES]

    @pages.setter
    def pages(self, value: list[ParamsBlock] | None):
        self.__note[KEY_PAGES] = value

    def get_total_pages(self) -> int:
        """Returns total page number.

        Returns
        -------
        int
            total page number
        """
        return len(self.__note[KEY_PAGES])

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
        return self.__note[KEY_PAGES][page_number].get(KEY_LAYERS) is not None

    def to_json(self, indent: int = None) -> str:
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
    def __init__(self, metadata: SupernoteMetadata) -> None:
        self.metadata = metadata
        self.page_width = PAGE_WIDTH
        self.page_height = PAGE_HEIGHT
        if self.metadata.header.get("APPLY_EQUIPMENT") == "N5":
            self.page_width = A5X2_PAGE_WIDTH
            self.page_height = A5X2_PAGE_HEIGHT
        self.type = metadata.type
        self.signature = metadata.signature
        self.cover = Cover()
        self.keywords: list[Keyword] = []
        has_keywords = metadata.footer.get(KEY_KEYWORDS) is not None
        if has_keywords:
            for k in metadata.footer.get(KEY_KEYWORDS):
                self.keywords.append(Keyword(k))
        self.titles: list[Title] = []
        has_titles = metadata.footer.get(KEY_TITLES) is not None
        if has_titles:
            for t in metadata.footer.get(KEY_TITLES):
                self.titles.append(Title(t))
        self.links: list[Link] = []
        has_links = metadata.footer.get(KEY_LINKS) is not None
        if has_links:
            for link in metadata.footer.get(KEY_LINKS):
                self.links.append(Link(link))
        self.pages: list[Page] = []
        total = metadata.get_total_pages()
        for i in range(total):
            self.pages.append(Page(metadata.pages[i]))

    def get_metadata(self) -> SupernoteMetadata:
        return self.metadata

    def get_width(self) -> int:
        return self.page_width

    def get_height(self) -> int:
        return self.page_height

    def get_type(self) -> str | None:
        return self.type

    def get_signature(self) -> str | None:
        return self.signature

    def get_total_pages(self) -> int:
        return len(self.pages)

    def get_page(self, number: int) -> "Page":
        if number < 0 or number >= len(self.pages):
            raise IndexError(f"page number out of range: {number}")
        return self.pages[number]

    def get_cover(self) -> "Cover":
        return self.cover

    def get_keywords(self) -> list["Keyword"]:
        return self.keywords

    def get_titles(self) -> list["Title"]:
        return self.titles

    def get_links(self):
        return self.links

    def get_fileid(self):
        return self.metadata.header.get("FILE_ID")

    def is_realtime_recognition(self):
        return self.metadata.header.get("FILE_RECOGN_TYPE") == "1"

    def supports_highres_grayscale(self):
        return int(self.signature[-8:]) >= 20230015


class Cover:
    def __init__(self) -> None:
        self.content: bytes | None = None

    def set_content(self, content: bytes | None):
        self.content = content

    def get_content(self) -> bytes | None:
        return self.content


class Keyword:
    def __init__(self, keyword_info: dict[str, str]) -> None:
        self.metadata = keyword_info
        self.content: bytes | None = None
        self.page_number = int(self.metadata["KEYWORDPAGE"]) - 1

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

    def __init__(self, page_info: ParamsBlock) -> None:
        self.metadata = page_info
        self.content: bytes | None = None
        self.totalpath = None
        self.recogn_file = None
        self.recogn_text = None
        self.layers: list[Layer] = []
        layer_supported = page_info.get(KEY_LAYERS) is not None
        if layer_supported:
            for i in range(5):
                self.layers.append(Layer(self.metadata[KEY_LAYERS][i]))

    def set_content(self, content: bytes) -> None:
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

    def get_layers(self):
        return self.layers

    def get_layer(self, number):
        if number < 0 or number >= len(self.layers):
            raise IndexError(f"layer number out of range: {number}")
        return self.layers[number]

    def get_protocol(self):
        if self.is_layer_supported():
            # currently MAINLAYER is only supported
            protocol = self.get_layer(0).metadata.get("LAYERPROTOCOL")
        else:
            protocol = self.metadata.get("PROTOCOL")
        return protocol

    def get_style(self):
        return self.metadata.get("PAGESTYLE")

    def get_style_hash(self):
        hashcode = self.metadata.get("PAGESTYLEMD5")
        if hashcode == "0":
            return ""
        return hashcode

    def get_layer_info(self):
        info = self.metadata.get("LAYERINFO")
        if info is None or info == "none":
            return None
        return info.replace("#", ":")

    def get_layer_order(self):
        seq = self.metadata.get("LAYERSEQ")
        if seq is None:
            return []
        order = seq.split(",")
        return order

    def set_totalpath(self, totalpath):
        self.totalpath = totalpath

    def get_totalpath(self):
        return self.totalpath

    def get_pageid(self):
        return self.metadata.get("PAGEID")

    def get_recogn_status(self):
        return int(self.metadata.get("RECOGNSTATUS"))

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
