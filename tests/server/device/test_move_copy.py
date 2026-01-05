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
    assert any(e.name == "ToMove" for e in data.entries)

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


"""
Corner Case Scenarios for Move and Copy (Black Box)
-----------------------------------------------

1. Move/Copy to same parent, same name (Identity)
   - [ ] Move `/A/file.txt` -> `/A/file.txt` (autorename=False)
   - [ ] Move `/A/file.txt` -> `/A/file.txt` (autorename=True)
   - [ ] Move `/A/folder` -> `/A/folder`
   - Expected: Should be a no-op or success. Verify if the system handles this as a rename or rejects it.

2. Basic Rename (Same parent, different name)
   - [ ] Move `/A/file.txt` -> `/A/new_file.txt`
   - [ ] Move `/A/folder` -> `/A/new_folder`
   - Expected: Success, original name gone, new name exists.

3. Name Collisions (autorename=False)
   - [ ] Move `/A/file.txt` -> `/B/file.txt` (where `/B/file.txt` exists)
   - [ ] Move `/A/folder` -> `/B/folder` (where `/B/folder` exists)
   - [ ] Move `/A/file.txt` -> `/B/folder` (where `/B/folder` exists with SAME NAME)
   - Expected: Should fail with a Conflict (409) or similar error.

4. Name Collisions (autorename=True)
   - [ ] Move `/A/file.txt` -> `/B/file.txt` (where `/B/file.txt` exists)
   - Expected: Success, destination becomes `/B/file(1).txt`.
   - [ ] Copy `/A/file.txt` -> `/A/file.txt`
   - Expected: Success, destination becomes `/A/file(1).txt`.

5. Cyclic Moves (The "black hole" problem)
   - [ ] Move `/A` -> `/A/B`
   - [ ] Move `/A` -> `/A/B/C`
   - Expected: Should fail. A folder cannot be moved into itself or its descendants.

6. Invalid Destinations
   - [ ] Move `/A/file.txt` -> `/B/non_existent_folder/file.txt`
   - [ ] Move `/A/file.txt` -> `/B/existing_file.txt/file.txt`
   - Expected: Failure. Target parent must exist and be a directory.

7. System/Protected Files
   - [ ] Move `/MyStyle` -> `/Documents/MyStyle`
   - [ ] Rename `/MyStyle` -> `/MyCustomStyle`
   - Expected: Failure. System folders should be immutable/immovable via standard API.

8. Root Operations
   - [ ] Move `/` -> `/SomeFolder`
   - [ ] Copy `/` -> `/Backup`
   - Expected: Failure. Root cannot be moved or copied.

9. Recursive Operations
   - [ ] Copy `/SourceFolder` (with deep hierarchy) -> `/DestFolder`
   - Expected: Entire structure duplicated with new IDs but same names/relative paths.

10. Rapid Operations (Concurrency/Race conditions) - Optional
    - [ ] Move `/A` -> `/B` and immediately Move `/A/sub` -> `/C`
    - [ ] Move `/A` -> `/B` and immediately Delete `/A`
"""
