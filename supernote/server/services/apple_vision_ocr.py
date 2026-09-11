import logging

import aiohttp

logger = logging.getLogger(__name__)


class AppleVisionOcrService:
    """Shared service for interacting with the visionocr-service microservice."""

    def __init__(self, base_url: str | None) -> None:
        self.base_url = base_url

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)

    async def extract_text(self, image_bytes: bytes) -> str:
        """Extract text from an image via the visionocr-service's `/ocr` endpoint."""
        if not self.base_url:
            raise ValueError("Apple Vision OCR base URL not configured")

        url = f"{self.base_url}/ocr"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=image_bytes) as response:
                if response.status != 200:
                    body = await response.text()
                    raise ValueError(
                        f"Apple Vision OCR request failed with status "
                        f"{response.status}: {body}"
                    )
                data = await response.json()

        return data.get("text", "")
