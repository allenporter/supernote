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

"""Parser classes."""

import os
import re
from typing import Protocol

from . import exceptions, fileformat

ParamsBlock = fileformat.ParamsBlock


class FileObj(Protocol):
    """Protocol for file-like object."""

    def seek(self, offset: int, whence: int = 0, /) -> int:
        """Seeks to the given offset."""
        ...

    def read(self, size: int = -1, /) -> bytes:
        """Reads bytes from the stream."""
        ...


def parse_metadata(stream: FileObj, policy="strict") -> fileformat.SupernoteMetadata:
    """Parses a supernote binary stream and returns metadata object.

    Policy:
    - 'strict': raise exception for unknown signature (default)
    - 'loose': try to parse for unknown signature

    Parameters
    ----------
    stream : file-like object
        supernote binary stream
    policy : str
        signature check policy

    Returns
    -------
    SupernoteMetadata
        metadata object
    """
    try:
        parser = SupernoteXParser()
        metadata = parser.parse_stream(stream, policy)
    except exceptions.UnsupportedFileFormat:
        # ignore this exception and try next parser
        pass
    else:
        return metadata

    try:
        parser = SupernoteParser()
        metadata = parser.parse_stream(stream, policy)
    except exceptions.UnsupportedFileFormat:
        # ignore this exception and try next parser
        pass
    else:
        return metadata

    # we cannot parse the file with any our parser.
    raise exceptions.UnsupportedFileFormat("unsupported file format")


def load(
    stream: FileObj,
    metadata: fileformat.SupernoteMetadata | None = None,
    policy: str = "strict",
    page_number: int | None = None,
) -> fileformat.Notebook:
    """Creates a Notebook object from the supernote binary stream.

     Policy:
     - 'strict': raise exception for unknown signature (default)
     - 'loose': try to parse for unknown signature

    Parameters
     ----------
     stream : file-like object
         supernote binary stream
     metadata : SupernoteMetadata
         metadata object
     policy : str
         signature check policy
     page_number : int | None
         optional single page index to load instead of all pages

     Returns
     -------
     Notebook
         notebook object
    """
    if metadata is None:
        metadata = parse_metadata(stream, policy)

    total_pages = metadata.get_total_pages()
    if page_number is not None and (page_number < 0 or page_number >= total_pages):
        raise ValueError(
            f"page_number {page_number} out of range (0..{total_pages - 1})"
        )

    note = fileformat.Notebook(metadata, page_number=page_number)

    if page_number is not None:
        page_indices = [page_number]
    else:
        cover_address = _get_cover_address(metadata)
        if cover_address > 0:
            content = _get_content_at_address(stream, cover_address)
            note.get_cover().set_content(content)
        # store keyword data to notebook object
        for keyword in note.get_keywords():
            address = _get_keyword_address(keyword)
            content = _get_content_at_address(stream, address)
            keyword.set_content(content)
        # store title data to notebook object
        page_numbers = _get_page_number_from_footer_property(
            note.get_metadata().footer, "TITLE_"
        )
        for i, title in enumerate(note.get_titles()):
            address = _get_title_address(title)
            content = _get_content_at_address(stream, address)
            title.set_content(content)
            title.set_page_number(page_numbers[i])
        # store link data to notebook object
        page_numbers = _get_page_number_from_footer_property(
            note.get_metadata().footer, "LINK"
        )
        for i, link in enumerate(note.get_links()):
            address = _get_link_address(link)
            content = _get_content_at_address(stream, address)
            link.set_content(content)
            link.set_page_number(page_numbers[i])
        page_indices = list(range(metadata.get_total_pages()))

    for p in page_indices:
        addresses = _get_bitmap_address(metadata, p)
        if len(addresses) == 1:  # the page has no layers
            content = _get_content_at_address(stream, addresses[0])
            note.get_page(p).set_content(content)
        else:
            for layer, addr in enumerate(addresses):
                content = _get_content_at_address(stream, addr)
                note.get_page(p).get_layer(layer).set_content(content)
        if page_number is None:
            # store path data to notebook object
            totalpath_address = _get_totalpath_address(metadata, p)
            if totalpath_address > 0:
                content = _get_content_at_address(stream, totalpath_address)
                note.get_page(p).set_totalpath(content)
            # store recogn file data to notebook object
            recogn_file_address = _get_recogn_file_address(metadata, p)
            if recogn_file_address > 0:
                content = _get_content_at_address(stream, recogn_file_address)
                note.get_page(p).set_recogn_file(content)
        # store recogn text data to notebook object
        recogn_text_address = _get_recogn_text_address(metadata, p)
        if recogn_text_address > 0:
            content = _get_content_at_address(stream, recogn_text_address)
            note.get_page(p).set_recogn_text(content)
    return note


