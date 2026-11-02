"""Notebook CLI commands."""

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

import argparse
import io
import os
import sys
from pathlib import Path
from typing import NoReturn

from colour import Color

from supernote.notebook import (
    NotebookAuthor,
    load,
    load_notebook,
    merge,
    parse_metadata,
    reconstruct,
)
from supernote.notebook.color import MODE_RGB, ColorPalette
from supernote.notebook.converter import (
    ImageConverter,
    PdfConverter,
    SvgConverter,
    TextConverter,
    VisibilityOverlay,
    build_visibility_overlay,
)


def convert_all(converter, total, file_name, save_func, visibility_overlay):
    basename, extension = os.path.splitext(file_name)
    max_digits = len(str(total))
    for i in range(total):
        # append page number between filename and extension
        numbered_filename = basename + "_" + str(i).zfill(max_digits) + extension
        img = converter.convert(i, visibility_overlay)
        save_func(img, numbered_filename)


def convert_and_concat_all(converter, total, file_name, save_func, separator):
    data = []
    for i in range(total):
        data.append(converter.convert(i))
    data = list(map(lambda x: "" if x is None else (x + "\n"), data))
    if len(data) > 0:
        alldata = ((separator + "\n") if separator else "").join(data)
        save_func(alldata, file_name)
    else:
        print("no data")


def convert_to_png(args, notebook, palette):
    converter = ImageConverter(notebook, palette=palette)
    bg_visibility = (
        VisibilityOverlay.INVISIBLE
        if args.exclude_background
        else VisibilityOverlay.DEFAULT
    )
    vo = build_visibility_overlay(background=bg_visibility)

    def save(img, file_name):
        img.save(file_name, format="PNG")

    if args.all:
        total = notebook.total_pages
        convert_all(converter, total, args.output, save, vo)
    else:
        img = converter.convert(args.number, visibility_overlay=vo)
        save(img, args.output)


def convert_to_svg(args, notebook, palette):
    converter = SvgConverter(notebook, palette=palette)
    bg_visibility = (
        VisibilityOverlay.INVISIBLE
        if args.exclude_background
        else VisibilityOverlay.DEFAULT
    )
    vo = build_visibility_overlay(background=bg_visibility)

    def save(svg, file_name):
        if svg is not None:
            with open(file_name, "w") as f:
                f.write(svg)
        else:
            print("no path data")

    if args.all:
        total = notebook.total_pages
        convert_all(converter, total, args.output, save, vo)
    else:
        svg = converter.convert(args.number, visibility_overlay=vo)
        save(svg, args.output)


def convert_to_pdf(args, notebook, palette):
    use_link = not args.no_link
    use_keyword = args.add_keyword
    converter = PdfConverter(notebook, palette=palette)

    def save(data, file_name):
        if data is not None:
            with open(file_name, "wb") as f:
                f.write(data)
        else:
            print("no data")

    if args.all:
        data = converter.convert(
            -1, enable_link=use_link, enable_keyword=use_keyword
        )  # minus value means converting all pages
        save(data, args.output)
    else:
        data = converter.convert(
            args.number, enable_link=use_link, enable_keyword=use_keyword
        )
        save(data, args.output)


def convert_to_txt(args, notebook, palette):
    converter = TextConverter(notebook, palette=palette)

    def save(data, file_name):
        if data is not None:
            with open(file_name, "w") as f:
                f.write(data)
        else:
            print("no data")

    if args.all:
        total = notebook.total_pages
        convert_and_concat_all(
            converter, total, args.output, save, args.text_page_separator
        )
    else:
        data = converter.convert(args.number)
        save(data, args.output)


def subcommand_convert(args):
    notebook = load_notebook(args.input, policy=args.policy)
    palette = None
    if args.color:
        try:
            colors = parse_color(args.color)
        except ValueError as e:
            print(e, file=sys.stderr)
            sys.exit(1)
        palette = ColorPalette(MODE_RGB, colors)
    if args.type == "png":
        convert_to_png(args, notebook, palette)
    elif args.type == "svg":
        convert_to_svg(args, notebook, palette)
    elif args.type == "pdf":
        convert_to_pdf(args, notebook, palette)
    elif args.type == "txt":
        convert_to_txt(args, notebook, palette)


def subcommand_analyze(args):
    # show all metadata as JSON
    with open(args.input, "rb") as f:
        metadata = parse_metadata(f, policy=args.policy)
    print(metadata.to_json(indent=2))


def subcommand_merge(args):
    num_input = len(args.input)
    if num_input == 1:  # reconstruct a note file
        notebook = load_notebook(args.input[0])
        reconstructed_binary = reconstruct(notebook)
        with open(args.output, "wb") as f:
            f.write(reconstructed_binary)
    else:  # merge multiple note files
        with open(args.input[0], "rb") as f:
            merged_binary = f.read()
        for i in range(1, num_input):
            stream = io.BytesIO(merged_binary)
            merged_notebook = load(stream)
            next_notebook = load_notebook(args.input[i])
            merged_binary = merge(merged_notebook, next_notebook)
        with open(args.output, "wb") as f:
            f.write(merged_binary)


