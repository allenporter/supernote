from dataclasses import replace

import pytest

from supernote.models.extended import VocabularySource
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.vocabulary import ROOT_SCOPE_ID
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.events import NoteDeletedEvent, NoteUpdatedEvent
from supernote.server.exceptions import FileNotFound, VocabularyTermNotFound
from supernote.server.services.vocabulary import (
    MAX_PROMPT_TERMS,
    VocabularyService,
)

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


@pytest.fixture
def vocabulary_service(session_manager: DatabaseSessionManager) -> VocabularyService:
    return VocabularyService(session_manager)


@pytest.fixture(autouse=True)
async def tree(session_manager: DatabaseSessionManager) -> None:
    """NOTE/Note/{Work/Projects/{Plan, Notes}, Loose}.note, plus Journal.note at the root."""
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
                    id=ELSEWHERE_ID,
                    user_id=USER_ID,
                    directory_id=ROOT_SCOPE_ID,
                    file_name="Journal.note",
                ),
            ]
        )
        await session.commit()


async def test_add_and_list_terms(vocabulary_service: VocabularyService) -> None:
    added = await vocabulary_service.add_terms(USER_ID, ["Lovelace", "  Babbage  "])
    assert [(t.term, t.scope_id, t.source) for t in added] == [
        ("Lovelace", ROOT_SCOPE_ID, VocabularySource.MANUAL),
        ("Babbage", ROOT_SCOPE_ID, VocabularySource.MANUAL),
    ]
    assert await vocabulary_service.list_terms(USER_ID) == added
    assert await vocabulary_service.list_terms(OTHER_USER_ID) == []


async def test_add_terms_is_idempotent_and_case_insensitive(
    vocabulary_service: VocabularyService,
) -> None:
    first = await vocabulary_service.add_terms(USER_ID, ["Lovelace"])
    again = await vocabulary_service.add_terms(USER_ID, ["lovelace", "LOVELACE"])
    assert again == first
    assert len(await vocabulary_service.list_terms(USER_ID)) == 1


async def test_add_terms_validates_scope_and_terms(
    vocabulary_service: VocabularyService,
) -> None:
    with pytest.raises(FileNotFound):
        await vocabulary_service.add_terms(USER_ID, ["Lovelace"], scope_id=99999)
    with pytest.raises(FileNotFound):
        await vocabulary_service.add_terms(
            OTHER_USER_ID, ["Lovelace"], scope_id=WORK_FOLDER_ID
        )
    with pytest.raises(ValueError, match="Invalid vocabulary term"):
        await vocabulary_service.add_terms(USER_ID, ["   "])
    with pytest.raises(ValueError, match="Invalid vocabulary term"):
        await vocabulary_service.add_terms(USER_ID, ["x" * 65])
    assert await vocabulary_service.list_terms(USER_ID) == []


async def test_harvest_scopes_to_top_folder_and_filters(
    vocabulary_service: VocabularyService,
) -> None:
    await vocabulary_service.add_terms(USER_ID, ["Lovelace"])
    added = await vocabulary_service.harvest(
        USER_ID,
        NOTEBOOK_ID,
        [
            "Kestrel",
            "kestrel",
            "events",
            "lovelace",
            "",
            "y" * 65,
            "action item",
            "  --dry-run!  ",
            "U.N.",
            "#7",
            "one two three four five",
        ],
    )
    assert added == 4
    harvested = [
        (t.term, t.scope_id, t.origin_file_id)
        for t in await vocabulary_service.list_terms(USER_ID)
        if t.source == VocabularySource.HARVEST
    ]
    assert harvested == [
        ("Kestrel", WORK_FOLDER_ID, NOTEBOOK_ID),
        ("action item", WORK_FOLDER_ID, NOTEBOOK_ID),
        ("dry-run", WORK_FOLDER_ID, NOTEBOOK_ID),
        ("U.N.", WORK_FOLDER_ID, NOTEBOOK_ID),
    ]
    assert await vocabulary_service.harvest(USER_ID, SIBLING_ID, ["Kestrel"]) == 0


