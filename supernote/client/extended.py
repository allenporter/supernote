"""Client for Extended (Web) APIs."""

from supernote.models.extended import (
    DomainEventVO,
    EventFeedListVO,
    FileProcessingStatusDTO,
    FileProcessingStatusVO,
    SystemTaskListVO,
    WebAiStatusVO,
    WebNoteCoverRequestDTO,
    WebNoteCoverVO,
    WebSearchRequestDTO,
    WebSearchResponseVO,
    WebSummaryListRequestDTO,
    WebSummaryListVO,
    WebTranscriptRequestDTO,
    WebTranscriptResponseVO,
)

from .client import Client

__all__ = ["DomainEventVO", "EventFeedListVO", "ExtendedClient"]


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

    async def get_transcript(
        self,
        file_id: int,
        start_index: int | None = None,
        end_index: int | None = None,
    ) -> WebTranscriptResponseVO:
        """Retrieve a notebook transcript (Extension)."""
        dto = WebTranscriptRequestDTO(
            file_id=file_id,
            start_index=start_index,
            end_index=end_index,
        )
        return await self._client.post_json(
            "/api/extended/transcript", WebTranscriptResponseVO, json=dto.to_dict()
        )

    async def get_processing_status(
        self, file_ids: list[int]
    ) -> FileProcessingStatusVO:
        """Query processing status of files (Extension)."""
        dto = FileProcessingStatusDTO(file_ids=file_ids)
        return await self._client.post_json(
            "/api/extended/file/processing/status",
            FileProcessingStatusVO,
            json=dto.to_dict(),
        )

    async def list_system_tasks(self) -> SystemTaskListVO:
        """List recent system tasks (Extension)."""
        return await self._client.get_json(
            "/api/extended/system/tasks", SystemTaskListVO
        )

    async def get_ai_status(self) -> WebAiStatusVO:
        """Query server AI processing configuration and status (Extension)."""
        return await self._client.get_json("/api/extended/ai/status", WebAiStatusVO)

    async def get_note_cover(self, file_id: int) -> WebNoteCoverVO:
        """Retrieve a single-page cover preview URL for a notebook (Extension)."""
        dto = WebNoteCoverRequestDTO(file_id=file_id)
        return await self._client.post_json(
            "/api/extended/file/note/cover", WebNoteCoverVO, json=dto.to_dict()
        )

    async def list_events(
        self,
        *,
        cursor: str = "0",
        types: list[str] | None = None,
        file_id: int | None = None,
        exclude_actor: str | None = None,
        limit: int = 200,
    ) -> EventFeedListVO:
        """List per-user domain events after `cursor` (Extension)."""
        params: dict[str, str] = {"cursor": cursor, "limit": str(limit)}
        if types:
            params["types"] = ",".join(types)
        if file_id is not None:
            params["fileId"] = str(file_id)
        if exclude_actor:
            params["excludeActor"] = exclude_actor
        return await self._client.get_json(
            "/api/extended/events", EventFeedListVO, params=params
        )
