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
    data = await device_client.list_folder(path="/SourceFolder", equipment_no="SN123456")
    entry = next(e for e in data.entries if e.name == "ToMove")
    item_id = int(entry.id)

    # Move /SourceFolder/ToMove -> /DestFolder/ToMove
    await device_client.move(
        id=item_id, to_path="/DestFolder", equipment_no="SN123456", autorename=False
    )

    # Verify in DestFolder
    data = await device_client.list_folder(path="/DestFolder", equipment_no="SN123456")
    assert any(e.name == "ToMove" for e in data.entries)

    # Verify NOT in SourceFolder
    data = await device_client.list_folder(path="/SourceFolder", equipment_no="SN123456")
    assert not any(e.name == "ToMove" for e in data.entries)


async def test_copy_file_autorename(device_client: DeviceClient) -> None:
    # Create Folder
    await device_client.create_folder(path="/CopySource", equipment_no="SN123456")

    # Create Item
    await device_client.create_folder(path="/CopySource/Item", equipment_no="SN123456")

    # Get ID
    data = await device_client.list_folder(path="/CopySource", equipment_no="SN123456")
    entry = next(e for e in data.entries if e.name == "Item")
    item_id = int(entry.id)

    # Copy to same folder (requires autorename)
    await device_client.copy(
        id=item_id, to_path="/CopySource", equipment_no="SN123456", autorename=True
    )

    # Verify both exist
    data = await device_client.list_folder(path="/CopySource", equipment_no="SN123456")
    names = [e.name for e in data.entries]
    assert "Item" in names
    # Should find Item(1) or similar. Since "Item" has no extension, it's just Item(1)
    assert any(n.startswith("Item(1)") for n in names)
