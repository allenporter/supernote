"""Tests for supernote.cli.notebook."""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from supernote.cli.notebook import (
    add_parser,
    parse_color,
    subcommand_analyze,
    subcommand_convert,
    subcommand_merge,
    subcommand_reconstruct,
)


def test_parse_color_valid():
    colors = parse_color("#000000,#444444,#888888,#ffffff")
    assert colors == (0x000000, 0x444444, 0x888888, 0xFFFFFF)


def test_parse_color_invalid_count():
    with pytest.raises(ValueError) as exc_info:
        parse_color("#000000,#ffffff")
    assert "4 colors are required" in str(exc_info.value)


def test_add_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    # Test analyze subparser
    parsed = parser.parse_args(["analyze", "input.note", "--policy", "loose"])
    assert parsed.command == "analyze"
    assert parsed.input == "input.note"
    assert parsed.policy == "loose"
    assert parsed.func == subcommand_analyze

    # Test convert subparser
    parsed = parser.parse_args(
        [
            "convert",
            "input.note",
            "output.png",
            "-t",
            "png",
            "-a",
            "--exclude-background",
        ]
    )
    assert parsed.command == "convert"
    assert parsed.type == "png"
    assert parsed.all is True
    assert parsed.exclude_background is True
    assert parsed.func == subcommand_convert

    # Test merge subparser
    parsed = parser.parse_args(["merge", "file1.note", "file2.note", "out.note"])
    assert parsed.command == "merge"
    assert parsed.input == ["file1.note", "file2.note"]
    assert parsed.output == "out.note"
    assert parsed.func == subcommand_merge

    # Test reconstruct subparser
    parsed = parser.parse_args(["reconstruct", "file.note", "out.note"])
    assert parsed.command == "reconstruct"
    assert parsed.input == "file.note"
    assert parsed.output == "out.note"
    assert parsed.func == subcommand_reconstruct


def test_subcommand_analyze(test_note_path: Path, capsys):
    args = argparse.Namespace(input=str(test_note_path), policy="strict")
    subcommand_analyze(args)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, dict)


def test_subcommand_convert_png_single_page(test_note_path: Path, tmp_path: Path):
    out_file = tmp_path / "output.png"
    args = argparse.Namespace(
        input=str(test_note_path),
        output=str(out_file),
        number=0,
        all=False,
        type="png",
        color=None,
        exclude_background=False,
        policy="strict",
    )
    subcommand_convert(args)
    assert out_file.exists()


def test_subcommand_convert_png_all_pages(test_note_path: Path, tmp_path: Path):
    out_file = tmp_path / "output.png"
    args = argparse.Namespace(
        input=str(test_note_path),
        output=str(out_file),
        number=0,
        all=True,
        type="png",
        color=None,
        exclude_background=True,
        policy="strict",
    )
    subcommand_convert(args)
    created_files = list(tmp_path.glob("output*.png"))
    assert len(created_files) > 0


def test_subcommand_convert_svg(test_note_path: Path, tmp_path: Path):
    out_file = tmp_path / "output.svg"
    args = argparse.Namespace(
        input=str(test_note_path),
        output=str(out_file),
        number=0,
        all=False,
        type="svg",
        color=None,
        exclude_background=False,
        policy="strict",
    )
    subcommand_convert(args)
    assert out_file.exists()


def test_subcommand_convert_svg_all(test_note_path: Path, tmp_path: Path):
    out_file = tmp_path / "output.svg"
    args = argparse.Namespace(
        input=str(test_note_path),
        output=str(out_file),
        number=0,
        all=True,
        type="svg",
        color=None,
        exclude_background=False,
        policy="strict",
    )
    subcommand_convert(args)
    created_files = list(tmp_path.glob("output*.svg"))
    assert len(created_files) > 0


