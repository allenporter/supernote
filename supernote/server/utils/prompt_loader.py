"""Externalized Markdown prompt loader (`PromptLoader`) and notebook-stem prompt routing.

Loads built-in or user-overridden (`ServerConfig.prompts_dir` / `SUPERNOTE_PROMPTS_DIR`)
prompts for `ocr` (`PromptId.OCR_TRANSCRIPTION`) and `summary` (`PromptId.SUMMARY_GENERATION`).
When a notebook is processed, `PromptLoader.get_prompt` combines `common/*.md` with either
a matching `<notebook_stem>/*.md` directory (e.g. `daily/` for `Daily.note`) or `default/*.md`.
Used by `supernote.server.ai.prompts`. See `supernote.guides.mcp`.
"""

import enum
import importlib.resources
import logging
from importlib.resources.abc import Traversable
from pathlib import Path

logger = logging.getLogger(__name__)

RESOURCES_DIR = importlib.resources.files("supernote.server") / "resources" / "prompts"


class PromptId(str, enum.Enum):
    OCR_TRANSCRIPTION = "ocr_transcription"
    OCR_VOCABULARY = "ocr_vocabulary"
    IMAGE_TRANSCRIPTION = "image_transcription"
    TITLE_TRANSCRIPTION = "title_transcription"
    SUMMARY_GENERATION = "summary_generation"
    WIKI_COMPILE = "wiki_compile"
    WIKI_CONFLICT = "wiki_conflict"
    WIKI_LINT = "wiki_lint"


CATEGORY_MAP = {
    "ocr": PromptId.OCR_TRANSCRIPTION.value,
    "ocr_vocabulary": PromptId.OCR_VOCABULARY.value,
    "image": PromptId.IMAGE_TRANSCRIPTION.value,
    "title": PromptId.TITLE_TRANSCRIPTION.value,
    "summary": PromptId.SUMMARY_GENERATION.value,
    "wiki_compile": PromptId.WIKI_COMPILE.value,
    "wiki_conflict": PromptId.WIKI_CONFLICT.value,
    "wiki_lint": PromptId.WIKI_LINT.value,
}
COMMON = "common"
DEFAULT = "default"


class PromptLoader:
    """Service to load and manage externalized prompts."""

    def __init__(self, resources_dir: Path | Traversable | None = None) -> None:
        self._resources_dir = resources_dir
        # Map: prompt_id -> (type -> prompt_text)
        # type can be "common", "default", or specific custom types like "monthly"
        self._prompts: dict[str, dict[str, str]] | None = None

    def configure(self, resources_dir: Path | Traversable) -> None:
        """Configure the custom prompts directory.

        Clears loaded prompts to trigger reload on next get_prompt call.
        """
        self._resources_dir = resources_dir
        self._prompts = None

    @property
    def resources_dir(self) -> Path | Traversable:
        return self._resources_dir or RESOURCES_DIR

    def _load_prompts(self) -> None:
        """Load built-in prompts, then overlay any categories present in `resources_dir`."""
        self._prompts = {pid.value: {} for pid in PromptId}
        self._load_directory(RESOURCES_DIR)
        if self._resources_dir is not None and self._resources_dir != RESOURCES_DIR:
            self._load_directory(self._resources_dir)

    def _load_directory(self, directory: Path | Traversable) -> None:
        """Load prompt categories from `directory`, replacing each present category."""
        assert self._prompts is not None
        if not directory.is_dir():
            logger.warning(f"Prompts directory not found at {directory}")
            return

        try:
            for category, prompt_id in CATEGORY_MAP.items():
                category_dir = directory / category
                if not category_dir.is_dir():
                    continue

                category_prompts: dict[str, str] = {}

                common_dir = category_dir / COMMON
                if common_dir.is_dir():
                    common_text = self._read_prompts_from_dir(common_dir)
                    if common_text:
                        category_prompts[COMMON] = common_text

                default_dir = category_dir / DEFAULT
                if default_dir.is_dir():
                    default_text = self._read_prompts_from_dir(default_dir)
                    if default_text:
                        category_prompts[DEFAULT] = default_text

                for item in category_dir.iterdir():
                    if item.is_dir() and item.name not in [COMMON, DEFAULT]:
                        custom_type = item.name.lower()
                        custom_text = self._read_prompts_from_dir(item)
                        if custom_text:
                            category_prompts[custom_type] = custom_text

                self._prompts[prompt_id] = category_prompts

            logger.info(f"Loaded prompts from {directory}")

        except (OSError, UnicodeDecodeError) as e:
            logger.error(f"Failed to load prompts from {directory}: {e}")

    def _read_prompts_from_dir(self, directory: Path | Traversable) -> str:
        """Read and concatenate all .md files in a directory."""
        prompts = []
        # Use iterdir instead of glob for Traversable compatibility
        files = sorted(
            [f for f in directory.iterdir() if f.name.endswith(".md")],
            key=lambda x: x.name,
        )
        for file_path in files:
            if file_path.is_file():
                prompts.append(file_path.read_text(encoding="utf-8").strip())
        return "\n\n".join(prompts)

    def has_custom_prompt(self, prompt_id: PromptId, custom_type: str | None) -> bool:
        """Return True if a specific custom prompt directory exists for custom_type."""
        if not custom_type or custom_type in (COMMON, DEFAULT):
            return False
        if self._prompts is None:
            self._load_prompts()
        assert self._prompts is not None
        type_map = self._prompts.get(prompt_id, {})
        return custom_type.lower() in type_map

    def get_prompt(self, prompt_id: PromptId, custom_type: str | None = None) -> str:
        """Retrieve a prompt by its ID, optionally overridden by a custom type.

        Logic: Common + (Custom if exists else Default)
        """
        if self._prompts is None:
            self._load_prompts()

        assert self._prompts is not None

        if prompt_id not in self._prompts:
            raise ValueError(f"Prompt ID '{prompt_id}' not found.")

        type_map = self._prompts[prompt_id]

        parts = []

        # 1. Add Common
        if COMMON in type_map:
            parts.append(type_map[COMMON])

        # 2. Add Specific (Custom or Default)
        specific_prompt = None
        if custom_type and custom_type in type_map:
            logger.info(f"Using custom prompt '{custom_type}' for {prompt_id}")
            specific_prompt = type_map[custom_type]
        elif DEFAULT in type_map:
            specific_prompt = type_map[DEFAULT]

        if specific_prompt:
            parts.append(specific_prompt)
        elif not parts:
            # If no common and no specific/default, that's an issue
            raise ValueError(
                f"No prompt content found for '{prompt_id}' (Custom: {custom_type})"
            )

        return "\n\n".join(parts)


PROMPT_LOADER = PromptLoader()
