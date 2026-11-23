"""Unit tests for `supernote.server.components.transcript.service.TranscriptService`."""

from __future__ import annotations

import pytest

from supernote.server.components.transcript import PageTranscript, TranscriptService
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import (
    NotePageContentDO,
    NotePageMetadataDO,
)
from supernote.server.db.session import DatabaseSessionManager


@pytest.fixture
def transcript_service(
    session_manager: DatabaseSessionManager,
) -> TranscriptService:
    return TranscriptService(session_manager=session_manager)


async def test_get_transcript(
    transcript_service: TranscriptService,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify formatted and structured transcript retrieval, range slicing, and access checks."""
    user_id = 1
    file_id = 101

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id, user_id=user_id, file_name="Journal.note", directory_id=0
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P20231027120000abc",
                text_content="Page 1 content.",
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=1,
                page_id="P20231028120000def",
                text_content="Page 2 content.",
            )
        )
        await session.commit()

    # Full transcript
    transcript = await transcript_service.get_transcript(
        user_id=user_id, file_id=file_id
    )
    assert transcript is not None
    assert "Page 1 content." in transcript
    assert "Page 2 content." in transcript
    assert "--- Page 1 ---" in transcript
    assert "Notebook Filename: Journal.note" in transcript
    assert "Page ID: P20231027120000abc" in transcript
    assert "Page Date (Inferred): 2023-10-27" in transcript
    assert "Page Date (Inferred): 2023-10-28" in transcript

    # Specific page
    page1 = await transcript_service.get_transcript(
        user_id=user_id, file_id=file_id, page_index=0
    )
    assert page1 == "Page 1 content."

    # Unauthorized
    assert await transcript_service.get_transcript(user_id=99, file_id=file_id) is None

    # Page range (Page 2 only via range)
    range_trans = await transcript_service.get_transcript(
        user_id=user_id, file_id=file_id, start_index=1, end_index=1
    )
    assert range_trans is not None
    assert "Page 2 content." in range_trans
    assert "Page 1 content." not in range_trans
    assert "--- Page 2 ---" in range_trans
    assert "Page ID: P20231028120000def" in range_trans

    # Structured per-page transcripts
    page_transcripts = await transcript_service.get_page_transcripts(
        user_id=user_id, file_id=file_id
    )
    assert page_transcripts == [
        PageTranscript(
            page_index=0,
            page_id="P20231027120000abc",
            text="Page 1 content.",
            date="2023-10-27",
        ),
        PageTranscript(
            page_index=1,
            page_id="P20231028120000def",
            text="Page 2 content.",
            date="2023-10-28",
        ),
    ]

    # Structured per-page transcripts with range filter
    range_pages = await transcript_service.get_page_transcripts(
        user_id=user_id, file_id=file_id, start_index=1, end_index=1
    )
    assert range_pages == [
        PageTranscript(
            page_index=1,
            page_id="P20231028120000def",
            text="Page 2 content.",
            date="2023-10-28",
        ),
    ]

    # Unauthorized structured per-page transcripts
    assert (
        await transcript_service.get_page_transcripts(user_id=99, file_id=file_id) == []
    )

    # Soft-deleted notebook and unprocessed notebook (no OCR text yet)
    deleted_file_id = 102
    unprocessed_file_id = 103
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=deleted_file_id,
                    user_id=user_id,
                    file_name="Deleted.note",
                    directory_id=0,
                    is_active="N",
                ),
                NotePageContentDO(
                    file_id=deleted_file_id,
                    page_index=0,
                    page_id="p0",
                    text_content="Deleted content",
                ),
                UserFileDO(
                    id=unprocessed_file_id,
                    user_id=user_id,
                    file_name="Pending.note",
                    directory_id=0,
                    is_active="Y",
                ),
                NotePageContentDO(
                    file_id=unprocessed_file_id,
                    page_index=0,
                    page_id="p0",
                    text_content=None,
                ),
            ]
        )
        await session.commit()

    assert (
        await transcript_service.get_transcript(
            user_id=user_id, file_id=deleted_file_id
        )
        is None
    )
    assert (
        await transcript_service.get_page_transcripts(
            user_id=user_id, file_id=deleted_file_id
        )
        == []
    )
    assert (
        await transcript_service.get_transcript(
            user_id=user_id, file_id=unprocessed_file_id
        )
        is None
    )
    assert (
        await transcript_service.get_page_transcripts(
            user_id=user_id, file_id=unprocessed_file_id
        )
        == []
    )


async def test_get_transcript_includes_verified_page_keywords(
    transcript_service: TranscriptService,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify get_transcript includes Page Keywords only for matching (page_id, content_hash) metadata rows."""
    user_id = 1
    file_id = 199

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=user_id,
                file_name="Architecture.note",
                directory_id=0,
                is_active="Y",
            )
        )
        session.add(
            NotePageContentDO(
                file_id=file_id,
                page_index=0,
                page_id="P20260301090000a",
                content_hash="h_arch",
                text_content="Discussed schema design.",
            )
        )
        session.add(
            NotePageMetadataDO(
                user_id=user_id,
                file_id=file_id,
                page_index=0,
                page_id="P20260301090000a",
                content_hash="h_arch",
                keywords_json='[{"KEYWORDPAGE": "1", "KEYWORD": "SQLite"}]',
            )
        )
        await session.commit()

    transcript = await transcript_service.get_transcript(
        user_id=user_id, file_id=file_id
    )
    assert transcript is not None
    assert "Page Keywords: SQLite" in transcript
