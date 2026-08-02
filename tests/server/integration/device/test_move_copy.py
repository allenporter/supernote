from supernote.client.device import DeviceClient


async def test_move_folder(device_client: DeviceClient) -> None:
    # Create folders for source and dest
    await device_client.create_folder(path="/SourceFolder", equipment_no="SN123456")
    await device_client.create_folder(path="/DestFolder", equipment_no="SN123456")

    # Create subfolder to move
    await device_client.create_folder(
        path="/SourceFolder/ToMove", equipment_no="SN123456"
    )

    # Get ID of /SourceFolder/ToMove
    data = await device_client.list_folder(
        path="/SourceFolder", equipment_no="SN123456"
    )
    entry = next(e for e in data.entries if e.name == "ToMove")
    item_id = int(entry.id)

    # Move /SourceFolder/ToMove -> /DestFolder/ToMove
    move_result = await device_client.move(
        id=item_id,
        to_path="/DestFolder/ToMove",
        equipment_no="SN123456",
        autorename=False,
    )
    assert move_result.equipment_no == "SN123456"
    assert move_result.entries_vo
    assert move_result.entries_vo.id
    assert move_result.entries_vo.name == "ToMove"
    assert move_result.entries_vo.path_display == "DestFolder/ToMove"
    assert move_result.entries_vo.parent_path == "DestFolder"
    assert move_result.entries_vo.tag == "folder"

    # Verify in DestFolder
    data = await device_client.list_folder(path="/DestFolder", equipment_no="SN123456")
    assert [e.name for e in data.entries] == ["ToMove"]

    # Verify SourceFolder is now empty
    data = await device_client.list_folder(
        path="/SourceFolder", equipment_no="SN123456"
    )
    assert [e.name for e in data.entries] == []


async def test_move_file(device_client: DeviceClient) -> None:
    # Create folders for source and dest
    await device_client.create_folder(path="/SourceFolder", equipment_no="SN123456")
    await device_client.create_folder(path="/DestFolder", equipment_no="SN123456")

    upload_result = await device_client.upload_content(
        "/SourceFolder/My.note", b"contents", equipment_no="SN123456"
    )
    assert upload_result.success
    assert upload_result.id
    assert upload_result.name == "My.note"
    assert upload_result.path_display == "SourceFolder/My.note"
    item_id = int(upload_result.id)

    # Move /SourceFolder/My.note -> /DestFolder/My-New.note
    move_result = await device_client.move(
        id=item_id,
        to_path="/DestFolder/My-New.note",
        equipment_no="SN123456",
        autorename=False,
    )
    assert move_result.equipment_no == "SN123456"
    assert move_result.entries_vo
    assert move_result.entries_vo.id
    assert move_result.entries_vo.name == "My-New.note"
    assert move_result.entries_vo.path_display == "DestFolder/My-New.note"
    assert move_result.entries_vo.parent_path == "DestFolder"
    assert move_result.entries_vo.tag == "file"

    # Verify in DestFolder
    data = await device_client.list_folder(path="/DestFolder", equipment_no="SN123456")
    assert data.entries
    assert len(data.entries) == 1
    assert data.entries[0].name == "My-New.note"
    assert data.entries[0].path_display == "DestFolder/My-New.note"
    assert data.entries[0].parent_path == "DestFolder"
    assert data.entries[0].tag == "file"

    # Verify Source Folder is now empty
    data = await device_client.list_folder(
        path="/SourceFolder", equipment_no="SN123456"
    )
    assert [e.name for e in data.entries] == []


async def test_copy_file_autorename(device_client: DeviceClient) -> None:
    # Create Folder
    await device_client.create_folder(path="/CopySource", equipment_no="SN123456")

    # Create Item
    await device_client.create_folder(path="/CopySource/Item", equipment_no="SN123456")

    # Get ID
    data = await device_client.list_folder(path="/CopySource", equipment_no="SN123456")
    assert data.entries
    assert len(data.entries) == 1
    assert data.entries[0].name == "Item"
    item_id = int(data.entries[0].id)

    # Copy to same folder (requires autorename)
    copy_result = await device_client.copy(
        id=item_id, to_path="/CopySource", equipment_no="SN123456", autorename=True
    )
    assert copy_result.equipment_no == "SN123456"
    assert copy_result.entries_vo is not None
    assert copy_result.entries_vo.id
    assert copy_result.entries_vo.name == "Item(1)"
    assert copy_result.entries_vo.path_display == "CopySource/Item(1)"
    assert copy_result.entries_vo.parent_path == "CopySource"
    assert copy_result.entries_vo.tag == "folder"

    # Verify both exist
    data = await device_client.list_folder(path="/CopySource", equipment_no="SN123456")
    names = [e.name for e in data.entries]
    assert names == ["Item", "Item(1)"]


async def test_copy_folder(device_client: DeviceClient) -> None:
    # Create folders for source and dest
    await device_client.create_folder(path="/SourceFolder", equipment_no="SN123456")
    await device_client.create_folder(path="/DestFolder", equipment_no="SN123456")

    # Create subfolder to copy
    create_result = await device_client.create_folder(
        path="/SourceFolder/ToMove", equipment_no="SN123456"
    )
    assert create_result.success
    assert create_result.metadata
    assert create_result.metadata.id
    assert create_result.metadata.name == "ToMove"
    assert create_result.metadata.path_display == "SourceFolder/ToMove"
    assert create_result.metadata.tag == "folder"
    item_id = int(create_result.metadata.id)

    # Copy /SourceFolder/ToMove -> /DestFolder/ToMove
    copy_result = await device_client.copy(
        id=item_id,
        to_path="/DestFolder/ToMove",
        equipment_no="SN123456",
        autorename=False,
    )
    assert copy_result.equipment_no == "SN123456"
    assert copy_result.entries_vo
    assert copy_result.entries_vo.id
    assert copy_result.entries_vo.name == "ToMove"
    assert copy_result.entries_vo.path_display == "DestFolder/ToMove"
    assert copy_result.entries_vo.parent_path == "DestFolder"
    assert copy_result.entries_vo.tag == "folder"

    # Verify in DestFolder
    data = await device_client.list_folder(path="/DestFolder", equipment_no="SN123456")
    assert len(data.entries) == 1
    assert data.entries[0].id != str(item_id)  # New id assigned
    assert data.entries[0].name == "ToMove"
    assert data.entries[0].path_display == "DestFolder/ToMove"
    assert data.entries[0].parent_path == "DestFolder"
    assert data.entries[0].tag == "folder"

    # List contents of new folder
    data = await device_client.list_folder(
        path="/DestFolder/ToMove", equipment_no="SN123456"
    )
    assert data.entries is not None
    assert len(data.entries) == 0

    # TODO Exercise doing a recursive copy of a folder
