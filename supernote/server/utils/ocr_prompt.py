"""Library for building the OCR prompt for a notebook page."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .note_content import format_page_metadata
from .prompt_loader import PROMPT_LOADER, PromptId

__all__ = ["PageMetadata", "create_ocr_prompt"]


@dataclass
class PageMetadata:
    file_name: str | None
    page_index: int
    page_id: str
    notebook_create_time: int | None

    @property
    def file_name_basis(self) -> str | None:
        if self.file_name:
            return Path(self.file_name).stem.lower()
        return None


def create_ocr_prompt(page_metadata: PageMetadata) -> str:
    """Build the OCR prompt: page metadata followed by the transcription instructions."""
    prompt = PROMPT_LOADER.get_prompt(
        PromptId.OCR_TRANSCRIPTION, custom_type=page_metadata.file_name_basis
    )

    metadata_block = format_page_metadata(
        page_index=page_metadata.page_index or 0,
        page_id=page_metadata.page_id,
        file_name=page_metadata.file_name,
        notebook_create_time=page_metadata.notebook_create_time,
        include_section_divider=True,
    )
    return f"{metadata_block}\n\n{prompt}"
