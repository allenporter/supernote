"""Tests for server-specific extension data models."""

from supernote.models.base import ProcessingStatus
from supernote.models.extended import (
    ApiKeyListResponseVO,
    ApiKeyVO,
    CreateApiKeyDTO,
    CreateApiKeyResponseVO,
    FileProcessingStatusDTO,
    FileProcessingStatusVO,
    NoteLinkVO,
    NotePageMetadataVO,
    NoteTitleVO,
    OAuthGrantListResponseVO,
    OAuthGrantVO,
    PageTranscriptVO,
    SearchResultVO,
    SystemTaskListVO,
    SystemTaskVO,
    WebAiStatusVO,
    WebNoteCoverRequestDTO,
    WebNoteCoverVO,
    WebNoteMetadataRequestDTO,
    WebNoteMetadataVO,
    WebSearchRequestDTO,
    WebSearchResponseVO,
    WebSummaryListRequestDTO,
    WebSummaryListVO,
    WebTranscriptRequestDTO,
    WebTranscriptResponseVO,
)
from supernote.models.summary import SummaryItem


def test_web_summary_list_models() -> None:
    req = WebSummaryListRequestDTO(file_id=772252421643567298)
    assert req.to_dict() == {"fileId": "772252421643567298"}
    assert WebSummaryListRequestDTO.from_dict({"fileId": "772252421643567298"}) == req
    assert WebSummaryListRequestDTO.from_dict(
        {"fileId": 42}
    ) == WebSummaryListRequestDTO(file_id=42)

    item = SummaryItem(id=1, file_id=42, content="Summary")
    vo = WebSummaryListVO(summary_do_list=[item], total_records=1)
    assert vo.to_dict() == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "summaryDOList": [item.to_dict()],
        "totalRecords": 1,
    }


def test_system_task_models() -> None:
    task = SystemTaskVO(
        id=772252421643567001,
        file_id=772252421643567298,
        task_type="OCR",
        key="page_0",
        status=ProcessingStatus.COMPLETED,
        retry_count=0,
        update_time=123456,
        last_error=None,
    )
    list_vo = SystemTaskListVO(tasks=[task])
    data = list_vo.to_dict()
    assert data == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "tasks": [
            {
                "id": "772252421643567001",
                "fileId": "772252421643567298",
                "taskType": "OCR",
                "key": "page_0",
                "status": "COMPLETED",
                "retryCount": 0,
                "updateTime": 123456,
                "lastError": None,
            }
        ],
    }
    assert SystemTaskListVO.from_dict(data) == list_vo


def test_file_processing_status_models() -> None:
    req = FileProcessingStatusDTO(file_ids=[1, 772252421643567298])
    assert req.to_dict() == {"fileIds": ["1", "772252421643567298"]}
    assert FileProcessingStatusDTO.from_dict(req.to_dict()) == req

    vo = FileProcessingStatusVO(status_map={"1": ProcessingStatus.COMPLETED})
    assert vo.to_dict() == {
        "success": True,
        "statusMap": {"1": "COMPLETED"},
    }


def test_web_search_models() -> None:
    req = WebSearchRequestDTO(
        query="notes",
        top_n=3,
        name_filter="Daily",
        date_after="2023-10-01",
        date_before="2023-10-31",
    )
    assert req.to_dict() == {
        "query": "notes",
        "topN": 3,
        "nameFilter": "Daily",
        "dateAfter": "2023-10-01",
        "dateBefore": "2023-10-31",
    }

    res = SearchResultVO(
        file_id=772252421643567298,
        file_name="Daily.note",
        page_index=0,
        page_id="P20231027120000abc",
        score=0.95,
        text_preview="Hello world",
        date="2023-10-27",
    )
    vo = WebSearchResponseVO(results=[res])
    data = vo.to_dict()
    assert data == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "results": [
            {
                "fileId": "772252421643567298",
                "fileName": "Daily.note",
                "pageIndex": 0,
                "pageId": "P20231027120000abc",
                "score": 0.95,
                "textPreview": "Hello world",
                "date": "2023-10-27",
            }
        ],
    }
    assert WebSearchResponseVO.from_dict(data) == vo