def load_notebook(
    file_name: str | os.PathLike[str],
    metadata: fileformat.SupernoteMetadata | None = None,
    policy: str = "strict",
    page_number: int | None = None,
) -> fileformat.Notebook:
    """Creates a Notebook object from the supernote file.

     Policy:
     - 'strict': raise exception for unknown signature (default)
     - 'loose': try to parse for unknown signature

    Parameters
     ----------
     file_name : str
         file path string
     metadata : SupernoteMetadata
         metadata object
     policy : str
         signature check policy
     page_number : int | None
         optional single page index to load instead of all pages

     Returns
     -------
     Notebook
         notebook object
    """
    with open(file_name, "rb") as f:
        note = load(f, metadata, policy, page_number=page_number)
    return note


def _get_content_at_address(fobj: FileObj, address: int) -> bytes | None:
    if address == 0:
        return None
    if address < 0:
        raise exceptions.ParserException(f"invalid negative block address: {address}")
    stream_end = fobj.seek(0, os.SEEK_END)
    if address + fileformat.LENGTH_FIELD_SIZE > stream_end:
        raise exceptions.ParserException(
            f"unexpected EOF reading block length at address {address}"
        )
    fobj.seek(address, os.SEEK_SET)
    length_bytes = fobj.read(fileformat.LENGTH_FIELD_SIZE)
    block_length = int.from_bytes(length_bytes, "little")
    remaining_bytes = stream_end - (address + fileformat.LENGTH_FIELD_SIZE)
    if block_length > remaining_bytes:
        raise exceptions.ParserException(
            f"block length {block_length} at address {address} exceeds remaining stream size {remaining_bytes}"
        )
    return fobj.read(block_length)


def _parse_int_value(value: object, field_name: str) -> int:
    if not isinstance(value, (str, int)):
        raise exceptions.ParserException(
            f"missing or invalid integer parameter {field_name!r}"
        )
    try:
        return int(value)
    except ValueError as exc:
        raise exceptions.ParserException(
            f"invalid integer parameter {field_name!r}: {value!r}"
        ) from exc


def _parse_address_list(params: ParamsBlock, key: str) -> list[int]:
    raw = params.get(key)
    if raw is None:
        raise exceptions.ParserException(f"missing address parameter {key!r}")
    if isinstance(raw, list):
        return [_parse_int_value(item, key) for item in raw]
    return [_parse_int_value(raw, key)]


def _get_cover_address(metadata: fileformat.SupernoteMetadata) -> int:
    """Returns cover address.

    Returns
    -------
    int
        cover address
    """
    if "COVER_2" in metadata.footer:
        return _parse_int_value(metadata.footer["COVER_2"], "COVER_2")
    if "COVER_1" in metadata.footer:
        return _parse_int_value(metadata.footer["COVER_1"], "COVER_1")
    return 0


def _get_keyword_address(keyword: fileformat.Keyword) -> int:
    """Returns keyword content address.

    Returns
    -------
    int
        keyword content address
    """
    return _parse_int_value(keyword.metadata.get("KEYWORDSITE"), "KEYWORDSITE")


def _get_title_address(title: fileformat.Title) -> int:
    """Returns title content address.

    Returns
    -------
    int
        title content address
    """
    return _parse_int_value(title.metadata.get("TITLEBITMAP"), "TITLEBITMAP")


def _get_link_address(link: fileformat.Link) -> int:
    """Returns link content address.

    Returns
    -------
    int
        link content address
    """
    return _parse_int_value(link.metadata.get("LINKBITMAP"), "LINKBITMAP")


def _get_bitmap_address(
    metadata: fileformat.SupernoteMetadata, page_number: int
) -> list[int]:
    """Returns bitmap address of the given page number.

    Returns
    -------
    list of int
        bitmap address
    """
    page_info = metadata.pages[page_number]
    if metadata.is_layer_supported(page_number):
        layers = page_info.get(fileformat.KEY_LAYERS)
        if not isinstance(layers, list):
            raise exceptions.ParserException("invalid page layers metadata")
        addresses: list[int] = []
        for layer_info in layers:
            if not isinstance(layer_info, dict):
                raise exceptions.ParserException("invalid layer metadata entry")
            address = layer_info.get("LAYERBITMAP")
            addresses.append(
                0 if address is None else _parse_int_value(address, "LAYERBITMAP")
            )
        return addresses
    return [_parse_int_value(page_info.get("DATA"), "DATA")]


