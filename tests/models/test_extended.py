"""Tests for server-specific extension data models."""

from supernote.models.base import ProcessingStatus
from supernote.models.extended import (
    FileProcessingStatusDTO,
    FileProcessingStatusVO,
    PageTranscriptVO,
    SearchResultVO,
    SystemTaskListVO,
    SystemTaskVO,
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
