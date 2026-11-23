"""HTTP route tests for `supernote.server.components.transcript.http`."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.exceptions import ApiException, NotFoundException
from supernote.client.extended import ExtendedClient
from supernote.models.user import UserRegisterDTO
from supernote.server.components.transcript import TRANSCRIPT_SERVICE_KEY
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.user import UserService


async def test_transcript_route_returns_pages_and_supports_range_slicing(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify POST /api/extended/transcript returns structured pages and supports start/end slicing."""
    async with session_manager.session() as db:
        journal = UserFileDO(
            user_id=test_user_id,
            file_name="Journal.note",
            directory_id=0,
            storage_key="journal_transcript_key",
        )
        db.add(journal)
        await db.flush()
        db.add_all(
            [
                NotePageContentDO(
                    file_id=journal.id,
                    page_index=0,
                    page_id="P20231027120000abc",
                    text_content="Page 1 content.",
                ),
                NotePageContentDO(
                    file_id=journal.id,
                    page_index=1,
                    page_id="P20231028120000def",
                    text_content="Page 2 content.",
                ),
            ]
        )
        await db.commit()
        journal_id = int(journal.id)

    full = await extended_client.get_transcript(file_id=journal_id)
    assert [(p.page_index, p.page_id, p.text, p.date) for p in full.pages] == [
        (0, "P20231027120000abc", "Page 1 content.", "2023-10-27"),
        (1, "P20231028120000def", "Page 2 content.", "2023-10-28"),
    ]

    sliced = await extended_client.get_transcript(
        file_id=journal_id, start_index=1, end_index=1
    )
    assert [(p.page_index, p.page_id, p.text, p.date) for p in sliced.pages] == [
        (1, "P20231028120000def", "Page 2 content.", "2023-10-28"),
    ]


async def test_transcript_route_returns_404_for_inaccessible_or_empty_notebooks(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    user_service: UserService,
    test_user_id: int,
) -> None:
    """Verify POST /api/extended/transcript returns 404 for other users', soft-deleted, unprocessed, or missing files."""
    other_account = await user_service.register(
        UserRegisterDTO(email="other_transcript_http@example.com", password="a" * 32)
    )
    async with session_manager.session() as db:
        other_user_file = UserFileDO(
            user_id=other_account.id,
            file_name="Private.note",
            directory_id=0,
            storage_key="private_transcript_key",
        )
        deleted_file = UserFileDO(
            user_id=test_user_id,
            file_name="Deleted.note",
            directory_id=0,
            is_active="N",
            storage_key="deleted_transcript_key",
        )
        unprocessed_file = UserFileDO(
            user_id=test_user_id,
            file_name="Pending.note",
            directory_id=0,
            is_active="Y",
            storage_key="pending_transcript_key",
        )
        db.add_all([other_user_file, deleted_file, unprocessed_file])
        await db.flush()
        db.add_all(
            [
                NotePageContentDO(
                    file_id=other_user_file.id,
                    page_index=0,
                    page_id="p0",
                    text_content="Secret content",
                ),
                NotePageContentDO(
                    file_id=deleted_file.id,
                    page_index=0,
                    page_id="p0",
                    text_content="Deleted content",
                ),
                NotePageContentDO(
                    file_id=unprocessed_file.id,
                    page_index=0,
                    page_id="p0",
                    text_content=None,
                ),
            ]
        )
        await db.commit()
        inaccessible_ids = (
            int(other_user_file.id),
            int(deleted_file.id),
            int(unprocessed_file.id),
            999999,
        )

    for inaccessible_id in inaccessible_ids:
        with pytest.raises(NotFoundException):
            await extended_client.get_transcript(file_id=inaccessible_id)


async def test_transcript_route_invalid_dto_and_errors(
    client: TestClient,
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
    user_service: UserService,
) -> None:
    """Verify POST /api/extended/transcript handles 400, 404, and 500 error paths."""
    assert client.app is not None

    bad_resp = await client.post(
        "/api/extended/transcript",
        json={"invalid": "payload"},
        headers=auth_headers,
    )
    assert bad_resp.status == 400

    with (
        patch.object(user_service, "get_user_id", return_value=None),
        pytest.raises(NotFoundException),
    ):
        await extended_client.get_transcript(file_id=101)

    with (
        patch.object(
            client.app[TRANSCRIPT_SERVICE_KEY],
            "get_page_transcripts",
            side_effect=RuntimeError("Transcript crash"),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.get_transcript(file_id=101)
