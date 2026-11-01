"""Provider-neutral prompts and structured output schemas for AI tasks."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mashumaro.jsonschema import build_json_schema
from mashumaro.mixins.json import DataClassJSONMixin

from supernote.server.ai.base import AIError
from supernote.server.utils.note_content import format_page_metadata
from supernote.server.utils.prompt_loader import PROMPT_LOADER, PromptId, PromptLoader

__all__ = [
    "PageMetadata",
    "SummaryResponse",
    "SummarySegment",
    "format_ocr_prompt",
    "format_summary_prompt",
    "get_summary_json_schema",
    "parse_summary_response",
]

# Both halves are needed: preferring a listed spelling fixes names a model has
# no prior for, and the second sentence stops the list becoming a source of
# inserted words.
_VOCABULARY_CLAUSE = (
    "These names and terms may appear in the text: {terms}. "
    "If a handwritten word closely matches one of them, prefer that spelling. "
    "Never insert one of these terms where the handwriting does not support it."
)

_CODE_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n?```\s*$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """Remove a Markdown code fence that some models wrap JSON output in."""
    match = _CODE_FENCE.match(text.strip())
    return match.group(1) if match else text


@dataclass
class PageMetadata:
    """Metadata about a notebook page used to contextualize OCR transcription."""

    file_name: str | None
    page_index: int
    page_id: str
    notebook_create_time: int | None

    @property
    def file_name_basis(self) -> str | None:
        if self.file_name:
            return Path(self.file_name).stem.lower()
        return None


@dataclass
class SummarySegment(DataClassJSONMixin):
    """A single time-based summary segment extracted from a notebook transcript."""

    date_range: str = field(
        metadata={
            "description": "The date range covered by this segment (e.g., '2023-10-27', 'Week of Oct 27')."
        }
    )
    summary: str = field(
        metadata={
            "description": "A concise summary of the events, tasks, and notes for this period."
        }
    )
    extracted_dates: list[str] = field(
        metadata={
            "description": "List of specific dates derived from the content in ISO 8601 format (YYYY-MM-DD)."
        }
    )
    page_refs: list[int] = field(
        metadata={
            "description": "List of 1-indexed page numbers typically found in the text as '--- Page X ---'."
        }
    )


@dataclass
class SummaryResponse(DataClassJSONMixin):
    """Structured output schema for notebook summarization."""

    segments: list[SummarySegment] = field(
        metadata={
            "description": "List of summary segments extracted from the transcript."
        }
    )


def format_ocr_prompt(
    page_metadata: PageMetadata,
    *,
    custom_type: str | None = None,
    vocabulary: Sequence[str] = (),
    prompt_loader: PromptLoader = PROMPT_LOADER,
) -> str:
    """Format the full OCR prompt including page metadata header and template.

    `vocabulary` lists spellings the writer uses, nearest scope first.
    """
    resolved_custom_type = (
        custom_type if custom_type is not None else page_metadata.file_name_basis
    )
    prompt = prompt_loader.get_prompt(
        PromptId.OCR_TRANSCRIPTION, custom_type=resolved_custom_type
    )
    metadata_block = format_page_metadata(
        page_index=page_metadata.page_index or 0,
        page_id=page_metadata.page_id,
        file_name=page_metadata.file_name,
        notebook_create_time=page_metadata.notebook_create_time,
        include_section_divider=True,
    )
    if not vocabulary:
        return f"{metadata_block}\n\n{prompt}"
    clause = _VOCABULARY_CLAUSE.format(terms=", ".join(vocabulary))
    return f"{metadata_block}\n\n{prompt}\n\n{clause}"


def format_summary_prompt(
    transcript: str,
    *,
    custom_type: str | None = None,
    prompt_loader: PromptLoader = PROMPT_LOADER,
) -> str:
    """Format the full summarization prompt for an aggregated notebook transcript."""
    prompt_template = prompt_loader.get_prompt(
        PromptId.SUMMARY_GENERATION, custom_type=custom_type
    )
    return f"{prompt_template}\n\nTRANSCRIPT:\n{transcript}"


def get_summary_json_schema() -> dict[str, Any]:
    """Return the JSON schema dictionary for `SummaryResponse`."""
    return build_json_schema(SummaryResponse).to_dict()


def parse_summary_response(text: str | None) -> SummaryResponse:
    """Parse raw model JSON text into a `SummaryResponse`, raising `AIError` on invalid output."""
    if not text or not text.strip():
        return SummaryResponse(segments=[])
    try:
        data = json.loads(_strip_code_fence(text))
        return SummaryResponse.from_dict(data)
    except (ValueError, TypeError, LookupError) as err:
        raise AIError(f"Failed to parse summary JSON response: {err}") from err
