# Copyright (c) 2021 jya
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

"""Note manipulator classes."""

import io
import re
from collections.abc import Mapping

from . import exceptions, fileformat, parser, schema, utils


class NotebookBuilder:
    def __init__(self, offset: int = 0) -> None:
        self.total_size = offset
        self.toc: dict[str, int | list[int]] = {}
        self.blocks: list[bytes] = []

    def get_total_size(self) -> int:
        return self.total_size

    def get_block_address(self, label: str) -> int:
        entry = self.toc.get(label)
        if isinstance(entry, list):
            address: int | None = entry[0]  # use first one
        else:
            address = entry
        return address if address is not None else 0

    def get_duplicate_block_address_list(self, label: str) -> list[int | None]:
        entry = self.toc.get(label)
        if isinstance(entry, list):
            return list(entry)
        return [entry]

    def get_labels(self):
        return self.toc.keys()

    def append(
        self,
        label: str,
        block: bytes | None,
        skip_block_size: bool = False,
        allow_duplicate: bool = False,
    ) -> bool:
        if not label or block is None:
            raise ValueError("empty label or block is not allowed")
        label_duplicated = label in self.toc
        if label_duplicated and not allow_duplicate:
            return False
        block_size = len(block)
        if not skip_block_size:
            self.blocks.append(
                block_size.to_bytes(fileformat.LENGTH_FIELD_SIZE, "little")
            )
        self.blocks.append(block)
        if label_duplicated:
            existing = self.toc[label]
            if isinstance(existing, list):
                existing.append(self.total_size)
            else:
                self.toc[label] = [existing, self.total_size]
        else:
            self.toc.setdefault(label, self.total_size)
        self.total_size += block_size
        if not skip_block_size:
            self.total_size += fileformat.LENGTH_FIELD_SIZE
        return True

    def build(self) -> bytes:
        return b"".join(self.blocks)

    def dump(self) -> None:
        print("# NotebookBuilder Dump:")
        print(f"# total_size = {self.total_size}")
        print(f"# toc = {self.toc}")


def reconstruct(notebook: fileformat.Notebook) -> bytes:
    """Reconstruct a notebook binary from its in-memory representation."""
    expected_signature = parser.SupernoteXParser.SN_SIGNATURES[
        -1
    ]  # latest supported signature
    metadata = notebook.get_metadata()
    if metadata.signature != expected_signature:
        raise ValueError(
            f"Only latest file format version is supported ({metadata.signature} != {expected_signature})"
        )

    builder = NotebookBuilder()
    _pack_type(builder, notebook)
    _pack_signature(builder, notebook)
    _pack_header(builder, notebook)
    _pack_cover(builder, notebook)
    _pack_keywords(builder, notebook)
    _pack_titles(builder, notebook)
    _pack_links(builder, notebook)
    _pack_backgrounds(builder, notebook)
    _pack_pages(builder, notebook)
    _pack_footer(builder)
    _pack_tail(builder)
    _pack_footer_address(builder)
    reconstructed_binary = builder.build()
    # check file format integrity
    try:
        stream = io.BytesIO(reconstructed_binary)
        xparser = parser.SupernoteXParser()
        _ = xparser.parse_stream(stream)
    except Exception as e:
        raise exceptions.GeneratedFileValidationException(
            f"generated file fails validation: {e}"
        ) from e
    return reconstructed_binary


