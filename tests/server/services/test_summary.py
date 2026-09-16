import hashlib

from sqlalchemy import select

from supernote.models.summary import AddSummaryDTO, AddSummaryGroupDTO
from supernote.models.user import UserRegisterDTO
from supernote.server.db.models.summary import SummaryDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService


async def _register_user(user_service: UserService, email: str) -> None:
    pw_md5 = hashlib.md5(b"password").hexdigest()
    await user_service.register(
        UserRegisterDTO(email=email, password=pw_md5, user_name="Test User")
    )


async def test_upsert_group_creates_then_updates(
    user_service: UserService,
    session_manager: DatabaseSessionManager,
) -> None:
    """First upsert_group call creates a row; second updates it in place."""
    summary_service = SummaryService(user_service, session_manager)
    user_email = "upsert-group@example.com"
    await _register_user(user_service, user_email)

    unique_identifier = "notebook-key-group"

    await summary_service.upsert_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier=unique_identifier,
            name="First Name",
            md5_hash="hash1",
        ),
    )

    async with session_manager.session() as session:
        rows = (
            (
                await session.execute(
                    select(SummaryDO).where(
                        SummaryDO.unique_identifier == unique_identifier
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        first_id = rows[0].id
        assert rows[0].name == "First Name"

    # Second call with the same unique_identifier should update, not duplicate.
    await summary_service.upsert_group(
        user_email,
        AddSummaryGroupDTO(
            unique_identifier=unique_identifier,
            name="Second Name",
            md5_hash="hash2",
        ),
    )

    async with session_manager.session() as session:
        rows = (
            (
                await session.execute(
                    select(SummaryDO).where(
                        SummaryDO.unique_identifier == unique_identifier
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].id == first_id
        assert rows[0].name == "Second Name"
        assert rows[0].md5_hash == "hash2"


async def test_upsert_summary_creates_then_updates(
    user_service: UserService,
    session_manager: DatabaseSessionManager,
) -> None:
    """First upsert_summary call creates a row; second updates it in place."""
    summary_service = SummaryService(user_service, session_manager)
    user_email = "upsert-summary@example.com"
    await _register_user(user_service, user_email)

    unique_identifier = "notebook-key-summary"
    parent_unique_identifier = "notebook-key-group"

    await summary_service.upsert_summary(
        user_email,
        AddSummaryDTO(
            unique_identifier=unique_identifier,
            parent_unique_identifier=parent_unique_identifier,
            content="first content",
            data_source="OCR",
        ),
    )

    async with session_manager.session() as session:
        rows = (
            (
                await session.execute(
                    select(SummaryDO).where(
                        SummaryDO.unique_identifier == unique_identifier
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        first_id = rows[0].id
        assert rows[0].content == "first content"

    # Second call with the same unique_identifier should update, not duplicate.
    await summary_service.upsert_summary(
        user_email,
        AddSummaryDTO(
            unique_identifier=unique_identifier,
            parent_unique_identifier=parent_unique_identifier,
            content="second content",
            data_source="GEMINI",
        ),
    )

    async with session_manager.session() as session:
        rows = (
            (
                await session.execute(
                    select(SummaryDO).where(
                        SummaryDO.unique_identifier == unique_identifier
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].id == first_id
        assert rows[0].content == "second content"
        assert rows[0].data_source == "GEMINI"


async def test_upsert_summary_without_unique_identifier_is_noop(
    user_service: UserService,
    session_manager: DatabaseSessionManager,
) -> None:
    """An upsert with no unique_identifier does not create a row."""
    summary_service = SummaryService(user_service, session_manager)
    user_email = "upsert-noop@example.com"
    await _register_user(user_service, user_email)

    await summary_service.upsert_summary(
        user_email,
        AddSummaryDTO(unique_identifier=None, content="orphan content"),
    )

    async with session_manager.session() as session:
        rows = (await session.execute(select(SummaryDO))).scalars().all()
        assert rows == []