async def test_harvest_scope_outside_user_folders(
    vocabulary_service: VocabularyService,
) -> None:
    await vocabulary_service.harvest(USER_ID, LOOSE_NOTEBOOK_ID, ["Kestrel"])
    await vocabulary_service.harvest(USER_ID, ELSEWHERE_ID, ["Osprey"])
    assert [
        (t.term, t.scope_id) for t in await vocabulary_service.list_terms(USER_ID)
    ] == [("Kestrel", NOTE_FOLDER_ID), ("Osprey", ROOT_SCOPE_ID)]


async def test_harvest_ignores_files_of_other_users(
    vocabulary_service: VocabularyService,
) -> None:
    assert (
        await vocabulary_service.harvest(OTHER_USER_ID, NOTEBOOK_ID, ["Kestrel"]) == 0
    )
    assert await vocabulary_service.harvest(USER_ID, 99999, ["Kestrel"]) == 0


async def test_harvest_follows_keyword_removals_and_edits(
    vocabulary_service: VocabularyService,
) -> None:
    await vocabulary_service.add_terms(USER_ID, ["Osprey"], scope_id=WORK_FOLDER_ID)
    await vocabulary_service.harvest(USER_ID, NOTEBOOK_ID, ["Kestrl", "Heron", "Owl"])
    [owl] = [t for t in await vocabulary_service.list_terms(USER_ID) if t.term == "Owl"]
    await vocabulary_service.remove_term(USER_ID, owl.id)

    # A spelling fix on the device replaces the misspelling; a dropped keyword goes
    assert await vocabulary_service.harvest(USER_ID, NOTEBOOK_ID, ["Kestrel"]) == 1
    assert [
        (t.term, t.source, t.is_suppressed)
        for t in await vocabulary_service.list_terms(USER_ID, include_suppressed=True)
    ] == [
        ("Osprey", VocabularySource.MANUAL, False),
        ("Owl", VocabularySource.HARVEST, True),
        ("Kestrel", VocabularySource.HARVEST, False),
    ]


async def test_harvest_keeps_terms_the_user_took_over(
    vocabulary_service: VocabularyService,
) -> None:
    await vocabulary_service.harvest(USER_ID, NOTEBOOK_ID, ["Kestrel"])
    [term] = await vocabulary_service.list_terms(USER_ID)
    await vocabulary_service.move_term(USER_ID, term.id, ROOT_SCOPE_ID)

    await vocabulary_service.harvest(USER_ID, NOTEBOOK_ID, [])
    assert [t.term for t in await vocabulary_service.list_terms(USER_ID)] == ["Kestrel"]


async def test_harvest_follows_a_moved_notebook(
    vocabulary_service: VocabularyService, session_manager: DatabaseSessionManager
) -> None:
    await vocabulary_service.harvest(USER_ID, NOTEBOOK_ID, ["Kestrel"])
    async with session_manager.session() as session:
        note = await session.get(UserFileDO, NOTEBOOK_ID)
        assert note
        note.directory_id = NOTE_FOLDER_ID
        await session.commit()

    assert await vocabulary_service.harvest(USER_ID, NOTEBOOK_ID, ["Kestrel"]) == 1
    assert [
        (t.term, t.scope_id) for t in await vocabulary_service.list_terms(USER_ID)
    ] == [("Kestrel", NOTE_FOLDER_ID)]


async def test_harvest_shared_keyword_moves_to_remaining_notebook(
    vocabulary_service: VocabularyService,
) -> None:
    await vocabulary_service.harvest(USER_ID, NOTEBOOK_ID, ["Kestrel"])
    assert await vocabulary_service.harvest(USER_ID, SIBLING_ID, ["Kestrel"]) == 0

    await vocabulary_service.harvest(USER_ID, NOTEBOOK_ID, [])
    assert await vocabulary_service.list_terms(USER_ID) == []
    assert await vocabulary_service.harvest(USER_ID, SIBLING_ID, ["Kestrel"]) == 1
    assert [t.origin_file_id for t in await vocabulary_service.list_terms(USER_ID)] == [
        SIBLING_ID
    ]