def merge(notebook1: fileformat.Notebook, notebook2: fileformat.Notebook) -> bytes:
    """Merge two notebooks into one binary stream."""
    # TODO: support non-X series
    metadata1 = notebook1.get_metadata()
    metadata2 = notebook2.get_metadata()
    expected_signature = parser.SupernoteXParser.SN_SIGNATURES[
        -1
    ]  # latest supported signature
    if metadata1.signature != expected_signature:
        raise ValueError(
            f"Only latest file format version is supported ({metadata1.signature} != {expected_signature})"
        )
    if metadata1.signature != metadata2.signature:
        raise ValueError(
            f"File signature must be same between merging files ({metadata1.signature} != {metadata2.signature})"
        )
    if notebook1.get_total_pages() + notebook2.get_total_pages() > 9999:
        raise ValueError("The total number of pages are limited to 9999")
    # check header properties are same to avoid generating a corrupted note file
    _verify_header_property("FILE_TYPE", metadata1, metadata2)
    _verify_header_property("APPLY_EQUIPMENT", metadata1, metadata2)
    _verify_header_property("DEVICE_DPI", metadata1, metadata2)
    _verify_header_property("SOFT_DPI", metadata1, metadata2)
    _verify_header_property("FILE_PARSE_TYPE", metadata1, metadata2)
    _verify_header_property("RATTA_ETMD", metadata1, metadata2)
    _verify_header_property("APP_VERSION", metadata1, metadata2)

    builder = NotebookBuilder()
    _pack_type(builder, notebook1)
    _pack_signature(builder, notebook1)
    _pack_header(builder, notebook1)
    _pack_cover(builder, notebook1)
    _pack_keywords(builder, notebook1)
    _pack_keywords(builder, notebook2, offset=notebook1.get_total_pages())
    _pack_titles(builder, notebook1)
    _pack_titles(builder, notebook2, offset=notebook1.get_total_pages())
    _pack_links(builder, notebook1)
    _pack_links(builder, notebook2, offset=notebook1.get_total_pages())
    _pack_backgrounds(builder, notebook1)
    _pack_backgrounds(builder, notebook2)
    _pack_pages(builder, notebook1)
    _pack_pages(builder, notebook2, offset=notebook1.get_total_pages())
    _pack_footer(builder)
    _pack_tail(builder)
    _pack_footer_address(builder)
    merged_binary = builder.build()
    # check file format integrity
    try:
        stream = io.BytesIO(merged_binary)
        xparser = parser.SupernoteXParser()
        _ = xparser.parse_stream(stream)
    except Exception as e:
        raise exceptions.GeneratedFileValidationException(
            f"generated file fails validation: {e}"
        ) from e
    return merged_binary


def _pack_type(builder: NotebookBuilder, notebook: fileformat.Notebook) -> None:
    metadata = notebook.get_metadata()
    builder.append("__type__", metadata.type.encode("ascii"), skip_block_size=True)


def _pack_signature(builder: NotebookBuilder, notebook: fileformat.Notebook) -> None:
    metadata = notebook.get_metadata()
    builder.append(
        "__signature__", metadata.signature.encode("ascii"), skip_block_size=True
    )


def _pack_header(builder: NotebookBuilder, notebook: fileformat.Notebook) -> None:
    metadata = notebook.get_metadata()
    header_block = _construct_metadata_block(metadata.header.to_params())
    builder.append("__header__", header_block)


def _pack_cover(builder: NotebookBuilder, notebook: fileformat.Notebook) -> None:
    cover_block = notebook.get_cover().get_content()
    if cover_block is not None:
        builder.append("COVER_2", cover_block)


def _pack_keywords(
    builder: NotebookBuilder, notebook: fileformat.Notebook, offset: int = 0
) -> None:
    for keyword in notebook.get_keywords():
        page_number = keyword.get_page_number() + 1 + offset
        if page_number > 9999:
            # the number of digits is limited to 4, so we ignore this keyword
            continue
        position = keyword.get_position_string()
        item_id = f"{page_number:04d}{position}"
        content = keyword.get_content()
        if content is not None:
            builder.append(f"KEYWORD_{item_id}", content, allow_duplicate=True)
            keyword_metadata = keyword.metadata.to_params()
            keyword_metadata["KEYWORDPAGE"] = str(page_number)
            address_list = builder.get_duplicate_block_address_list(
                f"KEYWORD_{item_id}"
            )
            keyword_metadata["KEYWORDSITE"] = str(address_list[-1])  # use last address
            keyword_metadata_block = _construct_metadata_block(keyword_metadata)
            builder.append(
                f"KEYWORD_{item_id}/metadata",
                keyword_metadata_block,
                allow_duplicate=True,
            )


