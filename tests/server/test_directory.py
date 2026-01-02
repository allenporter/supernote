from supernote.client.file import FileClient


async def test_create_directory(file_client: FileClient) -> None:
    # Create folder
    await file_client.create_folder(path="/NewFolder", equipment_no="SN123456")

    # Verify folder exists
    data = await file_client.list_folder(path="/", equipment_no="SN123456")
    assert any(e.name == "NewFolder" for e in data.entries)


async def test_delete_folder(file_client: FileClient) -> None:
    # Create folder
    await file_client.create_folder(path="/DeleteMe", equipment_no="SN123456")

    # Get ID via list
    data = await file_client.list_folder(path="/", equipment_no="SN123456")
    entry = next(e for e in data.entries if e.name == "DeleteMe")
    folder_id = int(entry.id)

    # Delete
    await file_client.delete_folder(folder_id=folder_id, equipment_no="SN123456")

    # Verify gone
    data = await file_client.list_folder(path="/", equipment_no="SN123456")
    assert not any(e.name == "DeleteMe" for e in data.entries)


async def test_list_recursive(file_client: FileClient) -> None:
    # Create /Parent
    await file_client.create_folder(path="/Parent", equipment_no="SN123456")

    # Create /Parent/Child
    await file_client.create_folder(path="/Parent/Child", equipment_no="SN123456")

    # List non-recursive from root
    data = await file_client.list_folder(
        path="/", equipment_no="SN123456", recursive=False
    )

    results = sorted((e.name, e.path_display) for e in data.entries)
    assert results == [
        ("Document", "/Document"),
        ("EXPORT", "/EXPORT"),
        ("Note", "/Note"),
        ("Parent", "/Parent"),
    ]

    # List recursive from root
    data = await file_client.list_folder(
        path="/", equipment_no="SN123456", recursive=True
    )

    results = sorted((e.name, e.path_display) for e in data.entries)
    assert results == [
        ("Child", "/Parent/Child"),
        ("Document", "/Document"),
        ("EXPORT", "/EXPORT"),
        ("Note", "/Note"),
        ("Parent", "/Parent"),
    ]


async def test_list_subdirectory(file_client: FileClient) -> None:
    # Create /FolderA/FolderB
    await file_client.create_folder(path="/FolderA", equipment_no="SN123456")
    await file_client.create_folder(path="/FolderA/FolderB", equipment_no="SN123456")

    # Get ID of FolderA
    data = await file_client.list_folder(path="/", equipment_no="SN123456")
    entry = next(e for e in data.entries if e.name == "FolderA")
    folder_a_id = int(entry.id)

    # List recursive from FolderA
    data = await file_client.list_folder(
        folder_id=folder_a_id, equipment_no="SN123456", recursive=True
    )

    results = sorted((e.name, e.path_display, e.parent_path) for e in data.entries)

    # Expect FolderB. Path display should be full path /FolderA/FolderB
    assert results == [
        ("FolderB", "/FolderA/FolderB", "/FolderA"),
    ]

    # List flat from FolderA
    data = await file_client.list_folder(
        folder_id=folder_a_id, equipment_no="SN123456", recursive=False
    )

    results = sorted((e.name, e.path_display, e.parent_path) for e in data.entries)
    assert results == [
        ("FolderB", "/FolderA/FolderB", "/FolderA"),
    ]