async def test_deleted_notebook_takes_its_terms(
    vocabulary_service: VocabularyService,
) -> None:
    await vocabulary_service.add_terms(USER_ID, ["Lovelace"], scope_id=WORK_FOLDER_ID)
    await vocabulary_service.harvest(USER_ID, NOTEBOOK_ID, ["Kestrel", "Heron"])
    await vocabulary_service.harvest(USER_ID, SIBLING_ID, ["Osprey"])
    [heron] = [
        t for t in await vocabulary_service.list_terms(USER_ID) if t.term == "Heron"
    ]
    await vocabulary_service.remove_term(USER_ID, heron.id)

    await vocabulary_service.handle_note_deleted(
        NoteUpdatedEvent(file_id=NOTEBOOK_ID, user_id=USER_ID, file_path="Plan.note")
    )
    await vocabulary_service.handle_note_deleted(
        NoteDeletedEvent(file_id=NOTEBOOK_ID, user_id=OTHER_USER_ID)
    )
    assert len(await vocabulary_service.list_terms(USER_ID)) == 3

    await vocabulary_service.handle_note_deleted(
        NoteDeletedEvent(file_id=NOTEBOOK_ID, user_id=USER_ID)
    )
    assert [
        (t.term, t.is_suppressed)
        for t in await vocabulary_service.list_terms(USER_ID, include_suppressed=True)
    ] == [("Lovelace", False), ("Heron", True), ("Osprey", False)]


async def test_removed_harvest_term_stays_removed(
    vocabulary_service: VocabularyService,
) -> None:
    await vocabulary_service.harvest(USER_ID, NOTEBOOK_ID, ["Kestrel"])
    [term] = await vocabulary_service.list_terms(USER_ID)

    await vocabulary_service.remove_term(USER_ID, term.id)
    assert await vocabulary_service.list_terms(USER_ID) == []
    assert await vocabulary_service.harvest(USER_ID, SIBLING_ID, ["Kestrel"]) == 0
    with pytest.raises(VocabularyTermNotFound):
        await vocabulary_service.remove_term(USER_ID, term.id)

    # Adding it by hand in the same scope brings it back as the user's own term
    [restored] = await vocabulary_service.add_terms(
        USER_ID, ["Kestrel"], scope_id=WORK_FOLDER_ID
    )
    assert restored == replace(
        term, scope_path="Note/Work", source=VocabularySource.MANUAL
    )


async def test_remove_manual_term_deletes_it(
    vocabulary_service: VocabularyService,
) -> None:
    [term] = await vocabulary_service.add_terms(USER_ID, ["Lovelace"])
    with pytest.raises(VocabularyTermNotFound):
        await vocabulary_service.remove_term(OTHER_USER_ID, term.id)

    await vocabulary_service.remove_term(USER_ID, term.id)
    assert await vocabulary_service.list_terms(USER_ID) == []
    assert await vocabulary_service.harvest(USER_ID, NOTEBOOK_ID, ["Lovelace"]) == 1


async def test_terms_for_notebook_orders_nearest_scope_first(
    vocabulary_service: VocabularyService,
) -> None:
    await vocabulary_service.add_terms(USER_ID, ["Everywhere"])
    await vocabulary_service.add_terms(USER_ID, ["WorkWide"], scope_id=WORK_FOLDER_ID)
    await vocabulary_service.harvest(USER_ID, NOTEBOOK_ID, ["Harvested"])
    await vocabulary_service.add_terms(
        USER_ID, ["ProjectWide"], scope_id=PROJECTS_FOLDER_ID
    )
    await vocabulary_service.add_terms(USER_ID, ["PlanOnly", "everywhere"], NOTEBOOK_ID)

    assert await vocabulary_service.terms_for_notebook(USER_ID, NOTEBOOK_ID) == [
        "PlanOnly",
        "everywhere",
        "ProjectWide",
        "WorkWide",
        "Harvested",
    ]
    assert await vocabulary_service.terms_for_notebook(USER_ID, SIBLING_ID) == [
        "ProjectWide",
        "WorkWide",
        "Harvested",
        "Everywhere",
    ]
    assert await vocabulary_service.terms_for_notebook(USER_ID, ELSEWHERE_ID) == [
        "Everywhere"
    ]
    assert await vocabulary_service.terms_for_notebook(OTHER_USER_ID, NOTEBOOK_ID) == []


