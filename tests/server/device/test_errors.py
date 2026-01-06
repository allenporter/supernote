from unittest.mock import patch

import pytest

from supernote.client.device import DeviceClient
from supernote.client.exceptions import (
    ApiException,
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)


async def test_error_list_folder_not_found(device_client: DeviceClient) -> None:
    # list_folder should now return 404
    with pytest.raises(NotFoundException, match="Path not found"):
        await device_client.list_folder(path="/NonExistent", equipment_no="test")


async def test_error_delete_system_directory(device_client: DeviceClient) -> None:
    # Create a system directory (identified by name in constants.py)
    await device_client.create_folder(path="/MyStyle", equipment_no="test")

    # Get ID of MyStyle
    res = await device_client.query_by_path(path="/MyStyle", equipment_no="test")
    assert res.entries_vo
    mystyle_id = int(res.entries_vo.id)

    with pytest.raises(ForbiddenException, match="Cannot delete system directory"):
        await device_client.delete(id=mystyle_id, equipment_no="test")


async def test_error_move_into_self(device_client: DeviceClient) -> None:
    # Trigger cyclic move: move FolderA into itself
    await device_client.create_folder(path="/FolderA", equipment_no="test")
    res = await device_client.query_by_path(path="/FolderA", equipment_no="test")
    assert res.entries_vo
    folder_id = int(res.entries_vo.id)

    with pytest.raises(BadRequestException, match="Cyclic move"):
        await device_client.move(
            id=folder_id, to_path="/FolderA/Sub", equipment_no="test"
        )


async def test_error_list_file_as_folder(device_client: DeviceClient) -> None:
    # Create a file
    await device_client.upload_content("/file.txt", b"hello", equipment_no="test")

    # Try to list it as a folder
    with pytest.raises(BadRequestException, match="Not a folder"):
        await device_client.list_folder(path="/file.txt", equipment_no="test")


async def test_error_hash_mismatch_missing_blob(device_client: DeviceClient) -> None:
    # 1. Apply
    await device_client.upload_apply(
        file_name="bad.txt", path="/", size=5, equipment_no="test"
    )
    # 2. Finish with wrong hash -> Blob not found (404)
    with pytest.raises(NotFoundException, match="Blob wronghash not found"):
        await device_client.upload_finish(
            file_name="bad.txt", path="/", content_hash="wronghash", equipment_no="test"
        )


async def test_error_uncaught_exception(device_client: DeviceClient) -> None:
    # Trigger 500 by mocking an internal service to raise Exception
    with patch(
        "supernote.server.services.file.FileService.list_folder",
        side_effect=Exception("BOOM"),
    ):
        with pytest.raises(ApiException, match="500"):
            await device_client.list_folder(path="/", equipment_no="test")
        # Check that BOOM is in the message (via inner attribute or re-raising)
        # The current Client implementation puts error_detail in the message.