def subcommand_reconstruct(args):
    notebook = load_notebook(args.input)
    reconstructed_binary = reconstruct(notebook)
    with open(args.output, "wb") as f:
        f.write(reconstructed_binary)


def _exit_cli_error(message: str, code: int = 2) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(code)


def subcommand_create(args: argparse.Namespace) -> None:
    """Create a new `.note` file or append Markdown pages onto an existing `.note` file.

    Routes CLI flags from `supernote create` into `NotebookAuthor`, supporting inline
    `--text`, Markdown files, or `stdin` (`-`), three stationery styles (`stylized`,
    `handwriting`, `architect`), hidden `LAYER1` overlay cards, TOC generation, and
    non-destructive `--append-to` editing.
    """
    if args.text is not None and args.input is not None:
        _exit_cli_error("cannot specify both positional 'input' and '--text'", code=2)
    if args.hidden_layer_text is not None and args.hidden_layer_file is not None:
        _exit_cli_error(
            "cannot specify both '--hidden-layer-text' and '--hidden-layer-file'",
            code=2,
        )
    if args.append_to is not None and args.equipment is not None:
        _exit_cli_error(
            "cannot override '--equipment' when using '--append-to'",
            code=2,
        )
    if args.font_size is not None and args.font_size <= 0:
        _exit_cli_error(
            f"'--font-size' must be positive, got {args.font_size}",
            code=2,
        )
    if args.font is not None and not Path(args.font).is_file():
        _exit_cli_error(f"font file not found: {args.font}", code=1)

    markdown = ""
    if args.text is not None:
        markdown = args.text
    elif args.input is not None:
        if args.input == "-":
            markdown = sys.stdin.read()
        else:
            input_path = Path(args.input)
            if not input_path.is_file():
                _exit_cli_error(f"input file not found: {args.input}", code=1)
            markdown = input_path.read_text(encoding="utf-8")

    hidden_md = None
    if args.hidden_layer_text is not None:
        hidden_md = args.hidden_layer_text
    elif args.hidden_layer_file is not None:
        hidden_path = Path(args.hidden_layer_file)
        if not hidden_path.is_file():
            _exit_cli_error(
                f"hidden layer file not found: {args.hidden_layer_file}",
                code=1,
            )
        hidden_md = hidden_path.read_text(encoding="utf-8")

    if args.append_to:
        append_path = Path(args.append_to)
        if not append_path.is_file():
            _exit_cli_error(
                f"append-to notebook not found: {args.append_to}",
                code=1,
            )
        existing = load_notebook(str(append_path), policy="loose")
        author = NotebookAuthor.from_notebook(existing, seed=args.seed)
    else:
        author = NotebookAuthor(
            equipment=args.equipment or "N6",
            seed=args.seed,
        )

    if markdown or hidden_md:
        author.add_markdown(
            markdown,
            style=args.style,
            background=args.background,
            layer=args.layer,
            hidden_layer_markdown=hidden_md,
            auto_toc=args.auto_toc,
            extract_keywords=not args.no_keywords,
            font_path=args.font,
            font_size=args.font_size,
            seed=args.seed,
        )
    else:
        author.add_page(background=args.background)

    author.save(args.output)


def parse_color(color_string):
    colorcodes = color_string.split(",")
    if len(colorcodes) != 4:
        raise ValueError(f"few color codes, 4 colors are required: {color_string}")
    black = int(Color(colorcodes[0]).hex_l[1:7], 16)
    darkgray = int(Color(colorcodes[1]).hex_l[1:7], 16)
    gray = int(Color(colorcodes[2]).hex_l[1:7], 16)
    white = int(Color(colorcodes[3]).hex_l[1:7], 16)
    return (black, darkgray, gray, white)


