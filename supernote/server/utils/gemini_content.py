"""Library for preparing Gemini Content requests."""

from dataclasses import dataclass
from pathlib import Path

from google.genai import types

from .note_content import format_page_metadata
from .prompt_loader import PROMPT_LOADER, PromptId


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


def create_gemini_content(
    page_metadata: PageMetadata,
    png_data: bytes,
) -> list[types.Part]:
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
    prompt = f"{metadata_block}\n\n{prompt}"

    return [
        types.Part.from_text(text=prompt),
        types.Part.from_bytes(data=png_data, mime_type="image/png"),
    ]
