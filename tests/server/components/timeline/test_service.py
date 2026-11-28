"""Unit tests for `supernote.server.components.timeline.service`."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from supernote.models.events import DomainEventType
from supernote.models.timeline import TimelineDaysRequestDTO, TimelinePagesRequestDTO
from supernote.notebook.schema import KeywordMetadata
from supernote.server.components.timeline.service import TimelineService
from supernote.server.db.models.event_log import UserEventDO
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageMetadataDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.exceptions import InvalidInputError
from supernote.server.utils.note_content import infer_page_created_ms


def _utc_ms(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> int:
    return int(
        datetime(year, month, day, hour, minute, 0, tzinfo=UTC).timestamp() * 1000
    )


@pytest.mark.parametrize(
    ("page_id", "expected"),
    [
        ("P20260314153045123456ABCDEF123456", _utc_ms(2026, 3, 14, 15, 30) + 45_000),
        ("", None),
        ("F20260314153045", None),
        ("P99999999999999", None),
    ],
)
def test_infer_page_created_ms(page_id: str, expected: int | None) -> None:
    assert infer_page_created_ms(page_id) == expected


async def _seed_timeline_fixture(
    session_manager: DatabaseSessionManager,
    user_id: int,
    other_user_id: int = 999999,
) -> None:
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=1001,
                    user_id=user_id,
                    storage_key="k1001",
                    file_name="ProjectAlpha.note",
                    directory_id=0,
                    is_active="Y",
                    create_time=_utc_ms(2026, 1, 1),
                ),
                UserFileDO(
                    id=1002,
                    user_id=user_id,
                    storage_key="k1002",
                    file_name="DailyLog.note",
                    directory_id=0,
                    is_active="Y",
                    create_time=_utc_ms(2026, 2, 1),
                ),
                UserFileDO(
                    id=1003,
                    user_id=user_id,
                    storage_key="k1003",
                    file_name="Deleted.note",
                    directory_id=0,
                    is_active="N",
                    create_time=_utc_ms(2026, 3, 1),
                ),
                UserFileDO(
                    id=2001,
                    user_id=other_user_id,
                    storage_key="k2001",
                    file_name="OtherUser.note",
                    directory_id=0,
                    is_active="Y",
                    create_time=_utc_ms(2026, 3, 14),
                ),
                NotePageMetadataDO(
                    user_id=user_id,
                    file_id=1001,
                    page_index=0,
                    page_id="P20260310100000000000AAAAAAAAAAAA",
                    has_ink=True,
                    has_drawables=True,
                    page_json=json.dumps({"FIVESTAR": "1"}),
                    keywords_json=json.dumps(
                        [KeywordMetadata(keyword="roadmap").to_wire_dict()]
                    ),
                ),
                NotePageMetadataDO(
                    user_id=user_id,
                    file_id=1001,
                    page_index=1,
                    page_id="P20260314090000000000BBBBBBBBBBBB",
                    has_ink=False,
                    has_drawables=False,
                    page_json="{}",
                ),
                NotePageMetadataDO(
                    user_id=user_id,
                    file_id=1002,
                    page_index=0,
                    page_id="P20260314030000000000CCCCCCCCCCCC",
                    has_ink=True,
                    has_drawables=True,
                    page_json="{}",
                ),
                NotePageMetadataDO(
                    user_id=user_id,
                    file_id=1003,
                    page_index=0,
                    page_id="P20260314120000000000DDDDDDDDDDDD",
                    has_ink=True,
                    has_drawables=True,
                    page_json="{}",
                ),
                NotePageMetadataDO(
                    user_id=other_user_id,
                    file_id=2001,
                    page_index=0,
                    page_id="P20260314120000000000EEEEEEEEEEEE",
                    has_ink=True,
                    has_drawables=True,
                    page_json="{}",
                ),
                UserEventDO(
                    user_id=user_id,
                    seq=1,
                    timestamp_ms=_utc_ms(2026, 3, 14, 16, 0),
                    event_type=DomainEventType.NOTE_PAGES_DELTA.value,
                    actor="device:sn",
                    entity_type="file",
                    entity_id="1001",
                    related_file_id=1001,
                    payload={"modified_pages": ["P20260310100000000000AAAAAAAAAAAA"]},
                ),
                UserEventDO(
                    user_id=user_id,
                    seq=2,
                    timestamp_ms=_utc_ms(2026, 3, 14, 18, 0),
                    event_type=DomainEventType.NOTE_PAGES_DELTA.value,
                    actor="device:sn",
                    entity_type="file",
                    entity_id="1001",
                    related_file_id=1001,
                    payload={"modified_pages": ["P20260310100000000000AAAAAAAAAAAA"]},
                ),
                UserEventDO(
                    user_id=user_id,
                    seq=3,
                    timestamp_ms=_utc_ms(2026, 3, 14, 14, 0),
                    event_type=DomainEventType.NOTE_PAGES_DELTA.value,
                    actor="device:sn",
                    entity_type="file",
                    entity_id="1002",
                    related_file_id=1002,
                    payload={"modified_pages": ["P20260314030000000000CCCCCCCCCCCC"]},
                ),
            ]
        )
        await session.commit()


async def test_list_pages_merges_created_and_edited_and_excludes_inactive_and_blank(
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    await _seed_timeline_fixture(session_manager, test_user_id)
    service = TimelineService(session_manager=session_manager)

    result = await service.list_pages(test_user_id, TimelinePagesRequestDTO())
    assert [
        (i.date, i.file_id, i.page_index, i.sources, i.has_five_star, i.keywords)
        for i in result.items
    ] == [
        ("2026-03-14", 1001, 0, ["edited"], True, ["roadmap"]),
        ("2026-03-14", 1002, 0, ["created", "edited"], False, []),
        ("2026-03-10", 1001, 0, ["created"], True, ["roadmap"]),
    ]
    assert result.has_more is False
    assert result.next_cursor is None


async def test_list_pages_filters_by_date_range_blank_and_starred(
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    await _seed_timeline_fixture(session_manager, test_user_id)
    service = TimelineService(session_manager=session_manager)

    day_with_blank = await service.list_pages(
        test_user_id,
        TimelinePagesRequestDTO(
            start_date="2026-03-14", end_date="2026-03-14", include_blank=True
        ),
    )
    assert [(i.file_id, i.page_index, i.is_blank) for i in day_with_blank.items] == [
        (1001, 0, False),
        (1002, 0, False),
        (1001, 1, True),
    ]

    starred = await service.list_pages(
        test_user_id,
        TimelinePagesRequestDTO(starred_only=True, end_date="2026-03-10"),
    )
    assert [(i.date, i.file_id, i.sources) for i in starred.items] == [
        ("2026-03-10", 1001, ["created"])
    ]


async def test_list_pages_timezone_bucketing(
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    await _seed_timeline_fixture(session_manager, test_user_id)
    service = TimelineService(session_manager=session_manager)

    # DailyLog p0 created at 2026-03-14 03:00 UTC shifts to 2026-03-13 at UTC-8.
    result = await service.list_pages(
        test_user_id,
        TimelinePagesRequestDTO(
            start_date="2026-03-13", end_date="2026-03-13", tz_offset_minutes=-480
        ),
    )
    assert [(i.date, i.file_id, i.sources) for i in result.items] == [
        ("2026-03-13", 1002, ["created"])
    ]


async def test_list_pages_cursor_pagination(
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    await _seed_timeline_fixture(session_manager, test_user_id)
    service = TimelineService(session_manager=session_manager)

    page1 = await service.list_pages(test_user_id, TimelinePagesRequestDTO(limit=2))
    assert len(page1.items) == 2
    assert page1.has_more is True
    assert page1.next_cursor is not None

    page2 = await service.list_pages(
        test_user_id, TimelinePagesRequestDTO(limit=2, cursor=page1.next_cursor)
    )
    assert [(i.date, i.file_id) for i in page2.items] == [("2026-03-10", 1001)]
    assert page2.has_more is False
    assert page2.next_cursor is None


async def test_list_days_chunks_large_edited_pair_sets(
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify >400 edited (file_id, page_id) pairs resolve cleanly across SQL batches."""
    total_pages = 450
    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=5001,
                user_id=test_user_id,
                storage_key="k5001",
                file_name="BigNote.note",
                directory_id=0,
                is_active="Y",
                create_time=_utc_ms(2026, 1, 1),
            )
        )
        page_ids: list[str] = []
        for idx in range(total_pages):
            pid = f"P20260101000000{idx:06d}AAAAAAAAAAAA"
            page_ids.append(pid)
            session.add(
                NotePageMetadataDO(
                    user_id=test_user_id,
                    file_id=5001,
                    page_index=idx,
                    page_id=pid,
                    has_ink=True,
                    has_drawables=True,
                    page_json="{}",
                )
            )
        session.add(
            UserEventDO(
                user_id=test_user_id,
                seq=10,
                timestamp_ms=_utc_ms(2026, 3, 20, 12, 0),
                event_type=DomainEventType.NOTE_PAGES_DELTA.value,
                actor="device:sn",
                entity_type="file",
                entity_id="5001",
                related_file_id=5001,
                payload={"modified_pages": page_ids},
            )
        )
        await session.commit()

    service = TimelineService(session_manager=session_manager)
    days = await service.list_days(
        test_user_id,
        TimelineDaysRequestDTO(start_date="2026-03-01", end_date="2026-03-31"),
    )
    assert [(d.date, d.count, d.edited_count) for d in days.days] == [
        ("2026-03-20", total_pages, total_pages)
    ]


