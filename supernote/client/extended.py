"""Client for Extended (Web) APIs."""

from supernote.models.extended import (
    WebSearchRequestDTO,
    WebSearchResponseVO,
    WebSummaryListRequestDTO,
    WebSummaryListVO,
)

from .client import Client


class ExtendedClient:
    """Client for Server Extension APIs."""

    def __init__(self, client: Client):
        """Initialize the extended client."""
        self._client = client

    async def list_summaries(self, file_id: int) -> WebSummaryListVO:
        """List summaries for a file (Extension)."""
        dto = WebSummaryListRequestDTO(file_id=file_id)
        return await self._client.post_json(
            "/api/extended/file/summary/list", WebSummaryListVO, json=dto.to_dict()
        )

    async def search(
        self,
        query: str,
        top_n: int = 5,
        name_filter: str | None = None,
        date_after: str | None = None,
        date_before: str | None = None,
    ) -> WebSearchResponseVO:
        """Perform a semantic search across notebooks (Extension)."""
        dto = WebSearchRequestDTO(
            query=query,
            top_n=top_n,
            name_filter=name_filter,
            date_after=date_after,
            date_before=date_before,
        )
        return await self._client.post_json(
            "/api/extended/search", WebSearchResponseVO, json=dto.to_dict()
        )
