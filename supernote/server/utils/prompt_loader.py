import enum
import importlib.resources
import logging
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Dict, Optional, Union

logger = logging.getLogger(__name__)

RESOURCES_DIR = importlib.resources.files("supernote.server") / "resources" / "prompts"


class PromptId(str, enum.Enum):
    OCR_TRANSCRIPTION = "ocr_transcription"
    SUMMARY_GENERATION = "summary_generation"


CATEGORY_MAP = {
    "ocr": PromptId.OCR_TRANSCRIPTION.value,
    "summary": PromptId.SUMMARY_GENERATION.value,
}
COMMON = "common"
DEFAULT = "default"


class PromptLoader:
    """Service to load and manage externalized prompts."""

    def __init__(
        self, resources_dir: Optional[Union[Path, Traversable]] = None
    ) -> None:
        self.resources_dir = resources_dir or RESOURCES_DIR
        # Map: prompt_id -> (type -> prompt_text)
        # type can be "common", "default", or specific custom types like "monthly"
        self.prompts: Dict[str, Dict[str, str]] = {}
        self._load_prompts()

    def _load_prompts(self) -> None:
        """Load all prompts from the resources directory into memory."""
        if not self.resources_dir.is_dir():
            logger.warning(f"Prompts directory not found at {self.resources_dir}")
            return

        # Initialize dicts for known prompt IDs
        for pid in PromptId:
            self.prompts[pid.value] = {}

        try:
            # Map categories to PromptId
            for category, prompt_id in CATEGORY_MAP.items():
                category_dir = self.resources_dir / category
                if not category_dir.is_dir():
                    continue

                if prompt_id not in self.prompts:
                    self.prompts[prompt_id] = {}

                # 1. Load Common Prompts (Always On)
                common_dir = category_dir / COMMON
                if common_dir.is_dir():
                    common_text = self._read_prompts_from_dir(common_dir)
                    if common_text:
                        self.prompts[prompt_id][COMMON] = common_text

                # 2. Load Default Prompts
                default_dir = category_dir / DEFAULT
                if default_dir.is_dir():
                    default_text = self._read_prompts_from_dir(default_dir)
                    if default_text:
                        self.prompts[prompt_id][DEFAULT] = default_text

                # 3. Load Custom Prompts (sub-directories)
                for item in category_dir.iterdir():
                    if item.is_dir() and item.name not in [COMMON, DEFAULT]:
                        custom_type = item.name.lower()
                        custom_text = self._read_prompts_from_dir(item)
                        if custom_text:
                            self.prompts[prompt_id][custom_type] = custom_text

            logger.info(f"Loaded prompts from {self.resources_dir}")

        except Exception as e:
            logger.error(f"Failed to load prompts from {self.resources_dir}: {e}")

    def _read_prompts_from_dir(self, directory: Union[Path, Traversable]) -> str:
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

    def get_prompt(self, prompt_id: PromptId, custom_type: Optional[str] = None) -> str:
        """Retrieve a prompt by its ID, optionally overridden by a custom type.

        Logic: Common + (Custom if exists else Default)
        """
        if prompt_id not in self.prompts:
            raise ValueError(f"Prompt ID '{prompt_id}' not found.")

        type_map = self.prompts[prompt_id]

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
