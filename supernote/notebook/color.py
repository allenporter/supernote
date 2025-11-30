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

"""Color classes."""

# color mode
MODE_GRAYSCALE = "grayscale"
MODE_RGB = "rgb"

# preset grayscale colors
BLACK = 0x00
DARK_GRAY = 0x9D
GRAY = 0xC9
WHITE = 0xFE
TRANSPARENT = 0xFF
DARK_GRAY_COMPAT = 0x30
GRAY_COMPAT = 0x50

# preset RGB colors
RGB_BLACK = 0x000000
RGB_DARK_GRAY = 0x9D9D9D
RGB_GRAY = 0xC9C9C9
RGB_WHITE = 0xFEFEFE
RGB_TRANSPARENT = 0xFFFFFF
RGB_DARK_GRAY_COMPAT = 0x303030
RGB_GRAY_COMPAT = 0x505050


def get_rgb(value: int) -> tuple[int, int, int]:
    r = (value & 0xFF0000) >> 16
    g = (value & 0x00FF00) >> 8
    b = value & 0x0000FF
    return (r, g, b)


def web_string(value: int, mode: str = MODE_RGB) -> str:
    if mode == MODE_GRAYSCALE:
        return "#" + (format(value & 0xFF, "02x") * 3)
    else:
        r, g, b = get_rgb(value)
        return (
            "#"
            + format(r & 0xFF, "02x")
            + format(g & 0xFF, "02x")
            + format(b & 0xFF, "02x")
        )


class ColorPalette:
    def __init__(
        self,
        mode: str = MODE_GRAYSCALE,
        colors: tuple[int, int, int, int] = (BLACK, DARK_GRAY, GRAY, WHITE),
        compat_colors: tuple[int, int] = (DARK_GRAY_COMPAT, GRAY_COMPAT),
    ) -> None:
        if mode not in [MODE_GRAYSCALE, MODE_RGB]:
            raise ValueError("mode must be MODE_GRAYSCALE or MODE_RGB")
        if len(colors) != 4:
            raise ValueError(
                "colors must have 4 color values (black, darkgray, gray, white)"
            )
        self.mode = mode
        self.black = colors[0]
        self.darkgray = colors[1]
        self.gray = colors[2]
        self.white = colors[3]
        if mode == MODE_GRAYSCALE:
            self.transparent = TRANSPARENT
        else:
            self.transparent = RGB_TRANSPARENT
        self.darkgray_compat = compat_colors[0]
        self.gray_compat = compat_colors[1]


DEFAULT_COLORPALETTE = ColorPalette(
    MODE_GRAYSCALE, (BLACK, DARK_GRAY, GRAY, WHITE), (DARK_GRAY_COMPAT, GRAY_COMPAT)
)
DEFAULT_RGB_COLORPALETTE = ColorPalette(
    MODE_RGB,
    (RGB_BLACK, RGB_DARK_GRAY, RGB_GRAY, RGB_WHITE),
    (RGB_DARK_GRAY_COMPAT, RGB_GRAY_COMPAT),
)
