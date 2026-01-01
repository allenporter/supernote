"""Summary related API data models mirroring OpenAPI Spec.

The following endpoints are supported:
- /api/file/add/summary
- /api/file/delete/summary
- /api/file/download/summary
- /api/file/query/summary
- /api/file/query/summary/hash
- /api/file/query/summary/id
- /api/file/update/summary
- /api/file/upload/apply/summary
- /api/file/add/summary/group
- /api/file/delete/summary/group
- /api/file/query/summary/group
- /api/file/update/summary/group
- /api/file/add/summary/tag
- /api/file/delete/summary/tag
- /api/file/query/summary/tag
- /api/file/update/summary/tag
"""

from dataclasses import dataclass, field
from typing import List, Dict

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseResponse


@dataclass
class SummaryItem(DataClassJSONMixin):
    """Summary item."""

    id: int | None = None
    file_id: int | None = field(metadata=field_options(alias="fileId"), default=None)
    name: str | None = None
    user_id: int | None = field(metadata=field_options(alias="userId"), default=None)
    unique_identifier: str | None = field(
        metadata=field_options(alias="uniqueIdentifier"), default=None
    )
    parent_unique_identifier: str | None = field(
        metadata=field_options(alias="parentUniqueIdentifier"), default=None
    )
    content: str | None = None
    source_path: str | None = field(
        metadata=field_options(alias="sourcePath"), default=None
    )
    data_source: str | None = field(
        metadata=field_options(alias="dataSource"), default=None
    )
    source_type: int | None = field(
        metadata=field_options(alias="sourceType"), default=None
    )
    is_summary_group: str | None = field(
        metadata=field_options(alias="isSummaryGroup"), default=None
    )
    description: str | None = None
    tags: str | None = None
    md5_hash: str | None = field(metadata=field_options(alias="md5Hash"), default=None)
    metadata: str | None = None
    """JSON string."""

    comment_str: str | None = field(
        metadata=field_options(alias="commentStr"), default=None
    )
    comment_handwrite_name: str | None = field(
        metadata=field_options(alias="commentHandwriteName"), default=None
    )
    handwrite_inner_name: str | None = field(
        metadata=field_options(alias="handwriteInnerName"), default=None
    )
    handwrite_md5: str | None = field(
        metadata=field_options(alias="handwriteMD5"), default=None
    )
    creation_time: int | None = field(
        metadata=field_options(alias="creationTime"), default=None
    )
    last_modified_time: int | None = field(
        metadata=field_options(alias="lastModifiedTime"), default=None
    )
    is_deleted: str | None = field(
        metadata=field_options(alias="isDeleted"), default=None
    )
    create_time: int | None = field(
        metadata=field_options(alias="createTime"), default=None
    )
    update_time: int | None = field(
        metadata=field_options(alias="updateTime"), default=None
    )
    author: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SummaryTagItem(DataClassJSONMixin):
    """Summary tag item."""

    id: int | None = None
    name: str | None = None
    user_id: int | None = field(metadata=field_options(alias="userId"), default=None)
    unique_identifier: str | None = field(
        metadata=field_options(alias="uniqueIdentifier"), default=None
    )
    created_at: int | None = field(
        metadata=field_options(alias="createdAt"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SummaryInfoItem(DataClassJSONMixin):
    """Summary info item."""

    id: int | None = None
    user_id: int | None = field(metadata=field_options(alias="userId"), default=None)
    md5_hash: str | None = field(metadata=field_options(alias="md5Hash"), default=None)
    handwrite_md5: str | None = field(
        metadata=field_options(alias="handwriteMd5"), default=None
    )
    comment_handwrite_name: str | None = field(
        metadata=field_options(alias="commentHandwriteName"), default=None
    )
    last_modified_time: int | None = field(
        metadata=field_options(alias="lastModifiedTime"), default=None
    )
    metadata_map: Dict[str, str] = field(
        metadata=field_options(alias="metadataMap"), default_factory=dict
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class AddSummaryTagDTO(DataClassJSONMixin):
    """Request to add a summary tag.

    Used by:
        /api/file/add/summary/tag (POST)
    """

    name: str

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class AddSummaryTagVO(BaseResponse):
    """Response for adding a summary tag.

    Used by:
        /api/file/add/summary/tag (POST)
    """

    id: int | None = None


@dataclass
class UpdateSummaryTagDTO(DataClassJSONMixin):
    """Request to update a summary tag.

    Used by:
        /api/file/update/summary/tag (POST)
    """

    id: int
    name: str

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class DeleteSummaryTagDTO(DataClassJSONMixin):
    """Request to delete a summary tag.

    Used by:
        /api/file/delete/summary/tag (POST)
    """

    id: int

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class QuerySummaryTagVO(BaseResponse):
    """Response for querying summary tags.

    Used by:
        /api/file/query/summary/tag (POST)
    """

    summary_tag_do_list: List[SummaryTagItem] = field(
        metadata=field_options(alias="summaryTagDOList"), default_factory=list
    )


@dataclass
class AddSummaryGroupDTO(DataClassJSONMixin):
    """Request to add a summary group.

    Used by:
        /api/file/add/summary/group (POST)
    """

    unique_identifier: str = field(metadata=field_options(alias="uniqueIdentifier"))
    name: str
    md5_hash: str = field(metadata=field_options(alias="md5Hash"))
    description: str | None = None
    creation_time: int | None = field(
        metadata=field_options(alias="creationTime"), default=None
    )
    last_modified_time: int | None = field(
        metadata=field_options(alias="lastModifiedTime"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class AddSummaryGroupVO(BaseResponse):
    """Response for adding a summary group.

    Used by:
        /api/file/add/summary/group (POST)
    """

    id: int | None = None


@dataclass
class UpdateSummaryGroupDTO(DataClassJSONMixin):
    """Request to update a summary group.

    Used by:
        /api/file/update/summary/group (POST)
    """

    id: int
    md5_hash: str = field(metadata=field_options(alias="md5Hash"))
    unique_identifier: str | None = field(
        metadata=field_options(alias="uniqueIdentifier"), default=None
    )
    name: str | None = None
    description: str | None = None
    metadata: str | None = None
    comment_str: str | None = field(
        metadata=field_options(alias="commentStr"), default=None
    )
    comment_handwrite_name: str | None = field(
        metadata=field_options(alias="commentHandwriteName"), default=None
    )
    handwrite_inner_name: str | None = field(
        metadata=field_options(alias="handwriteInnerName"), default=None
    )
    last_modified_time: int | None = field(
        metadata=field_options(alias="lastModifiedTime"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class DeleteSummaryGroupDTO(DataClassJSONMixin):
    """Request to delete a summary group.

    Used by:
        /api/file/delete/summary/group (POST)
    """

    id: int

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class QuerySummaryGroupDTO(DataClassJSONMixin):
    """Request to query summary groups.

    Used by:
        /api/file/query/summary/group (POST)
    """

    page: int | None = None
    size: int | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class QuerySummaryGroupVO(BaseResponse):
    """Response for querying summary groups.

    Used by:
        /api/file/query/summary/group (POST)
    """

    total_records: int | None = field(
        metadata=field_options(alias="totalRecords"), default=None
    )
    total_pages: int | None = field(
        metadata=field_options(alias="totalPages"), default=None
    )
    current_page: int | None = field(
        metadata=field_options(alias="currentPage"), default=None
    )
    page_size: int | None = field(
        metadata=field_options(alias="pageSize"), default=None
    )
    summary_do_list: List[SummaryItem] = field(
        metadata=field_options(alias="summaryDOList"), default_factory=list
    )


@dataclass
class AddSummaryDTO(DataClassJSONMixin):
    """Request to add a summary.

    Used by:
        /api/file/add/summary (POST)
    """

    unique_identifier: str | None = field(
        metadata=field_options(alias="uniqueIdentifier"), default=None
    )
    file_id: int | None = field(metadata=field_options(alias="fileId"), default=None)
    parent_unique_identifier: str | None = field(
        metadata=field_options(alias="parentUniqueIdentifier"), default=None
    )
    content: str | None = None
    data_source: str | None = field(
        metadata=field_options(alias="dataSource"), default=None
    )
    source_path: str | None = field(
        metadata=field_options(alias="sourcePath"), default=None
    )
    source_type: int | None = field(
        metadata=field_options(alias="sourceType"), default=None
    )
    tags: str | None = None
    md5_hash: str | None = field(metadata=field_options(alias="md5Hash"), default=None)
    metadata: str | None = None
    comment_str: str | None = field(
        metadata=field_options(alias="commentStr"), default=None
    )
    comment_handwrite_name: str | None = field(
        metadata=field_options(alias="commentHandwriteName"), default=None
    )
    handwrite_inner_name: str | None = field(
        metadata=field_options(alias="handwriteInnerName"), default=None
    )
    handwrite_md5: str | None = field(
        metadata=field_options(alias="handwriteMD5"), default=None
    )
    creation_time: int | None = field(
        metadata=field_options(alias="creationTime"), default=None
    )
    last_modified_time: int | None = field(
        metadata=field_options(alias="lastModifiedTime"), default=None
    )
    author: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class AddSummaryVO(BaseResponse):
    """Response for adding a summary.

    Used by:
        /api/file/add/summary (POST)
    """

    id: int | None = None


@dataclass
class UpdateSummaryDTO(DataClassJSONMixin):
    """Request to update a summary.

    Used by:
        /api/file/update/summary (POST)
    """

    id: int
    parent_unique_identifier: str | None = field(
        metadata=field_options(alias="parentUniqueIdentifier"), default=None
    )
    content: str | None = None
    source_path: str | None = field(
        metadata=field_options(alias="sourcePath"), default=None
    )
    data_source: str | None = field(
        metadata=field_options(alias="dataSource"), default=None
    )
    source_type: int | None = field(
        metadata=field_options(alias="sourceType"), default=None
    )
    tags: str | None = None
    md5_hash: str | None = field(metadata=field_options(alias="md5Hash"), default=None)
    metadata: str | None = None
    comment_str: str | None = field(
        metadata=field_options(alias="commentStr"), default=None
    )
    comment_handwrite_name: str | None = field(
        metadata=field_options(alias="commentHandwriteName"), default=None
    )
    handwrite_inner_name: str | None = field(
        metadata=field_options(alias="handwriteInnerName"), default=None
    )
    handwrite_md5: str | None = field(
        metadata=field_options(alias="handwriteMD5"), default=None
    )
    last_modified_time: int | None = field(
        metadata=field_options(alias="lastModifiedTime"), default=None
    )
    author: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class DeleteSummaryDTO(DataClassJSONMixin):
    """Request to delete a summary.

    Used by:
        /api/file/delete/summary (POST)
    """

    id: int

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class QuerySummaryDTO(DataClassJSONMixin):
    """Request to query summaries.

    Used by:
        /api/file/query/summary (POST)
    """

    page: int | None = None
    size: int | None = None
    parent_unique_identifier: str | None = field(
        metadata=field_options(alias="parentUniqueIdentifier"), default=None
    )
    ids: List[int] = field(default_factory=list)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class QuerySummaryVO(BaseResponse):
    """Response for querying summaries.

    Used by:
        /api/file/query/summary (POST)
    """

    total_records: int | None = field(
        metadata=field_options(alias="totalRecords"), default=None
    )
    total_pages: int | None = field(
        metadata=field_options(alias="totalPages"), default=None
    )
    current_page: int | None = field(
        metadata=field_options(alias="currentPage"), default=None
    )
    page_size: int | None = field(
        metadata=field_options(alias="pageSize"), default=None
    )
    summary_do_list: List[SummaryItem] = field(
        metadata=field_options(alias="summaryDOList"), default_factory=list
    )


@dataclass(kw_only=True)
class QuerySummaryByIdVO(BaseResponse):
    """Response for querying summary by ID.

    Used by:
        /api/file/query/summary/id (POST)
    """

    summary_do_list: List[SummaryItem] = field(
        metadata=field_options(alias="summaryDOList"), default_factory=list
    )


@dataclass(kw_only=True)
class QuerySummaryMD5HashVO(BaseResponse):
    """Response for querying summary by MD5 hash.

    Used by:
        /api/file/query/summary/hash (POST)
    """

    total_records: int | None = field(
        metadata=field_options(alias="totalRecords"), default=None
    )
    total_pages: int | None = field(
        metadata=field_options(alias="totalPages"), default=None
    )
    current_page: int | None = field(
        metadata=field_options(alias="currentPage"), default=None
    )
    page_size: int | None = field(
        metadata=field_options(alias="pageSize"), default=None
    )
    summary_info_vo_list: List[SummaryInfoItem] = field(
        metadata=field_options(alias="summaryInfoVOList"), default_factory=list
    )


@dataclass
class DownloadSummaryDTO(DataClassJSONMixin):
    """Request to download summary.

    Used by:
        /api/file/download/summary (POST)
    """

    id: int

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class DownloadSummaryVO(BaseResponse):
    """Response for downloading summary.

    Used by:
        /api/file/download/summary (POST)
    """

    url: str | None = None


@dataclass
class UploadSummaryApplyDTO(DataClassJSONMixin):
    """Request to apply for summary upload.

    Used by:
        /api/file/upload/apply/summary (POST)
    """

    file_name: str = field(metadata=field_options(alias="fileName"))
    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class UploadSummaryApplyVO(BaseResponse):
    """Response for applying for summary upload.

    Used by:
        /api/file/upload/apply/summary (POST)
    """

    full_upload_url: str | None = field(
        metadata=field_options(alias="fullUploadUrl"), default=None
    )
    part_upload_url: str | None = field(
        metadata=field_options(alias="partUploadUrl"), default=None
    )
    inner_name: str | None = field(
        metadata=field_options(alias="innerName"), default=None
    )
