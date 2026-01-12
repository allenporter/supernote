"""Client for Summary APIs."""

from supernote.models.summary import (
    AddSummaryDTO,
    AddSummaryGroupDTO,
    AddSummaryGroupVO,
    AddSummaryTagDTO,
    AddSummaryTagVO,
    AddSummaryVO,
    BaseResponse,
    DeleteSummaryDTO,
    DeleteSummaryGroupDTO,
    DeleteSummaryTagDTO,
    DownloadSummaryDTO,
    DownloadSummaryVO,
    QuerySummaryByIdVO,
    QuerySummaryDTO,
    QuerySummaryGroupDTO,
    QuerySummaryGroupVO,
    QuerySummaryMD5HashVO,
    QuerySummaryTagVO,
    QuerySummaryVO,
    UpdateSummaryDTO,
    UpdateSummaryGroupDTO,
    UpdateSummaryTagDTO,
    UploadSummaryApplyDTO,
    UploadSummaryApplyVO,
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

    async def add_group(self, dto: AddSummaryGroupDTO) -> AddSummaryGroupVO:
        """Add a summary group."""
        return await self._client.post_json(
            "/api/file/add/summary/group", AddSummaryGroupVO, json=dto.to_dict()
        )

    async def update_group(self, dto: UpdateSummaryGroupDTO) -> BaseResponse:
        """Update a summary group."""
        return await self._client.post_json(
            "/api/file/update/summary/group", BaseResponse, json=dto.to_dict()
        )

    async def delete_group(self, group_id: int) -> BaseResponse:
        """Delete a summary group."""
        dto = DeleteSummaryGroupDTO(id=group_id)
        return await self._client.post_json(
            "/api/file/delete/summary/group", BaseResponse, json=dto.to_dict()
        )

    async def query_groups(self, page: int = 1, size: int = 20) -> QuerySummaryGroupVO:
        """Query summary groups."""
        dto = QuerySummaryGroupDTO(page=page, size=size)
        return await self._client.post_json(
            "/api/file/query/summary/group", QuerySummaryGroupVO, json=dto.to_dict()
        )

    async def upload_apply(
        self, file_name: str, equipment_no: str | None = None
    ) -> UploadSummaryApplyVO:
        """Apply for summary upload."""
        dto = UploadSummaryApplyDTO(file_name=file_name, equipment_no=equipment_no)
        return await self._client.post_json(
            "/api/file/upload/apply/summary", UploadSummaryApplyVO, json=dto.to_dict()
        )

    async def download_summary(self, summary_id: int) -> DownloadSummaryVO:
        """Download summary binary data."""
        dto = DownloadSummaryDTO(id=summary_id)
        return await self._client.post_json(
            "/api/file/download/summary", DownloadSummaryVO, json=dto.to_dict()
        )

    async def query_summary_hash(self, dto: QuerySummaryDTO) -> QuerySummaryMD5HashVO:
        """Query summary lightweight info (hash/integrity)."""
        return await self._client.post_json(
            "/api/file/query/summary/hash", QuerySummaryMD5HashVO, json=dto.to_dict()
        )

    async def query_summary_id(self, dto: QuerySummaryDTO) -> QuerySummaryByIdVO:
        """Query full summaries by ID."""
        return await self._client.post_json(
            "/api/file/query/summary/id", QuerySummaryByIdVO, json=dto.to_dict()
        )
