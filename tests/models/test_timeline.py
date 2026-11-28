"""Unit tests for `supernote.models.timeline` DTOs and VOs."""

from __future__ import annotations

from supernote.models.timeline import (
    TimelineDayCountVO,
    TimelineDaysRequestDTO,
    TimelineDaysVO,
    TimelinePagesRequestDTO,
    TimelinePagesVO,
    TimelinePageVO,
)


def test_timeline_request_dtos_parse_camel_case_aliases() -> None:
    days_dto = TimelineDaysRequestDTO.from_dict(
        {
            "startDate": "2026-03-01",
            "endDate": "2026-03-31",
            "includeBlank": True,
            "starredOnly": True,
            "tzOffsetMinutes": -480,
        }
    )
    assert days_dto == TimelineDaysRequestDTO(
        start_date="2026-03-01",
        end_date="2026-03-31",
        include_blank=True,
        starred_only=True,
        tz_offset_minutes=-480,
    )

    pages_dto = TimelinePagesRequestDTO.from_dict(
        {"limit": 25, "cursor": "1773496800000:1001:0"}
    )
    assert pages_dto.limit == 25
    assert pages_dto.cursor == "1773496800000:1001:0"
    assert pages_dto.include_blank is False


def test_timeline_vos_serialize_with_camel_case_aliases_and_string_ids() -> None:
    pages_vo = TimelinePagesVO(
        items=[
            TimelinePageVO(
                date="2026-03-14",
                timestamp_ms=1773496800000,
                file_id=1001,
                file_name="Daily.note",
                page_index=2,
                page_id="P20260314120000",
                sources=["created"],
                is_blank=False,
                has_five_star=True,
                keywords=["roadmap"],
                summary="Reviewed Q2 milestones",
                image_url="http://example.test/api/oss/png/1001/2?sig=abc",
            )
        ],
        next_cursor="1773496800000:1001:2",
        has_more=True,
    )
    assert pages_vo.to_dict() == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "items": [
            {
                "date": "2026-03-14",
                "timestampMs": 1773496800000,
                "fileId": "1001",
                "fileName": "Daily.note",
                "pageIndex": 2,
                "pageId": "P20260314120000",
                "sources": ["created"],
                "isBlank": False,
                "hasFiveStar": True,
                "keywords": ["roadmap"],
                "summary": "Reviewed Q2 milestones",
                "imageUrl": "http://example.test/api/oss/png/1001/2?sig=abc",
            }
        ],
        "nextCursor": "1773496800000:1001:2",
        "hasMore": True,
    }

    days_vo = TimelineDaysVO(
        days=[
            TimelineDayCountVO(
                date="2026-03-14",
                count=3,
                created_count=2,
                edited_count=1,
                dated_count=1,
            )
        ]
    )
    assert days_vo.to_dict() == {
        "success": True,
        "errorCode": None,
        "errorMsg": None,
        "days": [
            {
                "date": "2026-03-14",
                "count": 3,
                "createdCount": 2,
                "editedCount": 1,
                "datedCount": 1,
            }
        ],
    }
