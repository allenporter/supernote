import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

RESOURCES_DIR = Path(__file__).parent.parent / "resources" / "prompts"


class PromptLoader:
    """Service to load and manage externalized prompts."""

    def __init__(self, resources_dir: Optional[Path] = None) -> None:
        self.resources_dir = resources_dir or RESOURCES_DIR
        self.prompts: Dict[str, str] = {}
        self._load_prompts()

    def _load_prompts(self) -> None:
        """Load prompts from the markdown files in the prompts directory."""
        if not self.resources_dir.exists():
            logger.warning(f"Prompts directory not found at {self.resources_dir}")
            return

        try:
            for file_path in self.resources_dir.glob("*.md"):
                if file_path.is_file():
                    key = file_path.stem
                    prompt_text = file_path.read_text(encoding="utf-8").strip()
                    self.prompts[key] = prompt_text
            logger.info(f"Loaded {len(self.prompts)} prompts from {self.resources_dir}")
        except Exception as e:
            logger.error(f"Failed to load prompts from {self.resources_dir}: {e}")

    def get_prompt(self, prompt_id: str) -> str:
        """Retrieve a prompt by its ID."""
        if prompt_id not in self.prompts:
            raise ValueError(f"Prompt '{prompt_id}' not found in {self.resources_dir}.")
        return self.prompts[prompt_id]


PROMPT_LOADER = PromptLoader()
