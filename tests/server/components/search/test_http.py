"""HTTP route tests for `supernote.server.components.search.http`."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient

from supernote.client.exceptions import ApiException, NotFoundException
from supernote.client.extended import ExtendedClient
from supernote.server.ai.models.embedding import EmbeddingTaskType
from supernote.server.components.search import SEARCH_SERVICE_KEY
from supernote.server.config import AiConfig, ModelConfig, ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.keys import EMBEDDING_MODEL_KEY
from supernote.server.services.user import UserService


@pytest.fixture
def server_config(server_config: ServerConfig) -> ServerConfig:
    """Configure the fake embedding provider through the `ai` + `fake_ai` components."""
    server_config.ai = AiConfig(
        embedding=ModelConfig(provider="fake", model="fake-embedding-v1"),
    )
    return server_config


async def test_search_route_ranks_matching_chunks(
    client: TestClient,
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify POST /api/extended/search ranks chunks by cosine similarity."""
    assert client.app is not None
    embedding_model = client.app[EMBEDDING_MODEL_KEY]
    assert embedding_model is not None
    cats_vec = await embedding_model.embed(
        "cats", task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT
    )
    orthogonal_vec = [cats_vec[1], -cats_vec[0], 0.0]

    async with session_manager.session() as db:
        file1 = UserFileDO(
            user_id=test_user_id,
            file_name="Journal.note",
            directory_id=0,
            storage_key="journal_key",
        )
        file2 = UserFileDO(
            user_id=test_user_id,
            file_name="Monthly Plan.note",
            directory_id=0,
            storage_key="monthly_key",
        )
        db.add_all([file1, file2])
        await db.flush()
        db.add_all(
            [
                NotePageContentDO(
                    file_id=file1.id,
                    page_index=0,
                    page_id="p0",
                    text_content="This is the first chunk about cats.",
                    embedding=json.dumps(cats_vec),
                    embedding_model=embedding_model.model_id,
                ),
                NotePageContentDO(
                    file_id=file2.id,
                    page_index=0,
                    page_id="p0",
                    text_content="This is the second chunk about dogs.",
                    embedding=json.dumps(orthogonal_vec),
                    embedding_model=embedding_model.model_id,
                ),
            ]
        )
        await db.commit()
        file_id_1, file_id_2 = int(file1.id), int(file2.id)

    response = await extended_client.search(query="cats", top_n=5)

    assert len(response.results) == 2
    assert response.results[0].file_id == file_id_1
    assert response.results[0].file_name == "Journal.note"
    assert response.results[0].score > 0.99
    assert response.results[0].text_preview == "This is the first chunk about cats."
    assert response.results[0].date is None
    assert response.results[1].file_id == file_id_2
    assert abs(response.results[1].score) < 0.01


