"""Client for Extended (Web) APIs."""

from supernote.models.base import BaseResponse
from supernote.models.extended import (
    FileProcessingStatusDTO,
    FileProcessingStatusVO,
    SystemTaskListVO,
    VocabularyAddDTO,
    VocabularyListDTO,
    VocabularyListVO,
    VocabularyMoveDTO,
    VocabularyTermIdDTO,
    WebSearchRequestDTO,
    WebSearchResponseVO,
    WebSummaryListRequestDTO,
    WebSummaryListVO,
    WebTranscriptRequestDTO,
    WebTranscriptResponseVO,
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

    async def list_vocabulary(
        self, include_suppressed: bool = False
    ) -> VocabularyListVO:
        """List vocabulary terms used in transcription prompts (Extension)."""
        dto = VocabularyListDTO(include_suppressed=include_suppressed)
        return await self._client.post_json(
            "/api/extended/vocabulary/list", VocabularyListVO, json=dto.to_dict()
        )

    async def add_vocabulary(
        self, terms: list[str], scope_id: int = 0
    ) -> VocabularyListVO:
        """Add vocabulary terms for every notebook, or one folder or notebook (Extension)."""
        dto = VocabularyAddDTO(terms=terms, scope_id=scope_id)
        return await self._client.post_json(
            "/api/extended/vocabulary/add", VocabularyListVO, json=dto.to_dict()
        )

    async def move_vocabulary(self, term_id: int, scope_id: int) -> VocabularyListVO:
        """Apply a vocabulary term to a different scope (Extension)."""
        dto = VocabularyMoveDTO(id=term_id, scope_id=scope_id)
        return await self._client.post_json(
            "/api/extended/vocabulary/move", VocabularyListVO, json=dto.to_dict()
        )

    async def delete_vocabulary(self, term_id: int) -> BaseResponse:
        """Remove a vocabulary term (Extension)."""
        dto = VocabularyTermIdDTO(id=term_id)
        return await self._client.post_json(
            "/api/extended/vocabulary/delete", BaseResponse, json=dto.to_dict()
        )

    async def restore_vocabulary(self, term_id: int) -> VocabularyListVO:
        """Bring back a removed harvested vocabulary term (Extension)."""
        dto = VocabularyTermIdDTO(id=term_id)
        return await self._client.post_json(
            "/api/extended/vocabulary/restore", VocabularyListVO, json=dto.to_dict()
        )