def test_subcommand_convert_pdf(test_note_path: Path, tmp_path: Path):
    out_file = tmp_path / "output.pdf"
    args = argparse.Namespace(
        input=str(test_note_path),
        output=str(out_file),
        number=0,
        all=False,
        type="pdf",
        color=None,
        no_link=True,
        add_keyword=True,
        policy="strict",
    )
    subcommand_convert(args)
    assert out_file.exists()


def test_subcommand_convert_pdf_all(test_note_path: Path, tmp_path: Path):
    out_file = tmp_path / "output.pdf"
    args = argparse.Namespace(
        input=str(test_note_path),
        output=str(out_file),
        number=0,
        all=True,
        type="pdf",
        color=None,
        no_link=False,
        add_keyword=False,
        policy="strict",
    )
    subcommand_convert(args)
    assert out_file.exists()


def test_subcommand_convert_txt_single(test_note_path: Path, tmp_path: Path):
    out_file = tmp_path / "output.txt"
    args = argparse.Namespace(
        input=str(test_note_path),
        output=str(out_file),
        number=0,
        all=False,
        type="txt",
        color=None,
        policy="strict",
    )
    with patch(
        "supernote.cli.notebook.TextConverter.convert", return_value="Sample text"
    ):
        subcommand_convert(args)
        assert out_file.exists()
        assert out_file.read_text() == "Sample text"


def test_subcommand_convert_txt_all(test_note_path: Path, tmp_path: Path):
    out_file = tmp_path / "output.txt"
    args = argparse.Namespace(
        input=str(test_note_path),
        output=str(out_file),
        number=0,
        all=True,
        type="txt",
        color=None,
        text_page_separator="--PAGE--",
        policy="strict",
    )
    with patch(
        "supernote.cli.notebook.TextConverter.convert", return_value="Page text"
    ):
        subcommand_convert(args)
        assert out_file.exists()
        assert "Page text" in out_file.read_text()


def test_subcommand_convert_with_color(test_note_path: Path, tmp_path: Path):
    out_file = tmp_path / "output.png"
    args = argparse.Namespace(
        input=str(test_note_path),
        output=str(out_file),
        number=0,
        all=False,
        type="png",
        color="#000000,#444444,#888888,#ffffff",
        exclude_background=False,
        policy="strict",
    )
    subcommand_convert(args)
    assert out_file.exists()


def test_subcommand_convert_invalid_color(test_note_path: Path, capsys):
    args = argparse.Namespace(
        input=str(test_note_path),
        output="out.png",
        number=0,
        all=False,
        type="png",
        color="invalid_color",
        exclude_background=False,
        policy="strict",
    )
    with pytest.raises(SystemExit) as exc_info:
        subcommand_convert(args)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "4 colors are required" in captured.err


def test_subcommand_reconstruct(test_note_path: Path, tmp_path: Path):
    out_file = tmp_path / "reconstructed.note"
    args = argparse.Namespace(input=str(test_note_path), output=str(out_file))
    with patch(
        "supernote.cli.notebook.reconstruct", return_value=b"reconstructed_data"
    ):
        subcommand_reconstruct(args)
        assert out_file.exists()
        assert out_file.read_bytes() == b"reconstructed_data"


def test_subcommand_merge_single(test_note_path: Path, tmp_path: Path):
    out_file = tmp_path / "merged.note"
    args = argparse.Namespace(input=[str(test_note_path)], output=str(out_file))
    with patch("supernote.cli.notebook.reconstruct", return_value=b"merged_data"):
        subcommand_merge(args)
        assert out_file.exists()
        assert out_file.read_bytes() == b"merged_data"


def test_subcommand_merge_multiple(test_note_path: Path, tmp_path: Path):
    out_file = tmp_path / "merged_multi.note"
    args = argparse.Namespace(
        input=[str(test_note_path), str(test_note_path)], output=str(out_file)
    )
    with patch("supernote.cli.notebook.merge", return_value=b"merged_multi_data"):
        subcommand_merge(args)
        assert out_file.exists()
        assert out_file.read_bytes() == b"merged_multi_data"
