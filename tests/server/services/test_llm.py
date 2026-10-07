from supernote.server.services.gemini import GeminiService
from supernote.server.services.llm import LLMError, LLMService
from supernote.server.services.openai_compatible import OpenAICompatibleService


def test_llm_error_is_runtime_error() -> None:
    """Callers catch RuntimeError for backend failures."""
    assert issubclass(LLMError, RuntimeError)


def test_backends_implement_protocol() -> None:
    """Both backends satisfy the LLMService protocol (checked by the type checker)."""
    services: list[LLMService] = [
        GeminiService(api_key=None, generation_model="g", embedding_model="e"),
        OpenAICompatibleService(
            base_url="http://localhost/v1", generation_model="g", embedding_model="e"
        ),
    ]
    assert [service.generation_model for service in services] == ["g", "g"]