async def test_search_route_excludes_inactive_files(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify soft-deleted files are excluded from search results."""
    async with session_manager.session() as db:
        active = UserFileDO(
            user_id=test_user_id,
            file_name="Active.note",
            directory_id=0,
            is_active="Y",
            storage_key="active_key",
        )
        deleted = UserFileDO(
            user_id=test_user_id,
            file_name="Deleted.note",
            directory_id=0,
            is_active="N",
            storage_key="deleted_key",
        )
        db.add_all([active, deleted])
        await db.flush()
        db.add_all(
            [
                NotePageContentDO(
                    file_id=active.id,
                    page_index=0,
                    page_id="p0",
                    text_content="Cats are active pets.",
                    embedding=json.dumps([1.0, 0.0, 0.0]),
                    embedding_model="fake-embedding-v1",
                ),
                NotePageContentDO(
                    file_id=deleted.id,
                    page_index=0,
                    page_id="p0",
                    text_content="Cats were deleted pets.",
                    embedding=json.dumps([1.0, 0.0, 0.0]),
                    embedding_model="fake-embedding-v1",
                ),
            ]
        )
        await db.commit()
        active_id = int(active.id)

    response = await extended_client.search(query="cats", top_n=5)

    assert len(response.results) == 1
    assert response.results[0].file_id == active_id
    assert response.results[0].file_name == "Active.note"


async def test_search_route_with_name_filter(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify name_filter restricts search results to matching notebook filenames."""
    async with session_manager.session() as db:
        journal = UserFileDO(
            user_id=test_user_id,
            file_name="Journal.note",
            directory_id=0,
            storage_key="journal_filter_key",
        )
        monthly = UserFileDO(
            user_id=test_user_id,
            file_name="Monthly Plan.note",
            directory_id=0,
            storage_key="monthly_filter_key",
        )
        db.add_all([journal, monthly])
        await db.flush()
        db.add_all(
            [
                NotePageContentDO(
                    file_id=journal.id,
                    page_index=0,
                    page_id="p0",
                    text_content="Cats are great.",
                    embedding=json.dumps([1.0, 0.0, 0.0]),
                    embedding_model="fake-embedding-v1",
                ),
                NotePageContentDO(
                    file_id=monthly.id,
                    page_index=0,
                    page_id="p0",
                    text_content="Dogs are great.",
                    embedding=json.dumps([1.0, 0.0, 0.0]),
                    embedding_model="fake-embedding-v1",
                ),
            ]
        )
        await db.commit()

    by_name = await extended_client.search(query="anything", name_filter="Monthly")
    assert len(by_name.results) == 1
    assert by_name.results[0].file_name == "Monthly Plan.note"


async def test_search_route_with_inferred_date_filters(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify date_after and date_before filtering against inferred page_id dates."""
    async with session_manager.session() as db:
        journal = UserFileDO(
            user_id=test_user_id,
            file_name="Journal.note",
            directory_id=0,
            storage_key="journal_date_key",
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
                    embedding=json.dumps([1.0, 0.0, 0.0]),
                    embedding_model="fake-embedding-v1",
                ),
                NotePageContentDO(
                    file_id=journal.id,
                    page_index=1,
                    page_id="P20231028120000def",
                    text_content="Page 2 content.",
                    embedding=json.dumps([1.0, 0.0, 0.0]),
                    embedding_model="fake-embedding-v1",
                ),
            ]
        )
        await db.commit()

    oct27 = await extended_client.search(
        query="test", date_after="2023-10-27", date_before="2023-10-27"
    )
    assert len(oct27.results) == 1
    assert oct27.results[0].page_index == 0
    assert oct27.results[0].date == "2023-10-27"

    oct28 = await extended_client.search(query="test", date_after="2023-10-28")
    assert len(oct28.results) == 1
    assert oct28.results[0].page_index == 1

    date_range = await extended_client.search(
        query="test", date_after="2023-10-27", date_before="2023-10-29"
    )
    assert len(date_range.results) == 2


async def test_search_route_filters_by_embedding_model(
    extended_client: ExtendedClient,
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> None:
    """Verify search ignores pages embedded with a different model or None."""
    async with session_manager.session() as db:
        file_do = UserFileDO(
            user_id=test_user_id,
            file_name="Journal.note",
            directory_id=0,
            storage_key="model_filter_key",
        )
        db.add(file_do)
        await db.flush()
        db.add_all(
            [
                NotePageContentDO(
                    file_id=file_do.id,
                    page_index=0,
                    page_id="p0",
                    text_content="Matching model page.",
                    embedding=json.dumps([1.0, 0.0, 0.0]),
                    embedding_model="fake-embedding-v1",
                ),
                NotePageContentDO(
                    file_id=file_do.id,
                    page_index=1,
                    page_id="p1",
                    text_content="Other model page with different dimensions.",
                    embedding=json.dumps([1.0] * 768),
                    embedding_model="gemini-embedding-001",
                ),
                NotePageContentDO(
                    file_id=file_do.id,
                    page_index=2,
                    page_id="p2",
                    text_content="Unannotated model page.",
                    embedding=json.dumps([1.0, 0.0, 0.0]),
                    embedding_model=None,
                ),
            ]
        )
        await db.commit()

    response = await extended_client.search(query="test", top_n=5)
    assert len(response.results) == 1
    assert response.results[0].page_index == 0
    assert response.results[0].text_preview == "Matching model page."


async def test_search_route_invalid_dto_and_errors(
    client: TestClient,
    auth_headers: dict[str, str],
    extended_client: ExtendedClient,
    user_service: UserService,
) -> None:
    """Verify POST /api/extended/search handles 400, 404, and 500 error paths."""
    assert client.app is not None

    bad_resp = await client.post(
        "/api/extended/search",
        json={"invalid": "data"},
        headers=auth_headers,
    )
    assert bad_resp.status == 400

    with (
        patch.object(user_service, "get_user_id", return_value=None),
        pytest.raises(NotFoundException),
    ):
        await extended_client.search(query="test")

    with (
        patch.object(
            client.app[SEARCH_SERVICE_KEY],
            "search_chunks",
            side_effect=RuntimeError("Search crash"),
        ),
        pytest.raises(ApiException),
    ):
        await extended_client.search(query="test")
