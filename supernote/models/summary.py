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

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseResponse, BooleanEnum


@dataclass
class SummaryItem(DataClassJSONMixin):
    """A Summary instance representing content derived from a source file (e.g., OCR, user notes)."""

    id: int | None = None
    """Internal database ID."""

    file_id: int | None = field(metadata=field_options(alias="fileId"), default=None)
    """The numeric ID of the source file in the cloud storage."""

    name: str | None = None
    """Display name of the summary or group."""

    user_id: int | None = field(metadata=field_options(alias="userId"), default=None)
    """ID of the user who owns this summary."""

    unique_identifier: str | None = field(
        metadata=field_options(alias="uniqueIdentifier"), default=None
    )
    """Client-provided UUID. This is the primary key for syncing between device and server.

    For file-associated summaries, this should match the source file's UUID.
    """

    parent_unique_identifier: str | None = field(
        metadata=field_options(alias="parentUniqueIdentifier"), default=None
    )
    """The UUID of the parent Summary Group, if applicable."""

    content: str | None = None
    """The primary text content (e.g., generated OCR text or markdown)."""

    source_path: str | None = field(
        metadata=field_options(alias="sourcePath"), default=None
    )
    """Absolute path to the source file on the device (e.g., /Note/MyMeeting.note)."""

    data_source: str | None = field(
        metadata=field_options(alias="dataSource"), default=None
    )
    """Source of the data (e.g., 'OCR', 'USER', 'GEMINI')."""

    source_type: int | None = field(
        metadata=field_options(alias="sourceType"), default=None
    )
    """Internal type indicator for the source."""

    is_summary_group: BooleanEnum | None = field(
        metadata=field_options(alias="isSummaryGroup"), default=None
    )
    """Flag indicating if this item is a folder/group ('Y') or a leaf summary ('N')."""

    description: str | None = None
    """Additional text description of the summary."""

    tags: str | None = None
    """Comma-separated list of tag names associated with this summary."""

    md5_hash: str | None = field(metadata=field_options(alias="md5Hash"), default=None)
    """MD5 hash of the 'content' field for integrity checking."""

    metadata: str | None = None
    """JSON string containing additional structured metadata."""

    comment_str: str | None = field(
        metadata=field_options(alias="commentStr"), default=None
    )
    """Text comment associated with the summary."""

    comment_handwrite_name: str | None = field(
        metadata=field_options(alias="commentHandwriteName"), default=None
    )
    """Name of the handwriting file (in OSS) associated with the comment."""

    handwrite_inner_name: str | None = field(
        metadata=field_options(alias="handwriteInnerName"), default=None
    )
    """The innerName on OSS for the handwriting binary data."""

    handwrite_md5: str | None = field(
        metadata=field_options(alias="handwriteMD5"), default=None
    )
    """MD5 hash of the handwriting binary data."""

    creation_time: int | None = field(
        metadata=field_options(alias="creationTime"), default=None
    )
    """Original creation time in milliseconds since epoch."""

    last_modified_time: int | None = field(
        metadata=field_options(alias="lastModifiedTime"), default=None
    )
    """Last modification time in milliseconds since epoch."""

    is_deleted: BooleanEnum | None = field(
        metadata=field_options(alias="isDeleted"), default=None
    )
    """Soft-delete flag ('Y' or 'N')."""

    create_time: int | None = field(
        metadata=field_options(alias="createTime"), default=None
    )
    """System creation timestamp (milliseconds)."""

    update_time: int | None = field(
        metadata=field_options(alias="updateTime"), default=None
    )
    """System update timestamp (milliseconds)."""

    author: str | None = None
    """Author of the summary."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SummaryTagItem(DataClassJSONMixin):
    """Summary tag metadata."""

    id: int | None = None
    """Internal database ID."""

    name: str | None = None
    """Tag display name (e.g., 'Work', 'Meeting')."""

    user_id: int | None = field(metadata=field_options(alias="userId"), default=None)
    """Owner user ID."""

    unique_identifier: str | None = field(
        metadata=field_options(alias="uniqueIdentifier"), default=None
    )
    """Tag UUID used for syncing."""

    created_at: int | None = field(
        metadata=field_options(alias="createdAt"), default=None
    )
    """Creation timestamp (milliseconds)."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SummaryInfoItem(DataClassJSONMixin):
    """Lightweight metadata for synchronization and integrity checks.

    Used by QuerySummaryMD5HashVO to provide a 'Sync Manifest' that allows
    clients to compare MD5 hashes before downloading full content.
    """

    id: int | None = None
    """Internal database ID."""

    user_id: int | None = field(metadata=field_options(alias="userId"), default=None)
    """Owner user ID."""

    md5_hash: str | None = field(metadata=field_options(alias="md5Hash"), default=None)
    """MD5 hash of the summary text content."""

    handwrite_md5: str | None = field(
        metadata=field_options(alias="handwriteMd5"), default=None
    )
    """MD5 hash of the associated handwriting stroke data."""

    comment_handwrite_name: str | None = field(
        metadata=field_options(alias="commentHandwriteName"), default=None
    )
    """Name of the handwriting file in storage."""

    last_modified_time: int | None = field(
        metadata=field_options(alias="lastModifiedTime"), default=None
    )
    """Timestamp of last modification (milliseconds)."""

    metadata_map: dict[str, str] = field(
        metadata=field_options(alias="metadataMap"), default_factory=dict
    )
    """Extensible map of metadata key-value pairs."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class AddSummaryTagDTO(DataClassJSONMixin):
    """Request to add a summary tag.

    Used by:
        /api/file/add/summary/tag (POST)
    """

    name: str
    """Name of the tag to create (e.g., 'Work')."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class AddSummaryTagVO(BaseResponse):
    """Response for adding a summary tag.

    Used by:
        /api/file/add/summary/tag (POST)
    """

    id: int | None = None
    """ID of the newly created tag."""


