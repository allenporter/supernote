from supernote.client.device import DeviceClient


async def test_move_file(device_client: DeviceClient) -> None:
    # 1. Create file via upload (mocked flow or just assume pre-existence logic via helper)
    # Actually, let's create a folder first to move things into
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
        id=item_id, to_path="/DestFolder", equipment_no="SN123456", autorename=False
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
    assert any(e.name == "ToMove" for e in data.entries)

    # Verify NOT in SourceFolder
    data = await device_client.list_folder(
        path="/SourceFolder", equipment_no="SN123456"
    )
    assert not any(e.name == "ToMove" for e in data.entries)


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