async def test_terms_for_notebook_is_capped(
    vocabulary_service: VocabularyService,
) -> None:
    await vocabulary_service.add_terms(
        USER_ID, [f"Term{i}" for i in range(MAX_PROMPT_TERMS + 5)]
    )
    terms = await vocabulary_service.terms_for_notebook(USER_ID, NOTEBOOK_ID)
    assert terms == [f"Term{i}" for i in range(MAX_PROMPT_TERMS)]


async def test_terms_describe_scope_and_origin(
    vocabulary_service: VocabularyService,
) -> None:
    await vocabulary_service.add_terms(USER_ID, ["Everywhere"])
    await vocabulary_service.add_terms(USER_ID, ["PlanOnly"], scope_id=NOTEBOOK_ID)
    await vocabulary_service.harvest(USER_ID, NOTEBOOK_ID, ["Kestrel"])
    assert [
        (t.term, t.scope_path, t.origin_name)
        for t in await vocabulary_service.list_terms(USER_ID)
    ] == [
        ("Everywhere", "", None),
        ("PlanOnly", "Note/Work/Projects/Plan.note", None),
        ("Kestrel", "Note/Work", "Plan.note"),
    ]


async def test_move_harvested_term_keeps_it_from_returning(
    vocabulary_service: VocabularyService,
) -> None:
    await vocabulary_service.harvest(USER_ID, NOTEBOOK_ID, ["Kestrel"])
    [term] = await vocabulary_service.list_terms(USER_ID)

    moved = await vocabulary_service.move_term(USER_ID, term.id, PROJECTS_FOLDER_ID)
    assert (moved.id, moved.scope_id, moved.scope_path, moved.source) == (
        term.id,
        PROJECTS_FOLDER_ID,
        "Note/Work/Projects",
        VocabularySource.MANUAL,
    )
    assert await vocabulary_service.harvest(USER_ID, SIBLING_ID, ["Kestrel"]) == 0
    assert await vocabulary_service.terms_for_notebook(USER_ID, ELSEWHERE_ID) == []

    removed = [
        t
        for t in await vocabulary_service.list_terms(USER_ID, include_suppressed=True)
        if t.is_suppressed
    ]
    assert [(t.term, t.scope_id, t.origin_file_id) for t in removed] == [
        ("Kestrel", WORK_FOLDER_ID, NOTEBOOK_ID)
    ]

    assert (
        await vocabulary_service.move_term(USER_ID, term.id, PROJECTS_FOLDER_ID)
        == moved
    )


async def test_move_term_merges_into_existing(
    vocabulary_service: VocabularyService,
) -> None:
    [everywhere] = await vocabulary_service.add_terms(USER_ID, ["Kestrel"])
    [local] = await vocabulary_service.add_terms(
        USER_ID, ["kestrel"], scope_id=WORK_FOLDER_ID
    )
    merged = await vocabulary_service.move_term(USER_ID, local.id, ROOT_SCOPE_ID)
    assert merged.id == everywhere.id
    assert [t.id for t in await vocabulary_service.list_terms(USER_ID)] == [
        everywhere.id
    ]


async def test_move_term_validates(vocabulary_service: VocabularyService) -> None:
    [term] = await vocabulary_service.add_terms(USER_ID, ["Kestrel"])
    with pytest.raises(VocabularyTermNotFound):
        await vocabulary_service.move_term(USER_ID, 12345, ROOT_SCOPE_ID)
    with pytest.raises(FileNotFound):
        await vocabulary_service.move_term(USER_ID, term.id, 12345)


async def test_restore_term(vocabulary_service: VocabularyService) -> None:
    await vocabulary_service.harvest(USER_ID, NOTEBOOK_ID, ["Kestrel"])
    [term] = await vocabulary_service.list_terms(USER_ID)
    with pytest.raises(VocabularyTermNotFound):
        await vocabulary_service.restore_term(USER_ID, term.id)

    await vocabulary_service.remove_term(USER_ID, term.id)
    restored = await vocabulary_service.restore_term(USER_ID, term.id)
    assert restored == term
    assert await vocabulary_service.list_terms(USER_ID) == [term]