def add_parser(subparsers):
    # 'analyze' subcommand
    parser_analyze = subparsers.add_parser("analyze", help="analyze note file")
    parser_analyze.add_argument("input", type=str, help="input note file")
    parser_analyze.add_argument(
        "--policy",
        choices=["strict", "loose"],
        default="strict",
        help="select parser policy",
    )
    parser_analyze.set_defaults(func=subcommand_analyze)

    # 'convert' subcommand
    parser_convert = subparsers.add_parser("convert", help="image conversion")
    parser_convert.add_argument("input", type=str, help="input note file")
    parser_convert.add_argument("output", type=str, help="output image file")
    parser_convert.add_argument(
        "-n", "--number", type=int, default=0, help="page number to be converted"
    )
    parser_convert.add_argument(
        "-a", "--all", action="store_true", default=False, help="convert all pages"
    )
    parser_convert.add_argument(
        "-c",
        "--color",
        type=str,
        help="colorize note with comma separated color codes in order of black, darkgray, gray and white.",
    )
    parser_convert.add_argument(
        "-t",
        "--type",
        choices=["png", "svg", "pdf", "txt"],
        default="png",
        help="select conversion file type",
    )
    parser_convert.add_argument(
        "--exclude-background",
        action="store_true",
        default=False,
        help="exclude background and make it transparent (PNG and SVG are supported)",
    )
    parser_convert.add_argument(
        "--pdf-type",
        choices=["original"],
        default="original",
        help="select PDF conversion type",
    )
    parser_convert.add_argument(
        "--no-link", action="store_true", default=False, help="disable links in PDF"
    )
    parser_convert.add_argument(
        "--add-keyword",
        action="store_true",
        default=False,
        help="enable keywords in PDF",
    )
    parser_convert.add_argument(
        "--text-page-separator",
        type=str,
        default="",
        help="page separator string for text conversion",
    )
    parser_convert.add_argument(
        "--policy",
        choices=["strict", "loose"],
        default="strict",
        help="select parser policy",
    )
    parser_convert.set_defaults(func=subcommand_convert)

    # 'merge' subcommand
    description = """
        (EXPERIMENTAL FEATURE)
        This command merge multiple note files to one.
        Backup your input files to save your data because you might get a corrupted output file.
        """
    parser_merge = subparsers.add_parser(
        "merge",
        description=description,
        help="merge multiple note files (EXPERIMENTAL FEATURE)",
    )
    parser_merge.add_argument("input", type=str, nargs="+", help="input note files")
    parser_merge.add_argument("output", type=str, help="output note file")
    parser_merge.set_defaults(func=subcommand_merge)

    # 'reconstruct' subcommand
    description = """
        (EXPERIMENTAL FEATURE)
        This command disassemble and reconstruct a note file for debugging and testing.
        Backup your input file to save your data because you might get a corrupted output file.
        """
    parser_reconstruct = subparsers.add_parser(
        "reconstruct",
        description=description,
        help="reconstruct a note file (EXPERIMENTAL FEATURE)",
    )
    parser_reconstruct.add_argument("input", type=str, help="input note file")
    parser_reconstruct.add_argument("output", type=str, help="output note file")
    parser_reconstruct.set_defaults(func=subcommand_reconstruct)

    # 'create' subcommand
    parser_create = subparsers.add_parser(
        "create",
        help="create or append a stylized or simulated-handwriting note file from Markdown",
    )
    parser_create.add_argument(
        "input",
        type=str,
        nargs="?",
        default=None,
        help="optional input Markdown file (use '-' for stdin)",
    )
    parser_create.add_argument("output", type=str, help="output note file")
    parser_create.add_argument(
        "-t",
        "--text",
        type=str,
        default=None,
        help="inline Markdown text to render when no input file is given",
    )
    parser_create.add_argument(
        "--style",
        choices=["stylized", "handwriting", "architect"],
        default="stylized",
        help="rendering visual style: editorial 'stylized', fluid 'handwriting', or draftsperson 'architect' (default: stylized)",
    )
    parser_create.add_argument(
        "--background",
        choices=["white", "dots", "ruled", "grid"],
        default="white",
        help="paper template background style (default: white)",
    )
    parser_create.add_argument(
        "--layer",
        choices=["BGLAYER", "MAINLAYER", "LAYER1", "LAYER2", "LAYER3"],
        default=None,
        help="target Supernote layer (defaults to BGLAYER for stylized, MAINLAYER for handwriting)",
    )
    parser_create.add_argument(
        "--hidden-layer-text",
        type=str,
        default=None,
        help="optional Markdown rendered onto hidden LAYER1 (toggleable on-device)",
    )
    parser_create.add_argument(
        "--hidden-layer-file",
        type=str,
        default=None,
        help="optional Markdown file rendered onto hidden LAYER1 (toggleable on-device)",
    )
    parser_create.add_argument(
        "--equipment",
        choices=["N6", "N5"],
        default=None,
        help="target device profile: N6 (1404x1872 Nomad) or N5 (1920x2560 Manta/A5X2); default: N6",
    )
    parser_create.add_argument(
        "--font",
        type=str,
        default=None,
        help="optional path to a custom .ttf/.otf font file",
    )
    parser_create.add_argument(
        "--font-size",
        type=int,
        default=None,
        help="optional base font size in pixels",
    )
    parser_create.add_argument(
        "--seed",
        type=int,
        default=0,
        help="random seed for deterministic simulated handwriting (default: 0)",
    )
    parser_create.add_argument(
        "--auto-toc",
        action="store_true",
        default=False,
        help="populate Supernote TOC Title blocks from Markdown headings",
    )
    parser_create.add_argument(
        "--no-keywords",
        action="store_true",
        default=False,
        help="disable extracting inline #hashtags as Supernote Keyword blocks",
    )
    parser_create.add_argument(
        "--append-to",
        type=str,
        default=None,
        help="append rendered pages onto an existing .note file instead of creating a new one",
    )
    parser_create.set_defaults(func=subcommand_create)
