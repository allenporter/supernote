"""HTTP route tests for `supernote.server.components.integrity.http`."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient
from sqlalchemy import update

from supernote.client.admin import AdminClient
from supernote.client.client import Client
from supernote.client.exceptions import (
    ApiException,
    ForbiddenException,
    NotFoundException,
)
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from tests.fixtures.server import TEST_USERNAME


@pytest.fixture
async def admin_user_id(
    session_manager: DatabaseSessionManager,
    test_user_id: int,
) -> int:
    """Promote the default test user to admin."""
    async with session_manager.session() as session:
        await session.execute(
            update(UserDO).where(UserDO.id == test_user_id).values(is_admin=True)
        )
        await session.commit()
    return test_user_id


@pytest.fixture
def admin_client(authenticated_client: Client, admin_user_id: int) -> AdminClient:
    """AdminClient authenticated as an admin user."""
    _ = admin_user_id
    return AdminClient(authenticated_client)


async def test_verify_integrity_requires_admin(
    authenticated_client: Client,
    test_user_id: int,
) -> None:
    """Verify GET /api/admin/integrity rejects non-admin users with 403."""
    _ = test_user_id
    with pytest.raises(ForbiddenException):
        await AdminClient(authenticated_client).verify_integrity(email=TEST_USERNAME)


async def test_verify_integrity_for_user(
    admin_client: AdminClient,
) -> None:
    """Verify GET /api/admin/integrity returns a report for an existing user."""
    report = await admin_client.verify_integrity(email=TEST_USERNAME)
    assert report.issues == []


async def test_verify_integrity_full_disk(
    admin_client: AdminClient,
) -> None:
    """Verify GET /api/admin/integrity?full_disk=true audits all users and buckets."""
    report = await admin_client.verify_integrity(full_disk=True)
    assert report.issues == []


async def test_verify_integrity_unknown_user_returns_404(
    admin_client: AdminClient,
) -> None:
    """Verify GET /api/admin/integrity returns 404 for an unknown email."""
    with pytest.raises(NotFoundException):
        await admin_client.verify_integrity(email="missing@example.com")


async def test_verify_integrity_rejects_missing_email(
    admin_client: AdminClient,
) -> None:
    """Verify GET /api/admin/integrity returns 400 when neither email nor full_disk is set."""
    with pytest.raises(ApiException):
        await admin_client.verify_integrity()


async def test_verify_integrity_rejects_full_disk_combined_with_email(
    admin_client: AdminClient,
) -> None:
    """Verify GET /api/admin/integrity rejects combining full_disk=true with email."""
    with pytest.raises(ApiException):
        await admin_client.verify_integrity(email=TEST_USERNAME, full_disk=True)


@pytest.mark.parametrize(
    "query",
    [
        "full_disk=invalid",
        f"email={TEST_USERNAME}&file_id=notanint",
    ],
)
async def test_verify_integrity_rejects_invalid_query_params(
    client: TestClient,
    auth_headers: dict[str, str],
    admin_user_id: int,
    query: str,
) -> None:
    """Verify GET /api/admin/integrity returns 400 on malformed full_disk or file_id."""
    _ = admin_user_id
    resp = await client.get(f"/api/admin/integrity?{query}", headers=auth_headers)
    assert resp.status == 400
