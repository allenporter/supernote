"""System related API data models mirroring OpenAPI Spec.

The following endpoints are supported:
- /api/save/email/config
- /api/query/email/config
- /api/query/email/publickey
- /api/oss/generate/upload/url
- /api/oss/upload/part
- /api/oss/generate/download/url
- /api/oss/upload
- /api/system/base/dictionary/deleteApi
- /api/system/base/dictionary/param/deleteApi
- /api/system/base/dictionary/by/{name}/deleteApi
- /api/system/base/reference/deleteApi
- /api/system/base/reference/param
- /api/official/system/base/param
"""

from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from .base import BaseResponse


@dataclass
class PageDTO(DataClassJSONMixin):
    """Common pagination DTO."""

    page_no: int = field(metadata=field_options(alias="pageNo"), default=1)
    """Page number."""

    page_size: int = field(metadata=field_options(alias="pageSize"), default=10)
    """Page size."""

    sort_field: str | None = field(
        metadata=field_options(alias="sortField"), default=None
    )
    """Sort field."""

    sort_rules: str | None = field(
        metadata=field_options(alias="sortRules"), default=None
    )
    """Sort rules."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class EmailServerDTO(DataClassJSONMixin):
    """Email server configuration request.

    Used by:
        /api/save/email/config (POST)
    """

    smtp_server: str = field(metadata=field_options(alias="smtpServer"))
    """Server Address."""

    port: str
    """Server Port."""

    username: str
    password: str
    encryption: str
    """SSL/TLS."""

    test_email: str | None = field(
        metadata=field_options(alias="testEmail"), default=None
    )
    language: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class EmailServerVO(BaseResponse):
    """Email server configuration response.

    Used by:
        /api/query/email/config (GET)
    """

    smtp_server: str | None = field(
        metadata=field_options(alias="smtpServer"), default=None
    )
    port: str | None = None
    username: str | None = None
    password: str | None = None
    encryption: str | None = None
    flag: str | None = None
    """N: Disabled, Y: Enabled."""

    test_email: str | None = field(
        metadata=field_options(alias="testEmail"), default=None
    )
    admin_email: str | None = field(
        metadata=field_options(alias="adminEmail"), default=None
    )


@dataclass(kw_only=True)
class EmailPublicKeyVO(BaseResponse):
    """Email public key response.

    Used by:
        /api/query/email/publickey (GET)
    """

    public_key: str | None = field(
        metadata=field_options(alias="publicKey"), default=None
    )


@dataclass
class FileUploadParams:
    """Query parameters for file uploads."""

    signature: str
    timestamp: int
    nonce: str
    path: str


@dataclass
class FileChunkParams(DataClassJSONMixin):
    """Query parameters for file uploads by chunk."""

    # Client provided parameters
    part_number: int = field(metadata=field_options(alias="partNumber"))
    total_chunks: int = field(metadata=field_options(alias="totalChunks"))
    upload_id: str = field(metadata=field_options(alias="uploadId"))

    # Server provided paramsters
    path: str | None = None
    signature: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class FileUploadApplyLocalVO(BaseResponse):
    """OSS upload apply response.

    Used by:
        /api/oss/generate/upload/url (POST)
    """

    equipment_no: str | None = field(
        metadata=field_options(alias="equipmentNo"), default=None
    )
    bucket_name: str | None = field(
        metadata=field_options(alias="bucketName"), default=None
    )
    """In private clouds, typically 'supernote'."""

    inner_name: str | None = field(
        metadata=field_options(alias="innerName"), default=None
    )
    """Obfuscated storage key. Formula: {UUID}-{tail}.{ext} where tail is SN last 3 digits."""

    x_amz_date: str | None = field(
        metadata=field_options(alias="xAmzDate"), default=None
    )
    authorization: str | None = None
    full_upload_url: str | None = field(
        metadata=field_options(alias="fullUploadUrl"), default=None
    )
    part_upload_url: str | None = field(
        metadata=field_options(alias="partUploadUrl"), default=None
    )


@dataclass(kw_only=True)
class FileChunkVO(BaseResponse):
    """File chunk response.

    Used by:
        /api/oss/upload/part (POST)
    """

    upload_id: str | None = field(
        metadata=field_options(alias="uploadId"), default=None
    )
    part_number: int | None = field(
        metadata=field_options(alias="partNumber"), default=None
    )
    total_chunks: int | None = field(
        metadata=field_options(alias="totalChunks"), default=None
    )
    chunk_md5: str | None = field(
        metadata=field_options(alias="chunkMd5"), default=None
    )
    status: str | None = None


@dataclass
class FileDownloadApplyVO(DataClassJSONMixin):
    """OSS download apply response (Note: missing BaseResponse in yaml, but likely VO).

    Used by:
        /api/oss/generate/download/url (POST)
    """

    url: str | None = None
    signature: str | None = None
    timestamp: int | None = None
    nonce: str | None = None
    path_id: str | None = field(metadata=field_options(alias="pathId"), default=None)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class UploadFileVO(BaseResponse):
    """Upload file response.

    Used by:
        /api/oss/upload (POST)
    """

    inner_name: str | None = field(
        metadata=field_options(alias="innerName"), default=None
    )
    """Obfuscated storage key. Formula: {UUID}-{tail}.{ext} where tail is SN last 3 digits."""

    md5: str | None = None


@dataclass
class DictionaryQueryDTO(DataClassJSONMixin):
    """Dictionary query DTO.

    Used by:
        /api/system/base/dictionary/deleteApi (GET)
    """

    name: str | None = None
    """Business code."""

    value: str | None = None
    """Code."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class DictionaryVagueDTO(PageDTO):
    """Dictionary vague query DTO.

    Used by:
        /api/system/base/dictionary/param/deleteApi (POST)
    """

    name: str | None = None
    """Dictionary name."""

    value_meaning: str | None = field(
        metadata=field_options(alias="valueMeaning"), default=None
    )
    """Value meaning."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class DictionaryVO(DataClassJSONMixin):
    """Dictionary item VO."""

    id: int | None = None
    name: str | None = None
    """Dictionary Category Name."""

    value: str | None = None
    """Dictionary Key/Code."""

    value_cn: str | None = field(metadata=field_options(alias="valueCn"), default=None)
    """Chinese Display Value."""

    value_en: str | None = field(metadata=field_options(alias="valueEn"), default=None)
    """English Display Value."""

    value_ja: str | None = field(metadata=field_options(alias="valueJa"), default=None)
    """Japanese Display Value."""

    op_user: str | None = field(metadata=field_options(alias="opUser"), default=None)
    """Last Modified By (Admin Username)."""

    op_time: int | None = field(metadata=field_options(alias="opTime"), default=None)
    """Last Modified Timestamp."""

    remark: str | None = None
    """Comments/Notes."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class DictionaryListVO(BaseResponse):
    """Dictionary list response.

    Used by:
        /api/system/base/dictionary/deleteApi (GET)
    """

    dictionary_vo_list: list[DictionaryVO] = field(
        metadata=field_options(alias="dictionaryVOList"), default_factory=list
    )


