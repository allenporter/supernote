"""OCR vocabulary read from the keywords marked on a Supernote device."""

import json

import pytest

from supernote.server.components.transcript.vocabulary import (
    MAX_PROMPT_TERMS,
    notebook_terms,
)
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageMetadataDO
from supernote.server.db.session import DatabaseSessionManager

ROOT_SCOPE_ID = 0
USER_ID = 100
OTHER_USER_ID = 200
NOTE_CONTAINER_ID = 1
NOTE_FOLDER_ID = 2
WORK_FOLDER_ID = 10
PROJECTS_FOLDER_ID = 11
NOTEBOOK_ID = 20
SIBLING_ID = 21
ELSEWHERE_ID = 22
LOOSE_NOTEBOOK_ID = 23
OTHER_LOOSE_NOTEBOOK_ID = 24


async def _terms(
    session_manager: DatabaseSessionManager, file_id: int, user_id: int = USER_ID
) -> list[str]:
    async with session_manager.session() as session:
        return await notebook_terms(session, user_id, file_id)


@pytest.fixture(autouse=True)
async def tree(session_manager: DatabaseSessionManager) -> None:
    """NOTE/Note/{Work/Projects/{Plan, Notes}, Loose, Stray}.note, plus Journal.note at the root."""
    async with session_manager.session() as session:
        session.add_all(
            [
                UserFileDO(
                    id=NOTE_CONTAINER_ID,
                    user_id=USER_ID,
                    directory_id=ROOT_SCOPE_ID,
                    file_name="NOTE",
                    is_folder="Y",
                ),
                UserFileDO(
                    id=NOTE_FOLDER_ID,
                    user_id=USER_ID,
                    directory_id=NOTE_CONTAINER_ID,
                    file_name="Note",
                    is_folder="Y",
                ),
                UserFileDO(
                    id=WORK_FOLDER_ID,
                    user_id=USER_ID,
                    directory_id=NOTE_FOLDER_ID,
                    file_name="Work",
                    is_folder="Y",
                ),
                UserFileDO(
                    id=PROJECTS_FOLDER_ID,
                    user_id=USER_ID,
                    directory_id=WORK_FOLDER_ID,
                    file_name="Projects",
                    is_folder="Y",
                ),
                UserFileDO(
                    id=NOTEBOOK_ID,
                    user_id=USER_ID,
                    directory_id=PROJECTS_FOLDER_ID,
                    file_name="Plan.note",
                ),
                UserFileDO(
                    id=SIBLING_ID,
                    user_id=USER_ID,
                    directory_id=PROJECTS_FOLDER_ID,
                    file_name="Notes.note",
                ),
                UserFileDO(
                    id=LOOSE_NOTEBOOK_ID,
                    user_id=USER_ID,
                    directory_id=NOTE_FOLDER_ID,
                    file_name="Loose.note",
                ),
                UserFileDO(
                    id=OTHER_LOOSE_NOTEBOOK_ID,
                    user_id=USER_ID,
                    directory_id=NOTE_FOLDER_ID,
                    file_name="Stray.note",
                ),
                UserFileDO(
                    id=ELSEWHERE_ID,
                    user_id=USER_ID,
                    directory_id=ROOT_SCOPE_ID,
                    file_name="Journal.note",
                ),
            ]
        )
        await session.commit()


async def _keywords(
    session_manager: DatabaseSessionManager,
    file_id: int,
    *pages: list[str],
    user_id: int = USER_ID,
) -> None:
    """Give a notebook pages whose metadata carries these device keywords."""
    async with session_manager.session() as session:
        for index, words in enumerate(pages):
            session.add(
                NotePageMetadataDO(
                    user_id=user_id,
                    file_id=file_id,
                    page_index=index,
                    page_id=f"{file_id}p{index}",
                    keywords_json=json.dumps(
                        [{"KEYWORDPAGE": str(index + 1), "KEYWORD": w} for w in words]
                    ),
                )
            )
        await session.commit()


async def test_own_keywords_first_then_the_folders(
    session_manager: DatabaseSessionManager,
) -> None:
    await _keywords(session_manager, NOTEBOOK_ID, ["Kestrel"], ["Heron"])
    await _keywords(session_manager, SIBLING_ID, ["Osprey", "kestrel"])
    await _keywords(session_manager, ELSEWHERE_ID, ["Lovelace"])
    await _keywords(session_manager, LOOSE_NOTEBOOK_ID, ["Babbage"])
    await _keywords(session_manager, OTHER_LOOSE_NOTEBOOK_ID, ["Hopper"])

    # Plan and Notes share Work/; the journal and the loose notebooks do not,
    # not even with each other.
    assert await _terms(session_manager, NOTEBOOK_ID) == [
        "Kestrel",
        "Heron",
        "Osprey",
    ]
    assert await _terms(session_manager, ELSEWHERE_ID) == ["Lovelace"]
    assert await _terms(session_manager, LOOSE_NOTEBOOK_ID) == ["Babbage"]