def test_web_transcript_models() -> None:
    req = WebTranscriptRequestDTO(file_id=101, start_index=0, end_index=2)
    assert req.to_dict() == {
        "fileId": "101",
        "startIndex": 0,
        "endIndex": 2,
    }
    assert WebTranscriptRequestDTO.from_dict(req.to_dict()) == req

    page = PageTranscriptVO(
        page_index=0,
        page_id="P20231027120000abc",
        text="Page 1 text",
        date="2023-10-27",
    )
    assert page.to_dict() == {
        "pageIndex": 0,
        "pageId": "P20231027120000abc",
        "text": "Page 1 text",
        "date": "2023-10-27",
    }

    vo = WebTranscriptResponseVO(pages=[page])
    data = vo.to_dict()
    assert data == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "pages": [
            {
                "pageIndex": 0,
                "pageId": "P20231027120000abc",
                "text": "Page 1 text",
                "date": "2023-10-27",
            }
        ],
    }
    parsed = WebTranscriptResponseVO.from_dict(data)
    assert parsed == vo


def test_api_key_models() -> None:
    dto = CreateApiKeyDTO(name="Obsidian Companion")
    assert dto.to_dict() == {"name": "Obsidian Companion", "expiresInDays": None}
    assert CreateApiKeyDTO.from_dict({"name": "Default Key"}).name == "Default Key"
    expiring_dto = CreateApiKeyDTO.from_dict(
        {"name": "Expiring Key", "expiresInDays": 30}
    )
    assert expiring_dto.expires_in_days == 30

    created_vo = CreateApiKeyResponseVO(
        id="abcdef1234567890",
        name="Obsidian Companion",
        key="sn_0123456789abcdef0123456789abcdef",
        created_at=1700000000,
        expires_at=1702592000,
    )
    assert created_vo.to_dict() == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "id": "abcdef1234567890",
        "name": "Obsidian Companion",
        "key": "sn_0123456789abcdef0123456789abcdef",
        "createdAt": 1700000000,
        "expiresAt": 1702592000,
    }
    assert CreateApiKeyResponseVO.from_dict(created_vo.to_dict()) == created_vo

    key_vo = ApiKeyVO(
        id="abcdef1234567890",
        name="Obsidian Companion",
        key_prefix="sn_01234567...",
        created_at=1700000000,
        last_used_at=1700000500,
        expires_at=1702592000,
    )
    list_vo = ApiKeyListResponseVO(keys=[key_vo])
    assert list_vo.to_dict() == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "keys": [
            {
                "id": "abcdef1234567890",
                "name": "Obsidian Companion",
                "keyPrefix": "sn_01234567...",
                "createdAt": 1700000000,
                "lastUsedAt": 1700000500,
                "expiresAt": 1702592000,
            }
        ],
    }
    assert ApiKeyListResponseVO.from_dict(list_vo.to_dict()) == list_vo


def test_oauth_grant_models() -> None:
    grant_vo = OAuthGrantVO(
        id="0a1b2c3d4e5f6a7b",
        client_id="https://client.example.com/",
        scopes=["supernote:all"],
        created_at=1700000000,
        expires_at=1702592000,
        last_used_at=1700000500,
    )
    list_vo = OAuthGrantListResponseVO(grants=[grant_vo])
    assert list_vo.to_dict() == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "grants": [
            {
                "id": "0a1b2c3d4e5f6a7b",
                "clientId": "https://client.example.com/",
                "scopes": ["supernote:all"],
                "createdAt": 1700000000,
                "expiresAt": 1702592000,
                "lastUsedAt": 1700000500,
            }
        ],
    }
    assert OAuthGrantListResponseVO.from_dict(list_vo.to_dict()) == list_vo


