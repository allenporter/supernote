"""Tests for supernote.cli.notebook."""

import argparse
import io
import json
from pathlib import Path

import pytest

from supernote.cli.notebook import (
    add_parser,
    parse_color,
    subcommand_analyze,
    subcommand_convert,
    subcommand_create,
    subcommand_merge,
    subcommand_reconstruct,
)
from supernote.notebook import load_notebook


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


def test_subcommand_convert_txt_single(test_data_dir: Path, tmp_path: Path):
    rtr_note = test_data_dir / "philips" / "rtr.note"
    out_file = tmp_path / "output.txt"
    args = argparse.Namespace(
        input=str(rtr_note),
        output=str(out_file),
        number=0,
        all=False,
        type="txt",
        color=None,
        policy="strict",
    )
    subcommand_convert(args)
    assert out_file.exists()
    assert "Real paragraph test recognition time" in out_file.read_text()


def test_subcommand_convert_txt_all(test_data_dir: Path, tmp_path: Path):
    rtr_note = test_data_dir / "philips" / "rtr.note"
    out_file = tmp_path / "output.txt"
    args = argparse.Namespace(
        input=str(rtr_note),
        output=str(out_file),
        number=0,
        all=True,
        type="txt",
        color=None,
        text_page_separator="--PAGE--",
        policy="strict",
    )
    subcommand_convert(args)
    assert out_file.exists()
    assert "Real paragraph test recognition time" in out_file.read_text()


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


def test_subcommand_reconstruct(test_data_dir: Path, tmp_path: Path):
    latest_note = test_data_dir / "dsummersl" / "sn2md_20260618.note"
    out_file = tmp_path / "reconstructed.note"
    args = argparse.Namespace(input=str(latest_note), output=str(out_file))
    subcommand_reconstruct(args)
    assert out_file.exists()
    assert out_file.stat().st_size > 0


def test_subcommand_merge_single(test_data_dir: Path, tmp_path: Path):
    latest_note = test_data_dir / "dsummersl" / "sn2md_20260618.note"
    out_file = tmp_path / "merged.note"
    args = argparse.Namespace(input=[str(latest_note)], output=str(out_file))
    subcommand_merge(args)
    assert out_file.exists()
    assert out_file.stat().st_size > 0


def test_subcommand_merge_multiple(test_data_dir: Path, tmp_path: Path):
    latest_note = test_data_dir / "dsummersl" / "sn2md_20260618.note"
    out_file = tmp_path / "merged_multi.note"
    args = argparse.Namespace(
        input=[str(latest_note), str(latest_note)], output=str(out_file)
    )
    subcommand_merge(args)
    assert out_file.exists()
    assert out_file.stat().st_size > 0


def test_subcommand_create_and_append(tmp_path: Path) -> None:
    md_file = tmp_path / "doc.md"
    md_file.write_text(
        "# CLI Notebook\n\n- [x] First task #cli\n\n---\n\n## Second Page\n\nBody text.",
        encoding="utf-8",
    )
    out_note = tmp_path / "created.note"

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    args = parser.parse_args(
        [
            "create",
            str(md_file),
            str(out_note),
            "--style",
            "handwriting",
            "--background",
            "ruled",
            "--hidden-layer-text",
            "## Hidden Hint\n\nSecret note",
            "--auto-toc",
            "--seed",
            "11",
        ]
    )
    assert args.func == subcommand_create
    args.func(args)
    assert out_note.exists()

    nb = load_notebook(str(out_note))
    assert nb.total_pages == 2
    assert len(nb.titles) == 2
    assert [k.keyword for k in nb.keywords] == ["cli"]

    appended_note = tmp_path / "appended.note"
    append_args = parser.parse_args(
        [
            "create",
            str(appended_note),
            "--append-to",
            str(out_note),
            "--text",
            "# Third Page\n\nAppended via CLI!",
            "--style",
            "stylized",
        ]
    )
    append_args.func(append_args)
    nb_appended = load_notebook(str(appended_note))
    assert nb_appended.total_pages == 3

    out_png = tmp_path / "rendered.png"
    conv_args = parser.parse_args(
        ["convert", str(appended_note), str(out_png), "-n", "2"]
    )
    conv_args.func(conv_args)
    assert out_png.exists()


def test_subcommand_create_stdin_blank_and_hidden_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    blank_note = tmp_path / "blank.note"
    blank_args = parser.parse_args(["create", str(blank_note), "--background", "grid"])
    blank_args.func(blank_args)
    assert load_notebook(str(blank_note)).total_pages == 1

    hidden_md_file = tmp_path / "hidden.md"
    hidden_md_file.write_text("### Overlay\n- Answer key", encoding="utf-8")
    stdin_note = tmp_path / "stdin.note"
    monkeypatch.setattr("sys.stdin", io.StringIO("# From Stdin\n\nHello"))
    stdin_args = parser.parse_args(
        [
            "create",
            "-",
            str(stdin_note),
            "--hidden-layer-file",
            str(hidden_md_file),
        ]
    )
    stdin_args.func(stdin_args)
    assert load_notebook(str(stdin_note)).total_pages == 1


@pytest.mark.parametrize(
    ("cli_argv", "expected_code", "expected_err"),
    [
        (
            ["create", "in.md", "out.note", "--text", "conflict"],
            2,
            "cannot specify both positional 'input' and '--text'",
        ),
        (
            [
                "create",
                "out.note",
                "--hidden-layer-text",
                "a",
                "--hidden-layer-file",
                "b.md",
            ],
            2,
            "cannot specify both '--hidden-layer-text' and '--hidden-layer-file'",
        ),
        (
            [
                "create",
                "out.note",
                "--append-to",
                "existing.note",
                "--equipment",
                "N5",
            ],
            2,
            "cannot override '--equipment' when using '--append-to'",
        ),
        (
            ["create", "out.note", "--font-size", "0"],
            2,
            "'--font-size' must be positive",
        ),
        (
            ["create", "out.note", "--font", "/nonexistent/font.ttf"],
            1,
            "font file not found",
        ),
        (
            ["create", "/nonexistent/in.md", "out.note"],
            1,
            "input file not found",
        ),
    ],
)
def test_subcommand_create_rejects_conflicting_or_missing_inputs(
    cli_argv: list[str],
    expected_code: int,
    expected_err: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    parsed = parser.parse_args(cli_argv)
    with pytest.raises(SystemExit) as exc_info:
        parsed.func(parsed)
    assert exc_info.value.code == expected_code
    assert expected_err in capsys.readouterr().err
