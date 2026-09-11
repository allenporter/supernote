import logging

import aiohttp

logger = logging.getLogger(__name__)


class OllamaService:
    """Shared service for interacting with a self-hosted Ollama instance."""

    def __init__(self, base_url: str | None, model: str) -> None:
        self.base_url = base_url
        self.model = model

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding for the given text via Ollama's `/api/embed`."""
        if not self.base_url:
            raise ValueError("Ollama base URL not configured")

        url = f"{self.base_url}/api/embed"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json={"model": self.model, "input": text}
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    raise ValueError(
                        f"Ollama embedding request failed with status "
                        f"{response.status}: {body}"
                    )
                data = await response.json()

        embeddings = data.get("embeddings")
        if not embeddings:
            raise ValueError(f"No embeddings returned from Ollama: {data}")

        return embeddings[0]