@dataclass
class UpdateSummaryTagDTO(DataClassJSONMixin):
    """Request to update a summary tag.

    Used by:
        /api/file/update/summary/tag (POST)
    """

    id: int
    """ID of the tag to update."""

    name: str
    """New name for the tag."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class DeleteSummaryTagDTO(DataClassJSONMixin):
    """Request to delete a summary tag.

    Used by:
        /api/file/delete/summary/tag (POST)
    """

    id: int
    """ID of the tag to delete."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class QuerySummaryTagVO(BaseResponse):
    """Response for querying summary tags.

    Used by:
        /api/file/query/summary/tag (POST)
    """

    summary_tag_do_list: list[SummaryTagItem] = field(
        metadata=field_options(alias="summaryTagDOList"), default_factory=list
    )
    """List of summary tags."""


@dataclass
class AddSummaryGroupDTO(DataClassJSONMixin):
    """Request to add a summary group.

    Used by:
        /api/file/add/summary/group (POST)
    """

    unique_identifier: str = field(metadata=field_options(alias="uniqueIdentifier"))
    """UUID for the group. For sync consistency, generate this on the client."""

    name: str
    """Display name for the group."""

    md5_hash: str = field(metadata=field_options(alias="md5Hash"))
    """Integrity hash for group metadata content."""

    description: str | None = None
    """Optional description."""

    creation_time: int | None = field(
        metadata=field_options(alias="creationTime"), default=None
    )
    """Timestamp of group creation (milliseconds)."""

    last_modified_time: int | None = field(
        metadata=field_options(alias="lastModifiedTime"), default=None
    )
    """Timestamp of last modification (milliseconds)."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class AddSummaryGroupVO(BaseResponse):
    """Response for adding a summary group.

    Used by:
        /api/file/add/summary/group (POST)
    """

    id: int | None = None
    """ID of the newly created summary group."""


@dataclass
class UpdateSummaryGroupDTO(DataClassJSONMixin):
    """Request to update a summary group.

    Used by:
        /api/file/update/summary/group (POST)
    """

    id: int
    """Database ID of the group to update."""

    md5_hash: str = field(metadata=field_options(alias="md5Hash"))
    """New integrity hash."""

    unique_identifier: str | None = field(
        metadata=field_options(alias="uniqueIdentifier"), default=None
    )
    """UUID of the group."""

    name: str | None = None
    """Updated name."""

    description: str | None = None
    """Updated description."""

    metadata: str | None = None
    """Updated JSON metadata string."""

    comment_str: str | None = field(
        metadata=field_options(alias="commentStr"), default=None
    )
    """Updated comment text."""

    comment_handwrite_name: str | None = field(
        metadata=field_options(alias="commentHandwriteName"), default=None
    )
    """Updated handwriting file name."""

    handwrite_inner_name: str | None = field(
        metadata=field_options(alias="handwriteInnerName"), default=None
    )
    """Updated OSS storage key for handwriting."""

    last_modified_time: int | None = field(
        metadata=field_options(alias="lastModifiedTime"), default=None
    )
    """Timestamp of update (milliseconds)."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class DeleteSummaryGroupDTO(DataClassJSONMixin):
    """Request to delete a summary group.

    Used by:
        /api/file/delete/summary/group (POST)
    """

    id: int
    """ID of the group to delete."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class QuerySummaryGroupDTO(DataClassJSONMixin):
    """Request to query summary groups.

    Used by:
        /api/file/query/summary/group (POST)
    """

    page: int | None = None
    """Page number to retrieve."""

    size: int | None = None
    """Number of groups per page."""

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
    """Total number of groups found."""

    total_pages: int | None = field(
        metadata=field_options(alias="totalPages"), default=None
    )
    """Total pages available."""

    current_page: int | None = field(
        metadata=field_options(alias="currentPage"), default=None
    )
    """The page returned in this response."""

    page_size: int | None = field(
        metadata=field_options(alias="pageSize"), default=None
    )
    """Number of records per page."""

    summary_do_list: list[SummaryItem] = field(
        metadata=field_options(alias="summaryDOList"), default_factory=list
    )
    """List of summary groups (as SummaryItems)."""


# Metadata keys used in the Summary 'extra_metadata' field
METADATA_SEGMENTS = "segments"
"""List of semantic segments. Each segment is a dict with:
    - date_range: str
    - summary: str
    - extracted_dates: List[str]
    - page_refs: List[int]
