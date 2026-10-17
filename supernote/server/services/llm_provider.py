"""Selects the `LLMService` backend from server configuration."""

import logging

from supernote.server.config import ServerConfig
from supernote.server.services.gemini import GeminiService
from supernote.server.services.llm import LLMService
from supernote.server.services.openai_compatible import OpenAICompatibleService

__all__ = ["create_llm_service"]

logger = logging.getLogger(__name__)


def create_llm_service(config: ServerConfig) -> LLMService:
    """Create the model backend named by `config.llm_provider`."""
    provider = config.llm_provider.strip().lower()
    if provider == "gemini":
        return GeminiService(
            config.gemini_api_key,
            generation_model=config.gemini_ocr_model,
            embedding_model=config.gemini_embedding_model,
            max_concurrency=config.gemini_max_concurrency,
        )
    if provider == "openai":
        service = OpenAICompatibleService(
            base_url=config.openai_base_url,
            generation_model=config.openai_model,
            embedding_model=config.openai_embedding_model,
            api_key=config.openai_api_key,
            embedding_base_url=config.openai_embedding_base_url,
            max_concurrency=config.openai_max_concurrency,
        )
        if not service.is_configured:
            logger.warning(
                "llm_provider is 'openai' but openai_base_url, openai_model or "
                "openai_embedding_model is not set; AI processing is disabled"
            )
        return service
    raise ValueError(
        f"Unknown llm_provider {config.llm_provider!r}; expected 'gemini' or 'openai'"
    )
