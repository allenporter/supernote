"""Tests for server-specific extension data models."""

from supernote.models.base import ProcessingStatus
from supernote.models.extended import (
    FileProcessingStatusDTO,
    FileProcessingStatusVO,
    NoteKeywordVO,
    NoteLinkVO,
    NotePageMetadataVO,
    NoteRectVO,
    NoteTitleVO,
    PageTranscriptVO,
    SearchResultVO,
    SystemTaskListVO,
    SystemTaskVO,
    WebAiStatusVO,
    WebNoteCoverRequestDTO,
    WebNoteCoverVO,
    WebNoteMetadataRequestDTO,
    WebNoteMetadataVO,
    WebNotePageMetadataRequestDTO,
    WebNotePageMetadataVO,
    WebSearchRequestDTO,
    WebSearchResponseVO,
    WebSummaryListRequestDTO,
    WebSummaryListVO,
    WebTranscriptRequestDTO,
    WebTranscriptResponseVO,
)
from supernote.models.summary import SummaryItem


def test_web_summary_list_models() -> None:
    req = WebSummaryListRequestDTO(file_id=42)
    assert req.to_dict() == {"fileId": 42}

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
        id=1,
        file_id=100,
        task_type="OCR",
        key="page_0",
        status=ProcessingStatus.COMPLETED,
        retry_count=0,
        update_time=123456,
        last_error=None,
    )
    list_vo = SystemTaskListVO(tasks=[task])
    assert list_vo.to_dict() == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "tasks": [
            {
                "id": 1,
                "fileId": 100,
                "taskType": "OCR",
                "key": "page_0",
                "status": "COMPLETED",
                "retryCount": 0,
                "updateTime": 123456,
                "lastError": None,
            }
        ],
    }


def test_file_processing_status_models() -> None:
    req = FileProcessingStatusDTO(file_ids=[1, 2])
    assert req.to_dict() == {"fileIds": [1, 2]}

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
        file_id=10,
        file_name="Daily.note",
        page_index=0,
        page_id="P20231027120000abc",
        score=0.95,
        text_preview="Hello world",
        date="2023-10-27",
    )
    vo = WebSearchResponseVO(results=[res])
    assert vo.to_dict() == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "results": [
            {
                "fileId": 10,
                "fileName": "Daily.note",
                "pageIndex": 0,
                "pageId": "P20231027120000abc",
                "score": 0.95,
                "textPreview": "Hello world",
                "date": "2023-10-27",
            }
        ],
    }


def test_web_transcript_models() -> None:
    req = WebTranscriptRequestDTO(file_id=101, start_index=0, end_index=2)
    assert req.to_dict() == {
        "fileId": 101,
        "startIndex": 0,
        "endIndex": 2,
    }

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
    assert req.to_dict() == {"fileId": 9101}
    assert WebNoteCoverRequestDTO.from_dict({"fileId": "9101"}) == req

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
    req = WebNoteMetadataRequestDTO(file_id=77)
    assert req.to_dict() == {"fileId": 77}
    assert WebNoteMetadataRequestDTO.from_dict({"fileId": "77"}) == req

    page_req = WebNotePageMetadataRequestDTO(file_id=77, start_index=0, end_index=4)
    assert page_req.to_dict() == {"fileId": 77, "startIndex": 0, "endIndex": 4}
    assert (
        WebNotePageMetadataRequestDTO.from_dict(
            {"fileId": "77", "startIndex": 0, "endIndex": 4}
        )
        == page_req
    )

    rect = NoteRectVO(left=10, top=20, right=110, bottom=60)
    kw = NoteKeywordVO(page_number=0, text="stroller", rect=rect)
    title = NoteTitleVO(page_number=0, level=1, style="1000254", rect=rect)
    link = NoteLinkVO(
        page_number=0,
        link_type=1,
        direction=0,
        style="4",
        target="/Note/Target.note",
        target_file_id="F999",
        target_page_id="P20260101000000xyz",
        target_page_number=None,
        rect=rect,
    )
    vo = WebNoteMetadataVO(
        file_id=77,
        native_file_id="F777",
        file_type="note",
        equipment="N5",
        signature="SN_FILE_VER_20230015",
        width=1920,
        height=2560,
        total_pages=1,
        recogn_language="en_US",
        realtime_recognition=True,
        keywords=[kw],
        titles=[title],
        links=[link],
    )
    data = vo.to_dict()
    assert data == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "fileId": 77,
        "nativeFileId": "F777",
        "fileType": "note",
        "equipment": "N5",
        "signature": "SN_FILE_VER_20230015",
        "width": 1920,
        "height": 2560,
        "totalPages": 1,
        "recognLanguage": "en_US",
        "realtimeRecognition": True,
        "keywords": [
            {
                "pageNumber": 0,
                "text": "stroller",
                "rect": {"left": 10, "top": 20, "right": 110, "bottom": 60},
            }
        ],
        "titles": [
            {
                "pageNumber": 0,
                "level": 1,
                "style": "1000254",
                "rect": {"left": 10, "top": 20, "right": 110, "bottom": 60},
            }
        ],
        "links": [
            {
                "pageNumber": 0,
                "linkType": 1,
                "direction": 0,
                "style": "4",
                "target": "/Note/Target.note",
                "targetFileId": "F999",
                "targetPageId": "P20260101000000xyz",
                "targetPageNumber": None,
                "rect": {"left": 10, "top": 20, "right": 110, "bottom": 60},
            }
        ],
    }
    assert WebNoteMetadataVO.from_dict(data) == vo

    page = NotePageMetadataVO(
        page_index=0,
        page_id="P20260101000000abc",
        date="2026-01-01",
        style="style_5mm_dots",
        style_label="5mm Dots",
        style_hash=None,
        orientation="1000",
        recogn_status=1,
        has_ink=True,
        has_drawables=True,
        has_textbox=False,
        has_vector_graph=False,
        has_content=True,
        five_star=["100,200,50,50"],
        keywords=[kw],
        titles=[title],
        links=[link],
    )
    page_vo = WebNotePageMetadataVO(file_id=77, total_pages=1, pages=[page])
    page_data = page_vo.to_dict()
    assert page_data == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "fileId": 77,
        "totalPages": 1,
        "pages": [
            {
                "pageIndex": 0,
                "pageId": "P20260101000000abc",
                "date": "2026-01-01",
                "style": "style_5mm_dots",
                "styleLabel": "5mm Dots",
                "styleHash": None,
                "orientation": "1000",
                "recognStatus": 1,
                "hasInk": True,
                "hasDrawables": True,
                "hasTextbox": False,
                "hasVectorGraph": False,
                "hasContent": True,
                "fiveStar": ["100,200,50,50"],
                "keywords": [
                    {
                        "pageNumber": 0,
                        "text": "stroller",
                        "rect": {"left": 10, "top": 20, "right": 110, "bottom": 60},
                    }
                ],
                "titles": [
                    {
                        "pageNumber": 0,
                        "level": 1,
                        "style": "1000254",
                        "rect": {"left": 10, "top": 20, "right": 110, "bottom": 60},
                    }
                ],
                "links": [
                    {
                        "pageNumber": 0,
                        "linkType": 1,
                        "direction": 0,
                        "style": "4",
                        "target": "/Note/Target.note",
                        "targetFileId": "F999",
                        "targetPageId": "P20260101000000xyz",
                        "targetPageNumber": None,
                        "rect": {"left": 10, "top": 20, "right": 110, "bottom": 60},
                    }
                ],
            }
        ],
    }
    assert WebNotePageMetadataVO.from_dict(page_data) == page_vo