"""


@dataclass
class AddSummaryDTO(DataClassJSONMixin):
    """Request to add a summary.

    Used by:
        /api/file/add/summary (POST)
    """

    unique_identifier: str | None = field(
        metadata=field_options(alias="uniqueIdentifier"), default=None
    )
    """UUID for the summary. Usually matches the source file's UUID."""

    file_id: int | None = field(metadata=field_options(alias="fileId"), default=None)
    """Database ID of the source file."""

    parent_unique_identifier: str | None = field(
        metadata=field_options(alias="parentUniqueIdentifier"), default=None
    )
    """UUID of the parent group (if organized in a folder)."""

    content: str | None = None
    """The summary content text."""

    data_source: str | None = field(
        metadata=field_options(alias="dataSource"), default=None
    )
    """Producer of the summary (e.g., 'OCR', 'GEMINI', 'USER')."""

    source_path: str | None = field(
        metadata=field_options(alias="sourcePath"), default=None
    )
    """Path to the source file."""

    source_type: int | None = field(
        metadata=field_options(alias="sourceType"), default=None
    )
    """Indicator of source type."""

    tags: str | None = None
    """Comma-separated tags."""

    md5_hash: str | None = field(metadata=field_options(alias="md5Hash"), default=None)
    """MD5 integrity hash of 'content'."""

    metadata: str | None = None
    """JSON-encoded metadata string."""

    comment_str: str | None = field(
        metadata=field_options(alias="commentStr"), default=None
    )
    """Initial comment."""

    comment_handwrite_name: str | None = field(
        metadata=field_options(alias="commentHandwriteName"), default=None
    )
    """Handwriting companion filename."""

    handwrite_inner_name: str | None = field(
        metadata=field_options(alias="handwriteInnerName"), default=None
    )
    """OSS storage key for handwriting."""

    handwrite_md5: str | None = field(
        metadata=field_options(alias="handwriteMD5"), default=None
    )
    """MD5 hash for handwriting data."""

    creation_time: int | None = field(
        metadata=field_options(alias="creationTime"), default=None
    )
    """Timestamp of creation (milliseconds)."""

    last_modified_time: int | None = field(
        metadata=field_options(alias="lastModifiedTime"), default=None
    )
    """Timestamp of last modification (milliseconds)."""

    author: str | None = None
    """Author of the summary."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class AddSummaryVO(BaseResponse):
    """Response for adding a summary.

    Used by:
        /api/file/add/summary (POST)
    """

    id: int | None = None
    """ID of the newly created summary."""


@dataclass
class UpdateSummaryDTO(DataClassJSONMixin):
    """Request to update a summary.

    Used by:
        /api/file/update/summary (POST)
    """

    id: int
    """Database ID of the summary."""

    parent_unique_identifier: str | None = field(
        metadata=field_options(alias="parentUniqueIdentifier"), default=None
    )
    """Updated parent group UUID."""

    content: str | None = None
    """Updated text content."""

    source_path: str | None = field(
        metadata=field_options(alias="sourcePath"), default=None
    )
    """Updated source path."""

    data_source: str | None = field(
        metadata=field_options(alias="dataSource"), default=None
    )
    """Updated data source (e.g., 'OCR', 'USER')."""

    source_type: int | None = field(
        metadata=field_options(alias="sourceType"), default=None
    )
    """Updated source type."""

    tags: str | None = None
    """Updated tags string."""

    md5_hash: str | None = field(metadata=field_options(alias="md5Hash"), default=None)
    """New content hash."""

    metadata: str | None = None
    """Updated JSON metadata."""

    comment_str: str | None = field(
        metadata=field_options(alias="commentStr"), default=None
    )
    """Updated comment."""

    comment_handwrite_name: str | None = field(
        metadata=field_options(alias="commentHandwriteName"), default=None
    )
    """Updated handwriting file name."""

    handwrite_inner_name: str | None = field(
        metadata=field_options(alias="handwriteInnerName"), default=None
    )
    """Updated OSS storage key."""

    handwrite_md5: str | None = field(
        metadata=field_options(alias="handwriteMD5"), default=None
    )
    """Updated handwriting MD5."""

    last_modified_time: int | None = field(
        metadata=field_options(alias="lastModifiedTime"), default=None
    )
    """Timestamp of modification (milliseconds)."""

    author: str | None = None
    """Author of the summary."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class DeleteSummaryDTO(DataClassJSONMixin):
    """Request to delete a summary.

    Used by:
        /api/file/delete/summary (POST)
    """

    id: int
    """ID of the summary to delete."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class QuerySummaryDTO(DataClassJSONMixin):
    """Request to query summaries.

    Used by:
        /api/file/query/summary (POST)
    """

    page: int | None = None
    """Page number (starting from 1)."""

    size: int | None = None
    """Number of records per page."""

    parent_unique_identifier: str | None = field(
        metadata=field_options(alias="parentUniqueIdentifier"), default=None
    )
    """Filter by parent group UUID."""

    ids: list[int] = field(default_factory=list)
    """Fetch specific summaries by their numeric IDs."""

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
    """Total number of records found."""

    total_pages: int | None = field(
        metadata=field_options(alias="totalPages"), default=None
    )
    """Total pages available."""

    current_page: int | None = field(
        metadata=field_options(alias="currentPage"), default=None
    )
    """Current page number."""

    page_size: int | None = field(
        metadata=field_options(alias="pageSize"), default=None
    )
    """Records per page."""

    summary_do_list: list[SummaryItem] = field(
        metadata=field_options(alias="summaryDOList"), default_factory=list
    )
    """List of summaries found."""


@dataclass(kw_only=True)
class QuerySummaryByIdVO(BaseResponse):
    """Response for querying summary by ID.

    Used by:
        /api/file/query/summary/id (POST)
    """

    summary_do_list: list[SummaryItem] = field(
        metadata=field_options(alias="summaryDOList"), default_factory=list
    )
    """List of summaries matched by ID."""


@dataclass(kw_only=True)
class QuerySummaryMD5HashVO(BaseResponse):
    """Response for a Lightweight Synchronization Manifest (MD5 query).

    Returns a list of SummaryInfoItem records. Designed for sync checks,
    allowing clients to identify changed summaries without full detail downloads.

    Used by:
        /api/file/query/summary/hash (POST)
    """

    total_records: int | None = field(
        metadata=field_options(alias="totalRecords"), default=None
    )
    """Total matching records."""

    total_pages: int | None = field(
        metadata=field_options(alias="totalPages"), default=None
    )
    """Total pages of results."""

    current_page: int | None = field(
        metadata=field_options(alias="currentPage"), default=None
    )
    """Current page number."""

    page_size: int | None = field(
        metadata=field_options(alias="pageSize"), default=None
    )
    """Current page size."""

    summary_info_vo_list: list[SummaryInfoItem] = field(
        metadata=field_options(alias="summaryInfoVOList"), default_factory=list
    )
    """List of summary integrity information."""


@dataclass
class DownloadSummaryDTO(DataClassJSONMixin):
    """Request to download summary.

    Used by:
        /api/file/download/summary (POST)
    """

    id: int
    """Database ID of the summary to download (for handwriting stroke data)."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class DownloadSummaryVO(BaseResponse):
    """Response for downloading summary.

    Used by:
        /api/file/download/summary (POST)
    """

    url: str | None = None
    """Signed OSS/S3 URL to download the binary content."""


@dataclass
class UploadSummaryApplyDTO(DataClassJSONMixin):
    """Request to apply for summary upload.

    Used by:
        /api/file/upload/apply/summary (POST)
    """

    file_name: str = field(metadata=field_options(alias="fileName"))
    """Suggested name for the stored file."""

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    """Serial number of the uploading device."""

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
    """Signed URL for single-part upload."""

    part_upload_url: str | None = field(
        metadata=field_options(alias="partUploadUrl"), default=None
    )
    """Signed URL for multi-part upload."""

    inner_name: str | None = field(
        metadata=field_options(alias="innerName"), default=None
    )
    """The generated internal name on object storage: {UUID}-{tail}.{ext} where tail is derived from the the client equipmentNo"""