def _pack_titles(
    builder: NotebookBuilder, notebook: fileformat.Notebook, offset: int = 0
) -> None:
    for title in notebook.get_titles():
        page_number = title.get_page_number() + 1 + offset
        if page_number > 9999:
            # the number of digits is limited to 4, so we ignore this title
            continue
        position = title.get_position_string()
        item_id = f"{page_number:04d}{position}"
        content = title.get_content()
        if content is not None:
            builder.append(f"TITLE_{item_id}", content, allow_duplicate=True)
            title_metadata = title.metadata.to_params()
            address_list = builder.get_duplicate_block_address_list(f"TITLE_{item_id}")
            title_metadata["TITLEBITMAP"] = str(address_list[-1])  # use last address
            title_metadata_block = _construct_metadata_block(title_metadata)
            builder.append(
                f"TITLE_{item_id}/metadata", title_metadata_block, allow_duplicate=True
            )


def _pack_links(
    builder: NotebookBuilder, notebook: fileformat.Notebook, offset: int = 0
) -> None:
    for link in notebook.get_links():
        page_number = link.get_page_number() + 1 + offset
        if page_number > 9999:
            # the number of digits is limited to 4, so we ignore this link
            continue
        position = link.get_position_string()
        item_id = f"{page_number:04d}{position}"
        content = link.get_content()
        if content is not None:
            builder.append(f"LINKO_{item_id}", content, allow_duplicate=True)
            link_metadata = link.metadata.to_params()
            address_list = builder.get_duplicate_block_address_list(f"LINKO_{item_id}")
            link_metadata["LINKBITMAP"] = str(address_list[-1])  # use last address
            link_metadata_block = _construct_metadata_block(link_metadata)
            builder.append(
                f"LINKO_{item_id}/metadata", link_metadata_block, allow_duplicate=True
            )


def _resolve_page_style(page: fileformat.Page, page_index: int) -> str:
    style = page.get_style()
    if not style:
        raise exceptions.ManipulatorException(
            f"page {page_index} metadata is missing PAGESTYLE"
        )
    if style.startswith("user_"):
        style += page.get_style_hash()
    return style


def _pack_backgrounds(builder: NotebookBuilder, notebook: fileformat.Notebook) -> None:
    for i in range(notebook.get_total_pages()):
        page = notebook.get_page(i)
        content = _find_background_content_from_page(page)
        if content is None:
            continue
        style = _resolve_page_style(page, i)
        builder.append(f"STYLE_{style}", content)


def _pack_pages(
    builder: NotebookBuilder, notebook: fileformat.Notebook, offset: int = 0
) -> None:
    for i in range(notebook.get_total_pages()):
        page_number = i + 1 + offset
        page = notebook.get_page(i)
        wrapped_page = utils.WorkaroundPageWrapper.from_page(page)
        # layers
        for layer in wrapped_page.get_layers():
            layer_name = layer.get_name()
            if layer_name is None:
                continue
            if layer_name == schema.LayerName.BGLAYER:
                style = _resolve_page_style(wrapped_page, i)
                layer_metadata = layer.metadata.to_params()
                layer_metadata["LAYERNAME"] = layer_name
                layer_metadata["LAYERBITMAP"] = str(
                    builder.get_block_address(f"STYLE_{style}")
                )
                layer_metadata_block = _construct_metadata_block(layer_metadata)
                builder.append(
                    f"PAGE{page_number}/{layer_name}/metadata", layer_metadata_block
                )
            else:
                content = layer.get_content()
                if content is not None:
                    builder.append(
                        f"PAGE{page_number}/{layer_name}/LAYERBITMAP", content
                    )
                layer_metadata = layer.metadata.to_params()
                layer_metadata["LAYERNAME"] = layer_name
                layer_metadata["LAYERBITMAP"] = str(
                    builder.get_block_address(
                        f"PAGE{page_number}/{layer_name}/LAYERBITMAP"
                    )
                )
                layer_metadata_block = _construct_metadata_block(layer_metadata)
                builder.append(
                    f"PAGE{page_number}/{layer_name}/metadata", layer_metadata_block
                )
        # totalpath
        totalpath_block = wrapped_page.get_totalpath()
        if totalpath_block is not None:
            builder.append(f"PAGE{page_number}/TOTALPATH", totalpath_block)
        # page metadata
        page_metadata = wrapped_page.metadata.to_params()
        for prop in schema.X_SERIES_LAYER_KEYS:
            address = builder.get_block_address(
                f"PAGE{page_number}/{prop.value}/metadata"
            )
            page_metadata[prop.value] = str(address)
        page_metadata["TOTALPATH"] = str(
            builder.get_block_address(f"PAGE{page_number}/TOTALPATH")
        )
        page_metadata_block = _construct_metadata_block(page_metadata)
        builder.append(f"PAGE{page_number}/metadata", page_metadata_block)


