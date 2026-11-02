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

"""Parser classes for Supernote `.note` and `.mark` binary streams."""

import os
import re
from typing import Protocol

from . import exceptions, fileformat, schema

RawParamsBlock = schema.RawParamsBlock


class FileObj(Protocol):
    """Protocol for seekable binary file-like streams."""

    def seek(self, offset: int, whence: int = 0, /) -> int:
        """Seeks to the given offset."""
        ...

    def read(self, size: int = -1, /) -> bytes:
        """Reads bytes from the stream."""
        ...


def parse_metadata(stream: FileObj, policy: str = "strict") -> schema.SupernoteMetadata:
    """Parses a Supernote binary stream and returns a typed `SupernoteMetadata` tree.

    Policy:
    - 'strict': raise exception for unknown signature (default)
    - 'loose': try to parse for unknown signature

    Parameters
    ----------
    stream : file-like object
        Supernote binary stream
    policy : str
        Signature check policy

    Returns
    -------
    SupernoteMetadata
        Parsed metadata object
    """
    try:
        x_parser = SupernoteXParser()
        return x_parser.parse_stream(stream, policy)
    except exceptions.UnsupportedFileFormat:
        # ignore this exception and try next parser
        pass

    try:
        legacy_parser = SupernoteParser()
        return legacy_parser.parse_stream(stream, policy)
    except exceptions.UnsupportedFileFormat:
        # ignore this exception and try next parser
        pass

    # we cannot parse the file with any of our parsers
    raise exceptions.UnsupportedFileFormat("unsupported file format")


def load(
    stream: FileObj,
    metadata: schema.SupernoteMetadata | None = None,
    policy: str = "strict",
    page_number: int | None = None,
) -> fileformat.Notebook:
    """Creates a `Notebook` object from a Supernote binary stream.

    Policy:
    - 'strict': raise exception for unknown signature (default)
    - 'loose': try to parse for unknown signature

    Parameters
    ----------
    stream : file-like object
        Supernote binary stream
    metadata : SupernoteMetadata | None
        Optional pre-parsed metadata object
    policy : str
        Signature check policy
    page_number : int | None
        Optional single 0-based page index to load instead of all pages

    Returns
    -------
    Notebook
        Loaded notebook object
    """
    if metadata is None:
        metadata = parse_metadata(stream, policy)

    total_pages = metadata.total_pages
    if page_number is not None and (page_number < 0 or page_number >= total_pages):
        raise ValueError(
            f"page_number {page_number} out of range (0..{total_pages - 1})"
        )

    note = fileformat.Notebook(metadata, page_number=page_number)

    if page_number is not None:
        page_indices = [page_number]
    else:
        cover_address = metadata.footer.cover_address
        if cover_address > 0:
            content = _get_content_at_address(stream, cover_address)
            note.cover.content = content
        # store keyword data to notebook object
        for keyword in note.keywords:
            content = _get_content_at_address(stream, keyword.metadata.site_address)
            keyword.content = content
        # store title data to notebook object
        for title in note.titles:
            content = _get_content_at_address(stream, title.metadata.bitmap_address)
            title.content = content
        # store link data to notebook object
        for link in note.links:
            content = _get_content_at_address(stream, link.metadata.bitmap_address)
            link.content = content
        page_indices = list(range(total_pages))

    for p in page_indices:
        page_meta = metadata.pages[p]
        page_obj = note.page(p)
        if page_meta.layers is not None:
            for layer_idx, layer_meta in enumerate(page_meta.layers):
                content = _get_content_at_address(stream, layer_meta.bitmap_address)
                page_obj.layer(layer_idx).content = content
        else:
            # the page has no layers
            if page_meta.data_address is None:
                raise exceptions.ParserException(
                    "missing or invalid integer parameter 'DATA'"
                )
            content = _get_content_at_address(stream, page_meta.data_address)
            page_obj.content = content

        if page_number is None:
            # store path data to notebook object
            if page_meta.totalpath_address > 0:
                content = _get_content_at_address(stream, page_meta.totalpath_address)
                page_obj.totalpath = content
            # store recogn file data to notebook object
            if page_meta.recogn_file_address > 0:
                content = _get_content_at_address(stream, page_meta.recogn_file_address)
                page_obj.recogn_file = content

        # store recogn text data to notebook object
        if page_meta.recogn_text_address > 0:
            content = _get_content_at_address(stream, page_meta.recogn_text_address)
            page_obj.recogn_text = content

    return note