def test_web_note_cover_models() -> None:
    req = WebNoteCoverRequestDTO(file_id=9101)
    assert req.to_dict() == {"fileId": "9101"}
    assert WebNoteCoverRequestDTO.from_dict({"fileId": "9101"}) == req
    assert WebNoteCoverRequestDTO.from_dict({"fileId": 9101}) == req

    vo = WebNoteCoverVO(url="https://example.com/api/oss/png/9101/0")
    data = vo.to_dict()
    assert data == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "url": "https://example.com/api/oss/png/9101/0",
    }
    assert WebNoteCoverVO.from_dict(data) == vo


def test_web_ai_status_model() -> None:
    default_vo = WebAiStatusVO()
    assert default_vo.to_dict() == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "hasApiKey": False,
        "ocrEnabled": False,
        "ocrModel": None,
        "summaryEnabled": False,
        "summaryModel": None,
        "vectorSearchEnabled": False,
        "embeddingModel": None,
        "model": None,
    }
    assert WebAiStatusVO.from_dict(default_vo.to_dict()) == default_vo

    vo = WebAiStatusVO(
        has_api_key=True,
        ocr_enabled=True,
        ocr_model="apple-vision",
        summary_enabled=True,
        summary_model="gemini-2.5-flash",
        vector_search_enabled=False,
        embedding_model=None,
        model="apple-vision",
    )
    data = vo.to_dict()
    assert data == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "hasApiKey": True,
        "ocrEnabled": True,
        "ocrModel": "apple-vision",
        "summaryEnabled": True,
        "summaryModel": "gemini-2.5-flash",
        "vectorSearchEnabled": False,
        "embeddingModel": None,
        "model": "apple-vision",
    }
    assert WebAiStatusVO.from_dict(data) == vo


def test_web_note_metadata_models() -> None:
    snowflake_id = 772252421643567298
    target_snowflake_id = 772252421643567999
    req = WebNoteMetadataRequestDTO(file_id=snowflake_id)
    assert req.to_dict() == {"fileId": str(snowflake_id)}
    assert WebNoteMetadataRequestDTO.from_dict({"fileId": str(snowflake_id)}) == req
    assert WebNoteMetadataRequestDTO.from_dict({"fileId": snowflake_id}) == req

    vo = WebNoteMetadataVO(
        file_id=snowflake_id,
        equipment="N5",
        total_pages=2,
        keywords={"Sprint": [0, 1]},
        titles=[NoteTitleVO(page_index=0, level=2)],
        links=[
            NoteLinkVO(
                page_index=1,
                link_type="page",
                target="/Note/Target.note",
                target_file_id=target_snowflake_id,
                target_page_index=2,
            )
        ],
        pages=[
            NotePageMetadataVO(
                page_index=0,
                page_id="P20261101120000abc",
                date="2026-11-01",
                style="5mm_dots",
                is_blank=False,
                has_five_star=True,
                keywords=["Sprint"],
            )
        ],
    )
    data = vo.to_dict()
    assert data == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "fileId": str(snowflake_id),
        "equipment": "N5",
        "totalPages": 2,
        "keywords": {"Sprint": [0, 1]},
        "titles": [{"pageIndex": 0, "level": 2}],
        "links": [
            {
                "pageIndex": 1,
                "linkType": "page",
                "target": "/Note/Target.note",
                "targetFileId": str(target_snowflake_id),
                "targetPageIndex": 2,
            }
        ],
        "pages": [
            {
                "pageIndex": 0,
                "pageId": "P20261101120000abc",
                "date": "2026-11-01",
                "style": "5mm_dots",
                "isBlank": False,
                "hasFiveStar": True,
                "keywords": ["Sprint"],
            }
        ],
    }
    assert WebNoteMetadataVO.from_dict(data) == vo