def _get_totalpath_address(
    metadata: fileformat.SupernoteMetadata, page_number: int
) -> int:
    """Returns total path address of the given page number.

    Returns
    -------
    int
        total path address
    """
    page_info = metadata.pages[page_number]
    if "TOTALPATH" in page_info:
        return _parse_int_value(page_info["TOTALPATH"], "TOTALPATH")
    return 0


def _get_recogn_file_address(
    metadata: fileformat.SupernoteMetadata, page_number: int
) -> int:
    """Returns recogn file address of the given page number.

    Returns
    -------
    int
        recogn file address
    """
    page_info = metadata.pages[page_number]
    if "RECOGNFILE" in page_info:
        return _parse_int_value(page_info["RECOGNFILE"], "RECOGNFILE")
    return 0


def _get_recogn_text_address(
    metadata: fileformat.SupernoteMetadata, page_number: int
) -> int:
    """Returns recogn text address of the given page number.

    Returns
    -------
    int
        recogn text address
    """
    page_info = metadata.pages[page_number]
    if "RECOGNTEXT" in page_info:
        return _parse_int_value(page_info["RECOGNTEXT"], "RECOGNTEXT")
    return 0


def _get_page_number_from_footer_property(
    footer: ParamsBlock, prefix: str
) -> list[int]:
    page_numbers: list[int] = []
    for k, value in footer.items():
        if not k.startswith(prefix):
            continue
        # e.g. get '0123' from 'TITLE_01234567'
        page_num = _parse_int_value(k[6:10], k) - 1
        count = len(value) if isinstance(value, list) else 1
        page_numbers.extend([page_num] * count)
    return page_numbers