def load_notebook(
    file_name: str | os.PathLike[str],
    metadata: schema.SupernoteMetadata | None = None,
    policy: str = "strict",
    page_number: int | None = None,
) -> fileformat.Notebook:
    """Creates a `Notebook` object from a Supernote file path.

    Policy:
    - 'strict': raise exception for unknown signature (default)
    - 'loose': try to parse for unknown signature

    Parameters
    ----------
    file_name : str | os.PathLike[str]
        File path
    metadata : SupernoteMetadata | None
        Optional pre-parsed metadata object
    policy : str
        Signature check policy
    page_number : int | None
        Optional single 0-based page index to load instead of all pages

    Returns
    -------
    Notebook
        Loaded notebook object
    """
    with open(file_name, "rb") as f:
        return load(f, metadata, policy, page_number=page_number)


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


def _parse_footer_key_page_index(key: str) -> int:
    """Extract 0-based page index from `TITLE_<page4>...` or `LINKO_<page4>...`."""
    # e.g. get '0123' from 'TITLE_01234567'
    return _parse_int_value(key[6:10], key) - 1


class SupernoteParser:
    """Parser for legacy A5 Supernote files (`SN_FILE_ASA_*`)."""

    SN_SIGNATURE_OFFSET = 0
    SN_SIGNATURE_PATTERN = r"SN_FILE_ASA_\d{8}"
    SN_SIGNATURES = ["SN_FILE_ASA_20190529"]

    def parse(self, file_name: str, policy: str = "strict") -> schema.SupernoteMetadata:
        """Parses a Supernote file path and returns `SupernoteMetadata`.

        Policy:
        - 'strict': raise exception for unknown signature (default)
        - 'loose': try to parse for unknown signature

        Parameters
        ----------
        file_name : str
            File path string
        policy : str
            Signature check policy

        Returns
        -------
        SupernoteMetadata
            Parsed metadata of the file
        """
        with open(file_name, "rb") as f:
            return self.parse_stream(f, policy)

    def parse_stream(
        self, stream: FileObj, policy: str = "strict"
    ) -> schema.SupernoteMetadata:
        """Parses a Supernote binary stream and returns `SupernoteMetadata`.

        Policy:
        - 'strict': raise exception for unknown signature (default)
        - 'loose': try to parse for unknown signature

        Parameters
        ----------
        stream : file-like object
            Supernote binary stream
        policy : str
            Signature check policy

        Returns
        -------
        SupernoteMetadata
            Parsed metadata of the file
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
            # treat as latest supported signature
            signature = self.SN_SIGNATURES[-1]

        # parse footer block (footer address is located at last 4-byte)
        stream.seek(-fileformat.ADDRESS_SIZE, os.SEEK_END)
        footer_address = int.from_bytes(stream.read(fileformat.ADDRESS_SIZE), "little")
        footer = self._parse_footer_block(stream, footer_address)
        # parse header block
        header_address = self._get_header_address(footer)
        header = schema.HeaderMetadata.from_params(
            self._parse_metadata_block(stream, header_address)
        )
        # parse page blocks
        page_addresses = self._get_page_addresses(footer)
        pages = [self._parse_page_block(stream, addr) for addr in page_addresses]

        return schema.SupernoteMetadata(
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
        latest_signature = self.SN_SIGNATURES[-1]
        try:
            fobj.seek(self.SN_SIGNATURE_OFFSET, os.SEEK_SET)
            signature = fobj.read(len(latest_signature)).decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        if signature in self.SN_SIGNATURES:
            return signature
        return None

    def _check_signature_compatible(self, fobj: FileObj) -> bool:
        latest_signature = self.SN_SIGNATURES[-1]
        try:
            fobj.seek(self.SN_SIGNATURE_OFFSET, os.SEEK_SET)
            signature = fobj.read(len(latest_signature)).decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        return bool(re.match(self.SN_SIGNATURE_PATTERN, signature))

    def _parse_footer_block(self, fobj: FileObj, address: int) -> schema.FooterMetadata:
        return schema.FooterMetadata.from_params(
            self._parse_metadata_block(fobj, address)
        )

    def _get_header_address(self, footer: schema.FooterMetadata) -> int:
        if footer.file_feature_address is None:
            raise exceptions.ParserException(
                "missing or invalid integer parameter 'FILE_FEATURE'"
            )
        return footer.file_feature_address

    def _get_page_addresses(self, footer: schema.FooterMetadata) -> list[int]:
        if not footer.legacy_page_addresses:
            raise exceptions.ParserException("missing address parameter 'PAGE'")
        return list(footer.legacy_page_addresses)

    def _parse_page_block(self, fobj: FileObj, address: int) -> schema.PageMetadata:
        return schema.PageMetadata.from_params(
            self._parse_metadata_block(fobj, address)
        )

    def _parse_metadata_block(self, fobj: FileObj, address: int) -> RawParamsBlock:
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

    def _extract_parameters(self, metadata: str) -> RawParamsBlock:
        return schema.extract_parameters(metadata)


class SupernoteXParser(SupernoteParser):
    """Parser for Supernote X and X2 series files (`SN_FILE_VER_*`)."""

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
    LAYER_KEYS = [layer_key.value for layer_key in schema.X_SERIES_LAYER_KEYS]

    def _parse_footer_block(self, fobj: FileObj, address: int) -> schema.FooterMetadata:
        footer = schema.FooterMetadata.from_params(
            self._parse_metadata_block(fobj, address)
        )

        # parse keywords
        keywords: list[schema.KeywordMetadata] = []
        for addrs in footer.keyword_addresses.values():
            for addr in addrs:
                kw = schema.KeywordMetadata.from_params(
                    self._parse_metadata_block(fobj, addr)
                )
                # Workaround: Replacing keyword content due to inaccurate parsing.
                content = _get_content_at_address(fobj, kw.site_address)
                if content is None:
                    kw.keyword = ""
                else:
                    try:
                        kw.keyword = content.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise exceptions.ParserException(
                            f"invalid UTF-8 keyword content at address {kw.site_address}: {exc}"
                        ) from exc
                keywords.append(kw)
        footer.keywords = keywords

        # parse titles
        titles: list[schema.TitleMetadata] = []
        for key, addrs in footer.title_addresses.items():
            page_index = _parse_footer_key_page_index(key)
            for addr in addrs:
                titles.append(
                    schema.TitleMetadata.from_params(
                        self._parse_metadata_block(fobj, addr),
                        page_index=page_index,
                    )
                )
        footer.titles = titles

        # parse links
        links: list[schema.LinkMetadata] = []
        for key, addrs in footer.link_addresses.items():
            page_index = _parse_footer_key_page_index(key)
            for addr in addrs:
                links.append(
                    schema.LinkMetadata.from_params(
                        self._parse_metadata_block(fobj, addr),
                        page_index=page_index,
                    )
                )
        footer.links = links

        return footer

    def _get_page_addresses(self, footer: schema.FooterMetadata) -> list[int]:
        return list(footer.page_addresses.values())

    def _parse_page_block(self, fobj: FileObj, address: int) -> schema.PageMetadata:
        raw_page = self._parse_metadata_block(fobj, address)
        layer_addresses = [
            _parse_int_value(raw_page[key], key)
            for key in raw_page
            if key in self.LAYER_KEYS
        ]
        layers = [
            schema.LayerMetadata.from_params(
                self._parse_metadata_block(fobj, layer_addr)
            )
            for layer_addr in layer_addresses
        ]
        return schema.PageMetadata.from_params(raw_page, layers=layers)