@dataclass(kw_only=True)
class DictionaryByNameVO(BaseResponse):
    """Dictionary by name response.

    Used by:
        /api/system/base/dictionary/by/{name}/deleteApi (GET)
    """

    dictionary_vo_list: list[DictionaryVO] = field(
        metadata=field_options(alias="dictionaryVOList"), default_factory=list
    )


@dataclass
class ReferenceQueryDTO(DataClassJSONMixin):
    """Reference query DTO.

    Used by:
        /api/system/base/reference/deleteApi (POST)
    """

    name: str
    """Business code."""

    serial: str | None = None
    """Code."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ReferenceVagueDTO(PageDTO):
    """Reference vague query DTO.

    Used by:
        /api/system/base/reference/param (POST)
    """

    name: str | None = None
    """Business code."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ReferenceVO(DataClassJSONMixin):
    """Reference item VO."""

    id: int | None = None
    serial: str | None = None
    """Reference Serial Number / Key."""

    name: str | None = None
    """Reference Category Name."""

    value: str | None = None
    """Reference Value."""

    value_cn: str | None = field(metadata=field_options(alias="valueCn"), default=None)
    """Description (CN)."""

    op_user: str | None = field(metadata=field_options(alias="opUser"), default=None)
    """Last Modified By (Admin Username)."""

    op_time: int | None = field(metadata=field_options(alias="opTime"), default=None)
    """Last Modified Timestamp."""

    remark: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class ReferenceListVO(BaseResponse):
    """Reference list response.

    Used by:
        /api/system/base/reference/deleteApi (POST)
    """

    reference_vo_list: list[ReferenceVO] = field(
        metadata=field_options(alias="referenceVOList"), default_factory=list
    )


@dataclass
class ReferenceInfoVO(DataClassJSONMixin):
    """Reference info."""

    serial: str | None = None
    name: str | None = None
    value: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass(kw_only=True)
class ReferenceRespVO(BaseResponse):
    """Reference response with params.

    Used by:
        /api/official/system/base/param (POST)
    """

    param_list: list[ReferenceInfoVO] = field(
        metadata=field_options(alias="paramList"), default_factory=list
    )
    random: str | None = None