class SupernoteParser:
    """Parser for original Supernote."""

    SN_SIGNATURE_OFFSET = 0
    SN_SIGNATURE_PATTERN = r"SN_FILE_ASA_\d{8}"
    SN_SIGNATURES = ["SN_FILE_ASA_20190529"]

    def parse(
        self, file_name: str, policy: str = "strict"
    ) -> fileformat.SupernoteMetadata:
        """Parses a Supernote file and returns SupernoteMetadata object.

        Policy:
        - 'strict': raise exception for unknown signature (default)
        - 'loose': try to parse for unknown signature

        Parameters
        ----------
        file_name : str
            file path string
        policy : str
            signature check policy

        Returns
        -------
        SupernoteMetadata
            metadata of the file
        """
        with open(file_name, "rb") as f:
            metadata = self.parse_stream(f, policy)
        return metadata

    def parse_stream(
        self, stream: FileObj, policy: str = "strict"
    ) -> fileformat.SupernoteMetadata:
        """Parses a Supernote file stream and returns SupernoteMetadata object.

        Policy:
        - 'strict': raise exception for unknown signature (default)
        - 'loose': try to parse for unknown signature

        Parameters
        ----------
        file_name : str
            file path string
        policy : str
            signature check policy

        Returns
        -------
        SupernoteMetadata
            metadata of the file
        """
        # parse file type
        filetype = self._parse_filetype(stream)
        # check file signature
        signature = self._find_matching_signature(stream)
        if signature is None:
            compatible = self._check_signature_compatible(stream)
            if policy != "loose" or not compatible:
                raise exceptions.UnsupportedFileFormat(
                    f"unknown signature: {signature}"
                )
            else:
                signature = self.SN_SIGNATURES[
                    -1
                ]  # treat as latest supported signature
        # parse footer block
        stream.seek(
            -fileformat.ADDRESS_SIZE, os.SEEK_END
        )  # footer address is located at last 4-byte
        footer_address = int.from_bytes(stream.read(fileformat.ADDRESS_SIZE), "little")
        footer = self._parse_footer_block(stream, footer_address)
        # parse header block
        header_address = self._get_header_address(footer)
        header = self._parse_metadata_block(stream, header_address)
        # parse page blocks
        page_addresses = self._get_page_addresses(footer)
        pages = list(
            map(lambda addr: self._parse_page_block(stream, addr), page_addresses)
        )

        return fileformat.SupernoteMetadata(
            type=filetype,
            signature=signature,
            header=header,
            footer=footer,
            pages=pages,
        )

    def _parse_filetype(self, fobj: FileObj) -> str:
        fobj.seek(0, os.SEEK_SET)
        raw = fobj.read(4)
        if len(raw) < 4:
            raise exceptions.UnsupportedFileFormat(
                "stream too short to contain file type"
            )
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise exceptions.UnsupportedFileFormat(
                f"invalid file type header: {exc}"
            ) from exc

    def _find_matching_signature(self, fobj: FileObj) -> str | None:
        """Reads signature from file object and returns matching signature.

        Parameters
        ----------
        fobj : file
            file object

        Returns
        -------
        string
            matching signature or None if not found
        """
        latest_signature = self.SN_SIGNATURES[-1]
        try:
            fobj.seek(self.SN_SIGNATURE_OFFSET, os.SEEK_SET)
            signature = fobj.read(len(latest_signature)).decode()
        except Exception:
            return None
        if re.match(self.SN_SIGNATURE_PATTERN, signature):
            return signature
        return None

    def _check_signature_compatible(self, fobj: FileObj) -> bool:
        latest_signature = self.SN_SIGNATURES[-1]
        try:
            fobj.seek(self.SN_SIGNATURE_OFFSET, os.SEEK_SET)
            signature = fobj.read(len(latest_signature)).decode()
        except Exception:
            return False
        return bool(re.match(self.SN_SIGNATURE_PATTERN, signature))

    def _parse_footer_block(self, fobj: FileObj, address: int) -> ParamsBlock:
        return self._parse_metadata_block(fobj, address)

    def _get_header_address(self, footer: ParamsBlock) -> int:
        """Returns header address.

        Parameters
        ----------
        footer : dict
            footer parameters

        Returns
        -------
        int
            header address
        """
        return _parse_int_value(footer.get("FILE_FEATURE"), "FILE_FEATURE")

    def _get_page_addresses(self, footer: ParamsBlock) -> list[int]:
        """Returns list of page addresses.

        Parameters
        ----------
        footer : dict
            footer parameters

        Returns
        -------
        list of int
            list of page address
        """
        return _parse_address_list(footer, "PAGE")

    def _parse_page_block(self, fobj: FileObj, address: int) -> ParamsBlock:
        """Returns parameters in a page block.

        Parameters
        ----------
        fobj : file
            file object
        address : int
            page block address

        Returns
        -------
        dict
            parameters in the page block
        """
        return self._parse_metadata_block(fobj, address)

    def _parse_metadata_block(self, fobj: FileObj, address: int) -> ParamsBlock:
        """Converts metadata block into dict of parameters.

        Returns empty dict if address equals to 0.

        Parameters
        ----------
        fobj : file
            file object
        address : int
            metadata block address

        Returns
        -------
        dict
            extracted parameters
        """
        contents = _get_content_at_address(fobj, address)
        if contents is None:
            return {}
        try:
            decoded = contents.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise exceptions.ParserException(
                f"invalid UTF-8 metadata block at address {address}: {exc}"
            ) from exc
        return self._extract_parameters(decoded)

    def _extract_parameters(self, metadata: str) -> ParamsBlock:
        """Returns dict of parameters extracted from metadata.

        metadata is a repetition of key-value style parameter like
        `<KEY1:VALUE1><KEY2:VALUE2>...`.

        Parameters
        ----------
        metadata : str
            metadata string

        Returns
        -------
        dict
            extracted parameters
        """
        pattern = r"<([^:<>]+):(.*?)>"
        result = re.finditer(pattern, metadata)
        params = {}
        for m in result:
            key = m[1]
            value = m[2]
            if params.get(key):
                # the key is duplicate.
                if type(params.get(key)) is not list:
                    # To store duplicate parameters, we transform data structure
                    # from {key: value} to {key: [value1, value2, ...]}
                    first_value = params.pop(key)
                    params[key] = [first_value, value]
                else:
                    # Data structure have already been transformed.
                    # We simply append new value to the list.
                    params[key].append(value)
            else:
                params[key] = value
        return params