async def test_list_days_counts_per_day(
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    await _seed_timeline_fixture(session_manager, test_user_id)
    service = TimelineService(session_manager=session_manager)

    days = await service.list_days(
        test_user_id,
        TimelineDaysRequestDTO(start_date="2026-03-01", end_date="2026-03-31"),
    )
    assert [d.to_dict() for d in days.days] == [
        {"date": "2026-03-14", "count": 2, "createdCount": 1, "editedCount": 2},
        {"date": "2026-03-10", "count": 1, "createdCount": 1, "editedCount": 0},
    ]


@pytest.mark.parametrize(
    "req",
    [
        TimelinePagesRequestDTO(start_date="not-a-date"),
        TimelinePagesRequestDTO(start_date="2026-03-20", end_date="2026-03-10"),
        TimelinePagesRequestDTO(cursor="not-a-cursor"),
        TimelinePagesRequestDTO(cursor="a:b:c"),
        TimelinePagesRequestDTO(limit=0),
        TimelinePagesRequestDTO(limit=500),
        TimelinePagesRequestDTO(tz_offset_minutes=9999),
    ],
)
async def test_list_pages_rejects_invalid_inputs(
    session_manager: DatabaseSessionManager,
    test_user_id: int,
    req: TimelinePagesRequestDTO,
) -> None:
    service = TimelineService(session_manager=session_manager)
    with pytest.raises(InvalidInputError):
        await service.list_pages(test_user_id, req)
