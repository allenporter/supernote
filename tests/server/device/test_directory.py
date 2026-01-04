from supernote.client.device import DeviceClient


async def test_create_directory(device_client: DeviceClient) -> None:
    # Create folder
    await device_client.create_folder(path="/NewFolder", equipment_no="SN123456")

    # Verify folder exists
    data = await device_client.list_folder(path="/", equipment_no="SN123456")
    assert any(e.name == "NewFolder" for e in data.entries)


async def test_delete_folder(device_client: DeviceClient) -> None:
    # Create folder
    await device_client.create_folder(path="/DeleteMe", equipment_no="SN123456")

    # Get ID via list
    data = await device_client.list_folder(path="/", equipment_no="SN123456")
    entry = next(e for e in data.entries if e.name == "DeleteMe")
    folder_id = int(entry.id)

    # Delete
    await device_client.delete(id=folder_id, equipment_no="SN123456")

    # Verify gone
    data = await device_client.list_folder(path="/", equipment_no="SN123456")
    assert not any(e.name == "DeleteMe" for e in data.entries)


async def test_list_recursive(device_client: DeviceClient) -> None:
    # Create /Parent
    await device_client.create_folder(path="/Parent", equipment_no="SN123456")

    # Create /Parent/Child
    await device_client.create_folder(path="/Parent/Child", equipment_no="SN123456")

    # List non-recursive from root
    data = await device_client.list_folder(
        path="/", equipment_no="SN123456", recursive=False
    )

    results = sorted((e.name, e.path_display) for e in data.entries)
    assert results == [
        ("DOCUMENT", "/DOCUMENT"),
        ("Export", "/Export"),
        ("Inbox", "/Inbox"),
        ("NOTE", "/NOTE"),
        ("Parent", "/Parent"),
        ("Screenshot", "/Screenshot"),
    ]

    # List recursive from root
    data = await device_client.list_folder(
        path="/", equipment_no="SN123456", recursive=True
    )

    results = sorted((e.name, e.path_display) for e in data.entries)
    assert results == [
        ("Child", "/Parent/Child"),
        ("DOCUMENT", "/DOCUMENT"),
        ("Document", "/DOCUMENT/Document"),
        ("Export", "/Export"),
        ("Inbox", "/Inbox"),
        ("MyStyle", "/NOTE/MyStyle"),
        ("NOTE", "/NOTE"),
        ("Note", "/NOTE/Note"),
        ("Parent", "/Parent"),
        ("Screenshot", "/Screenshot"),
    ]


async def test_list_subdirectory(device_client: DeviceClient) -> None:
    # Create /FolderA/FolderB
    await device_client.create_folder(path="/FolderA", equipment_no="SN123456")
    await device_client.create_folder(path="/FolderA/FolderB", equipment_no="SN123456")

    # Get ID of FolderA
    data = await device_client.list_folder(path="/", equipment_no="SN123456")
    entry = next(e for e in data.entries if e.name == "FolderA")
    folder_a_id = int(entry.id)

    # List recursive from FolderA
    data = await device_client.list_folder(
        folder_id=folder_a_id, equipment_no="SN123456", recursive=True
    )

    results = sorted((e.name, e.path_display, e.parent_path) for e in data.entries)

    # Expect FolderB. Path display should be full path /FolderA/FolderB
    assert results == [
        ("FolderB", "/FolderA/FolderB", "/FolderA"),
    ]

    # List flat from FolderA
    data = await device_client.list_folder(
        folder_id=folder_a_id, equipment_no="SN123456", recursive=False
    )

    results = sorted((e.name, e.path_display, e.parent_path) for e in data.entries)
    assert results == [
        ("FolderB", "/FolderA/FolderB", "/FolderA"),
    ]
