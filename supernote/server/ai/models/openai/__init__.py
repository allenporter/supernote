"""OpenAI-compatible model implementations.

Works with OpenAI itself and with any server implementing the same HTTP API,
such as Ollama, llama.cpp, vLLM or LM Studio, configured via
`ai.providers.openai.base_url`.
"""

__all__ = [
    "backend",
    "embedding",
    "ocr",
    "summary",
]