class SupernoteXParser(SupernoteParser):
    """Parser for Supernote X-series."""

    SN_SIGNATURE_OFFSET = 4
    SN_SIGNATURE_PATTERN = r"SN_FILE_VER_\d{8}"
    SN_SIGNATURES = [
        "SN_FILE_VER_20200001",  # Firmware version C.053
        "SN_FILE_VER_20200005",  # Firmware version C.077
        "SN_FILE_VER_20200006",  # Firmware version C.130
        "SN_FILE_VER_20200007",  # Firmware version C.159
        "SN_FILE_VER_20200008",  # Firmware version C.237
        "SN_FILE_VER_20210009",  # Firmware version C.291
        "SN_FILE_VER_20210010",  # Firmware version Chauvet 2.1.6
        "SN_FILE_VER_20220011",  # Firmware version Chauvet 2.5.17
        "SN_FILE_VER_20220013",  # Firmware version Chauvet 2.6.19
        "SN_FILE_VER_20230014",  # Firmware version Chauvet 2.10.25
        "SN_FILE_VER_20230015",  # Firmware version Chauvet 3.14.27
        "SN_FILE_VER_20260016",  # Firmware version Chauvet 2026
    ]
    LAYER_KEYS = ["MAINLAYER", "LAYER1", "LAYER2", "LAYER3", "BGLAYER"]

    def _parse_footer_block(self, fobj: FileObj, address: int) -> ParamsBlock:
        footer = super()._parse_metadata_block(fobj, address)
        # parse keywords
        keyword_addresses = self._get_keyword_addresses(footer)
        keywords = [self._parse_keyword_block(fobj, addr) for addr in keyword_addresses]
        if keywords:
            # Workaround: Replacing keyword content due to inaccurate parsing.
            for keyword in keywords:
                addr = _parse_int_value(keyword.get("KEYWORDSITE"), "KEYWORDSITE")
                content = _get_content_at_address(fobj, addr)
                if content is None:
                    keyword["KEYWORD"] = ""
                else:
                    try:
                        keyword["KEYWORD"] = content.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise exceptions.ParserException(
                            f"invalid UTF-8 keyword content at address {addr}: {exc}"
                        ) from exc
            footer[fileformat.KEY_KEYWORDS] = keywords
        # parse titles
        title_addresses = self._get_title_addresses(footer)
        titles = [self._parse_title_block(fobj, addr) for addr in title_addresses]
        if titles:
            footer[fileformat.KEY_TITLES] = titles
        # parse links
        link_addresses = self._get_link_addresses(footer)
        links = [self._parse_link_block(fobj, addr) for addr in link_addresses]
        if links:
            footer[fileformat.KEY_LINKS] = links
        return footer

    def _get_keyword_addresses(self, footer: ParamsBlock) -> list[int]:
        keyword_addresses: list[int] = []
        for k in footer:
            if k.startswith("KEYWORD_"):
                keyword_addresses.extend(_parse_address_list(footer, k))
        return keyword_addresses

    def _parse_keyword_block(self, fobj: FileObj, address: int) -> ParamsBlock:
        return self._parse_metadata_block(fobj, address)

    def _get_title_addresses(self, footer: ParamsBlock) -> list[int]:
        title_addresses: list[int] = []
        for k in footer:
            if k.startswith("TITLE_"):
                title_addresses.extend(_parse_address_list(footer, k))
        return title_addresses

    def _parse_title_block(self, fobj: FileObj, address: int) -> ParamsBlock:
        return self._parse_metadata_block(fobj, address)

    def _get_link_addresses(self, footer: ParamsBlock) -> list[int]:
        link_addresses: list[int] = []
        for k in footer:
            if k.startswith("LINK"):
                link_addresses.extend(_parse_address_list(footer, k))
        return link_addresses

    def _parse_link_block(self, fobj: FileObj, address: int) -> ParamsBlock:
        return self._parse_metadata_block(fobj, address)

    def _get_page_addresses(self, footer: ParamsBlock) -> list[int]:
        """Returns list of page addresses.

        Parameters
        ----------
        footer : dict
            footer parameters

        Returns
        -------
        list of int
            list of page address
        """
        return [_parse_int_value(footer[k], k) for k in footer if k.startswith("PAGE")]

    def _parse_page_block(self, fobj: FileObj, address: int) -> ParamsBlock:
        """Returns parameters in a page block.

        Parameters
        ----------
        fobj : file
            file object
        address : int
            page block address

        Returns
        -------
        dict
            parameters in the page block
        """
        page_info = super()._parse_page_block(fobj, address)
        layer_addresses = self._get_layer_addresses(page_info)
        layers = [self._parse_layer_block(fobj, addr) for addr in layer_addresses]
        page_info[fileformat.KEY_LAYERS] = layers
        return page_info

    def _get_layer_addresses(self, page_info: ParamsBlock) -> list[int]:
        """Returns list of layer addresses.

        Parameters
        ----------
        page_info : dict
            page parameters

        Returns
        -------
        list of int
            list of layer address
        """
        return [
            _parse_int_value(page_info[k], k) for k in page_info if k in self.LAYER_KEYS
        ]

    def _parse_layer_block(self, fobj, address):
        """Returns parameters in a layer block.

        Parameters
        ----------
        fobj : file
            file object
        address : int
            layer block address

        Returns
        -------
        dict
            parameters in the layer block
        """
        return self._parse_metadata_block(fobj, address)
