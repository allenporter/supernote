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

"""Utility classes."""

import copy
from collections.abc import Mapping
from typing import Any, Self

from . import fileformat, schema


class WorkaroundPageWrapper(fileformat.Page):
    """Workaround for duplicated layer name."""

    def __init__(self, page_info: schema.PageMetadata | Mapping[str, Any]) -> None:
        if isinstance(page_info, schema.PageMetadata):
            page_info = copy.deepcopy(page_info)
        super().__init__(page_info)
        self._override_layer_name()

    @classmethod
    def from_page(cls, page: fileformat.Page) -> Self:
        wrapped_page = cls(page.metadata)
        # copy contents from the original page object
        wrapped_page.content = page.content
        wrapped_page.totalpath = page.totalpath
        wrapped_page.recogn_file = page.recogn_file
        wrapped_page.recogn_text = page.recogn_text
        wrapped_page._page_index = page._page_index
        wrapped_page._notebook = page._notebook
        wrapped_page._keywords = list(page._keywords)
        wrapped_page._titles = list(page._titles)
        wrapped_page._links = list(page._links)
        for i, layer in enumerate(page.layers):
            wrapped_page.layer(i).content = layer.content
        return wrapped_page

    def _override_layer_name(self) -> None:
        mainlayer_visited = False
        for layer in self.layers:
            name = layer.name
            if name is None:
                continue
            if mainlayer_visited and name == schema.LayerName.MAINLAYER:
                # this layer has duplicated name, so we guess this layer is BGLAYER
                layer.metadata.name = schema.LayerName.BGLAYER
            elif name == schema.LayerName.MAINLAYER:
                mainlayer_visited = True
