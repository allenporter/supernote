import pytest
from sqlalchemy import select

from supernote.client.device import DeviceClient
from supernote.client.exceptions import ForbiddenException
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.user import UserService
from tests.server.conftest import TEST_USERNAME


async def test_device_capacity_query_returns_volume_backed_allocated_by_default(
    device_client: DeviceClient,
    blob_storage: BlobStorage,
) -> None:
    """Verify device capacity endpoint returns positive volume-backed capacity when uncapped."""
    capacity = await device_client.get_capacity()
    assert capacity.allocation_vo is not None
    assert capacity.used == 0
    assert capacity.allocation_vo.allocated > 0
    available = blob_storage.get_available_bytes()
    assert available is not None
    assert abs(capacity.allocation_vo.allocated - available) < 64 * 1024 * 1024


async def test_device_capacity_query_returns_custom_allocated_by_user(
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify device capacity endpoint returns customized user total_capacity."""
    custom_capacity = 20 * 1024 * 1024 * 1024  # 20GB
    async with session_manager.session() as session:
        stmt = select(UserDO).where(UserDO.email == TEST_USERNAME)
        user = (await session.execute(stmt)).scalar_one()
        user.total_capacity = str(custom_capacity)
        await session.commit()

    capacity = await device_client.get_capacity()
    assert capacity.allocation_vo is not None
    assert capacity.allocation_vo.allocated == custom_capacity


async def test_device_capacity_query_bound_equipment(
    device_client: DeviceClient,
    user_service: UserService,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify device capacity endpoint returns bound user's total_capacity when querying by equipmentNo."""
    eq_no = "SN_DEVICE_001"
    await user_service.bind_equipment(TEST_USERNAME, eq_no)

    custom_capacity = 30 * 1024 * 1024 * 1024  # 30GB
    async with session_manager.session() as session:
        stmt = select(UserDO).where(UserDO.email == TEST_USERNAME)
        user = (await session.execute(stmt)).scalar_one()
        user.total_capacity = str(custom_capacity)
        await session.commit()

    capacity = await device_client.get_capacity(equipment_no=eq_no)
    assert capacity.equipment_no == eq_no
    assert capacity.allocation_vo is not None
    assert capacity.allocation_vo.allocated == custom_capacity


async def test_device_upload_enforces_quota_via_api(
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
) -> None:
    """Verify device upload completion rejects uploads exceeding quota with 403."""
    # Set quota to 500 bytes
    async with session_manager.session() as session:
        stmt = select(UserDO).where(UserDO.email == TEST_USERNAME)
        user = (await session.execute(stmt)).scalar_one()
        user.total_capacity = "500"
        await session.commit()

    # Upload 300 bytes - fits within 500-byte quota
    res1 = await device_client.upload_content(
        path="quota_test.txt",
        content=b"x" * 300,
        equipment_no="SN_DEVICE_001",
    )
    assert res1.size == 300

    # Upload another 300 bytes for a second file - total 600 > 500 - should fail with 403
    with pytest.raises(ForbiddenException):
        await device_client.upload_content(
            path="quota_overflow.txt",
            content=b"y" * 300,
            equipment_no="SN_DEVICE_001",
        )

    # Overwrite first file with 400 bytes (net +100 bytes, total 400 <= 500) -> succeeds
    res_overwrite = await device_client.upload_content(
        path="quota_test.txt",
        content=b"z" * 400,
        equipment_no="SN_DEVICE_001",
    )
    assert res_overwrite.size == 400

    # Overwrite first file with 600 bytes (net +200 bytes, total 600 > 500) -> fails with 403
    with pytest.raises(ForbiddenException):
        await device_client.upload_content(
            path="quota_test.txt",
            content=b"w" * 600,
            equipment_no="SN_DEVICE_001",
        )
