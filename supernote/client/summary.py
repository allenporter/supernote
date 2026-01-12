"""Client for Summary APIs."""

from supernote.models.summary import (
    AddSummaryDTO,
    AddSummaryTagDTO,
    AddSummaryTagVO,
    AddSummaryVO,
    BaseResponse,
    DeleteSummaryDTO,
    DeleteSummaryTagDTO,
    QuerySummaryDTO,
    QuerySummaryTagVO,
    QuerySummaryVO,
    UpdateSummaryDTO,
    UpdateSummaryTagDTO,
)

from . import Client


class SummaryClient:
    """Client for Summary APIs."""

    def __init__(self, client: Client):
        """Initialize a summary client."""
        self._client = client

    async def add_tag(self, name: str) -> AddSummaryTagVO:
        """Add a summary tag."""
        dto = AddSummaryTagDTO(name=name)
        return await self._client.post_json(
            "/api/file/add/summary/tag", AddSummaryTagVO, json=dto.to_dict()
        )

    async def update_tag(self, tag_id: int, name: str) -> BaseResponse:
        """Update a summary tag."""
        dto = UpdateSummaryTagDTO(id=tag_id, name=name)
        return await self._client.post_json(
            "/api/file/update/summary/tag", BaseResponse, json=dto.to_dict()
        )

    async def delete_tag(self, tag_id: int) -> BaseResponse:
        """Delete a summary tag."""
        dto = DeleteSummaryTagDTO(id=tag_id)
        return await self._client.post_json(
            "/api/file/delete/summary/tag", BaseResponse, json=dto.to_dict()
        )

    async def query_tags(self) -> QuerySummaryTagVO:
        """Query summary tags."""
        return await self._client.post_json(
            "/api/file/query/summary/tag", QuerySummaryTagVO, json={}
        )

    async def add_summary(self, dto: AddSummaryDTO) -> AddSummaryVO:
        """Add a new summary."""
        return await self._client.post_json(
            "/api/file/add/summary", AddSummaryVO, json=dto.to_dict()
        )

    async def update_summary(self, dto: UpdateSummaryDTO) -> BaseResponse:
        """Update an existing summary."""
        return await self._client.post_json(
            "/api/file/update/summary", BaseResponse, json=dto.to_dict()
        )

    async def delete_summary(self, summary_id: int) -> BaseResponse:
        """Delete a summary."""
        dto = DeleteSummaryDTO(id=summary_id)
        return await self._client.post_json(
            "/api/file/delete/summary", BaseResponse, json=dto.to_dict()
        )

    async def query_summaries(
        self,
        parent_uuid: str | None = None,
        page: int = 1,
        size: int = 20,
        ids: list[int] | None = None,
    ) -> QuerySummaryVO:
        """Query summaries."""
        dto = QuerySummaryDTO(
            parent_unique_identifier=parent_uuid,
            page=page,
            size=size,
            ids=ids or [],
        )
        return await self._client.post_json(
            "/api/file/query/summary", QuerySummaryVO, json=dto.to_dict()
        )