def _pack_footer(builder: NotebookBuilder) -> None:
    metadata_footer: dict[str, object] = {}
    metadata_footer.setdefault("FILE_FEATURE", builder.get_block_address("__header__"))
    for label in builder.get_labels():
        if re.match(r"PAGE\d+/metadata", label):
            address = builder.get_block_address(label)
            short_label = label[: -len("/metadata")]
            metadata_footer.setdefault(short_label, address)
    for label in builder.get_labels():
        if re.match(r"TITLE_\d+/metadata", label):
            address_list = builder.get_duplicate_block_address_list(label)
            short_label = label[: -len("/metadata")]
            if len(address_list) == 1:
                metadata_footer.setdefault(short_label, address_list[0])
            else:
                metadata_footer[short_label] = address_list
    for label in builder.get_labels():
        if re.match(r"KEYWORD_\d+/metadata", label):
            address_list = builder.get_duplicate_block_address_list(label)
            short_label = label[: -len("/metadata")]
            if len(address_list) == 1:
                metadata_footer.setdefault(short_label, address_list[0])
            else:
                metadata_footer[short_label] = address_list
    for label in builder.get_labels():
        if re.match(r"LINKO_\d+/metadata", label):
            address_list = builder.get_duplicate_block_address_list(label)
            short_label = label[: -len("/metadata")]
            if len(address_list) == 1:
                metadata_footer.setdefault(short_label, address_list[0])
            else:
                metadata_footer[short_label] = address_list
    address = builder.get_block_address("COVER_2")
    if address == 0:
        metadata_footer["COVER_0"] = 0
    else:
        metadata_footer["COVER_2"] = address
    for label in builder.get_labels():
        if label.startswith("STYLE_"):
            address = builder.get_block_address(label)
            metadata_footer.setdefault(label, address)
    footer_block = _construct_metadata_block(metadata_footer)
    builder.append("__footer__", footer_block)


def _pack_tail(builder: NotebookBuilder) -> None:
    builder.append("__tail__", b"tail", skip_block_size=True)


def _pack_footer_address(builder: NotebookBuilder) -> None:
    footer_address = builder.get_block_address("__footer__")
    builder.append(
        "__footer_address__", footer_address.to_bytes(4, "little"), skip_block_size=True
    )


def _verify_header_property(
    prop_name: str,
    metadata1: schema.SupernoteMetadata,
    metadata2: schema.SupernoteMetadata,
) -> None:
    header1 = metadata1.header.to_params()
    header2 = metadata2.header.to_params()
    if header1.get(prop_name) != header2.get(prop_name):
        raise ValueError(f"<{prop_name}> property must be same between merging files")


def _construct_metadata_block(info: Mapping[str, object]) -> bytes:
    return schema.encode_parameters(info)


def _find_background_content_from_page(page: fileformat.Page) -> bytes | None:
    if not page.is_layer_supported():
        return None
    wrapped_page = utils.WorkaroundPageWrapper.from_page(page)
    for layer in wrapped_page.get_layers():
        if layer.get_name() == schema.LayerName.BGLAYER:
            return layer.get_content()
    return None
