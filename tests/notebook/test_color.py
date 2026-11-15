from typing import Any, cast

import pytest

from supernote.notebook import color


def test_get_rgb_and_web_string() -> None:
    assert color.get_rgb(0x123456) == (0x12, 0x34, 0x56)
    assert color.web_string(0x123456, mode=color.MODE_RGB) == "#123456"
    assert color.web_string(0x9D, mode=color.MODE_GRAYSCALE) == "#9d9d9d"


def test_color_palette_modes_and_validation() -> None:
    gray_palette = color.ColorPalette(
        color.MODE_GRAYSCALE,
        (color.BLACK, color.DARK_GRAY, color.GRAY, color.WHITE),
    )
    assert gray_palette.transparent == color.TRANSPARENT

    rgb_palette = color.ColorPalette(
        color.MODE_RGB,
        (color.RGB_BLACK, color.RGB_DARK_GRAY, color.RGB_GRAY, color.RGB_WHITE),
    )
    assert rgb_palette.transparent == color.RGB_TRANSPARENT

    with pytest.raises(ValueError, match="mode must be MODE_GRAYSCALE or MODE_RGB"):
        color.ColorPalette("invalid_mode")

    with pytest.raises(ValueError, match="colors must have 4 color values"):
        color.ColorPalette(color.MODE_GRAYSCALE, cast(Any, (0, 1, 2)))