async def test_keywords_that_would_not_help_are_left_out(
    session_manager: DatabaseSessionManager,
) -> None:
    await _keywords(
        session_manager,
        NOTEBOOK_ID,
        ["  Kestrel!  ", "2026", "the", "a whole sentence of notes here", "U.N."],
    )
    assert await _terms(session_manager, NOTEBOOK_ID) == [
        "Kestrel",
        "U.N.",
    ]


async def test_a_deleted_notebook_or_another_user_contributes_nothing(
    session_manager: DatabaseSessionManager,
) -> None:
    await _keywords(session_manager, SIBLING_ID, ["Osprey"])
    await _keywords(session_manager, NOTEBOOK_ID, ["Owl"], user_id=OTHER_USER_ID)
    async with session_manager.session() as session:
        sibling = await session.get(UserFileDO, SIBLING_ID)
        assert sibling is not None
        sibling.is_active = "N"
        await session.commit()
    assert await _terms(session_manager, NOTEBOOK_ID) == []
    assert await _terms(session_manager, NOTEBOOK_ID, user_id=OTHER_USER_ID) == []


async def test_capped(
    session_manager: DatabaseSessionManager,
) -> None:
    await _keywords(
        session_manager, NOTEBOOK_ID, [f"Term{i}" for i in range(MAX_PROMPT_TERMS + 5)]
    )
    terms = await _terms(session_manager, NOTEBOOK_ID)
    assert terms == [f"Term{i}" for i in range(MAX_PROMPT_TERMS)]


@pytest.mark.parametrize(
    "keywords_json", ["not json", '{"KEYWORD": "Kestrel"}', "[1, null]"]
)
async def test_malformed_keyword_metadata_is_ignored(
    session_manager: DatabaseSessionManager,
    keywords_json: str,
) -> None:
    async with session_manager.session() as session:
        session.add(
            NotePageMetadataDO(
                user_id=USER_ID,
                file_id=NOTEBOOK_ID,
                page_index=0,
                page_id="p0",
                keywords_json=keywords_json,
            )
        )
        await session.commit()
    assert await _terms(session_manager, NOTEBOOK_ID) == []


async def test_soft_deleted_target_notebook_returns_no_terms(
    session_manager: DatabaseSessionManager,
) -> None:
    await _keywords(session_manager, SIBLING_ID, ["Osprey"])
    async with session_manager.session() as session:
        target = await session.get(UserFileDO, NOTEBOOK_ID)
        assert target is not None
        target.is_active = "N"
        await session.commit()
    assert await _terms(session_manager, NOTEBOOK_ID) == []


async def test_more_recently_updated_sibling_wins_folder_order(
    session_manager: DatabaseSessionManager,
) -> None:
    newer_sibling_id = 25
    async with session_manager.session() as session:
        older = await session.get(UserFileDO, SIBLING_ID)
        assert older is not None
        older.update_time = 1_000
        session.add(
            UserFileDO(
                id=newer_sibling_id,
                user_id=USER_ID,
                directory_id=PROJECTS_FOLDER_ID,
                file_name="Recent.note",
                update_time=2_000,
            )
        )
        await session.commit()
    await _keywords(session_manager, SIBLING_ID, ["ArchiveTerm"])
    await _keywords(session_manager, newer_sibling_id, ["CurrentTerm"])

    assert await _terms(session_manager, NOTEBOOK_ID) == [
        "CurrentTerm",
        "ArchiveTerm",
    ]


async def test_an_unknown_notebook_has_no_terms(
    session_manager: DatabaseSessionManager,
) -> None:
    assert await _terms(session_manager, 999) == []


async def test_common_words_and_plurals_are_filtered_while_phrases_survive(
    session_manager: DatabaseSessionManager,
) -> None:
    await _keywords(
        session_manager,
        NOTEBOOK_ID,
        [
            "the",
            "API",
            "events",
            "Boxes",
            "milestones",
            "  Logic ",
            "Lovelace",
            "ks-tilt",
            "action item",
            "",
            "   ",
        ],
    )
    assert await _terms(session_manager, NOTEBOOK_ID) == [
        "Boxes",
        "Lovelace",
        "ks-tilt",
        "action item",
    ]
