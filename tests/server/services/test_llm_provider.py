from pathlib import Path

import pytest

from supernote.server.config import AuthConfig, ServerConfig
from supernote.server.services.gemini import GeminiService
from supernote.server.services.llm_provider import create_llm_service
from supernote.server.services.openai_compatible import OpenAICompatibleService


@pytest.fixture
def config(tmp_path: Path) -> ServerConfig:
    return ServerConfig(auth=AuthConfig(secret_key="secret"), storage_dir=str(tmp_path))


def test_default_is_gemini(config: ServerConfig) -> None:
    service = create_llm_service(config)
    assert isinstance(service, GeminiService)
    assert not service.is_configured
    assert service.generation_model == config.gemini_ocr_model


def test_openai(config: ServerConfig) -> None:
    config.llm_provider = "OpenAI"
    config.openai_base_url = "http://localhost:11434/v1"
    config.openai_model = "gemma-vision"
    config.openai_embedding_model = "nomic-embed-text"

    service = create_llm_service(config)

    assert isinstance(service, OpenAICompatibleService)
    assert service.is_configured
    assert service.generation_model == "gemma-vision"
    assert service.max_concurrency == 1


def test_openai_incomplete_config(config: ServerConfig) -> None:
    config.llm_provider = "openai"
    config.openai_base_url = "http://localhost:11434/v1"

    service = create_llm_service(config)

    assert isinstance(service, OpenAICompatibleService)
    assert not service.is_configured


def test_unknown_provider(config: ServerConfig) -> None:
    config.llm_provider = "other"
    with pytest.raises(ValueError, match="Unknown llm_provider 'other'"):
        create_llm_service(config)
