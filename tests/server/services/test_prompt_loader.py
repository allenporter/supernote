from pathlib import Path

import pytest

from supernote.server.utils.prompt_loader import PromptId, PromptLoader


@pytest.fixture
def mock_resources_dir(tmp_path: Path) -> Path:
    """Create a mock resources directory structure."""
    resources_dir = tmp_path / "resources"
    prompts_dir = resources_dir / "prompts"
    prompts_dir.mkdir(parents=True)

    # 1. OCR Category setup
    ocr_dir = prompts_dir / "ocr"
    ocr_dir.mkdir(parents=True)

    # Common
    (ocr_dir / "common").mkdir()
    (ocr_dir / "common" / "base.md").write_text("Common OCR Base", encoding="utf-8")

    # Default
    (ocr_dir / "default").mkdir()
    (ocr_dir / "default" / "ocr_transcription.md").write_text(
        "Default Ocr", encoding="utf-8"
    )

    # Custom type_a
    (ocr_dir / "type_a").mkdir()
    (ocr_dir / "type_a" / "custom1.md").write_text("Custom A", encoding="utf-8")

    # 2. Summary Category setup (No common)
    summary_dir = prompts_dir / "summary"
    summary_dir.mkdir(parents=True)

    # Default
    (summary_dir / "default").mkdir()
    (summary_dir / "default" / "summary_generation.md").write_text(
        "Default Summary", encoding="utf-8"
    )

    return prompts_dir


def test_get_prompt_ocr_default(mock_resources_dir: Path) -> None:
    """Test OCR: Has Common + Default"""
    loader = PromptLoader(resources_dir=mock_resources_dir)
    prompt = loader.get_prompt(PromptId.OCR_TRANSCRIPTION)
    assert prompt == "Common OCR Base\n\nDefault Ocr"


def test_get_prompt_ocr_custom(mock_resources_dir: Path) -> None:
    """Test OCR: Has Common + Custom"""
    loader = PromptLoader(resources_dir=mock_resources_dir)
    prompt = loader.get_prompt(PromptId.OCR_TRANSCRIPTION, custom_type="type_a")
    assert prompt == "Common OCR Base\n\nCustom A"


def test_get_prompt_ocr_fallback(mock_resources_dir: Path) -> None:
    """Test OCR: Custom type missing -> Fallback to Common + Default"""
    loader = PromptLoader(resources_dir=mock_resources_dir)
    prompt = loader.get_prompt(PromptId.OCR_TRANSCRIPTION, custom_type="unknown_type")
    assert prompt == "Common OCR Base\n\nDefault Ocr"


def test_get_prompt_summary(mock_resources_dir: Path) -> None:
    """Test Summary: No Common, only Default"""
    loader = PromptLoader(resources_dir=mock_resources_dir)
    prompt = loader.get_prompt(PromptId.SUMMARY_GENERATION)
    assert prompt == "Default Summary"
