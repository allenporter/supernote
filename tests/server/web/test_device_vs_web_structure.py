import pytest

from supernote.client.device import DeviceClient
from supernote.client.web import WebClient


@pytest.mark.asyncio
async def test_device_vs_web_structure(
    web_client: WebClient, device_client: DeviceClient
) -> None:
    """Verify that Web sees a flattened root while Device sees the real structure."""

    # 1. Web Listing (Root)
    web_res = await web_client.list_query(directory_id=0)
    web_folders = {f.file_name for f in web_res.user_file_vo_list}

    # Web should see: Note, Document, MyStyle, Export, Inbox, Screenshot
    # But NOT NOTE or DOCUMENT
    expected_web = {"Note", "Document", "MyStyle", "Export", "Inbox", "Screenshot"}
    assert expected_web.issubset(web_folders)
    assert "NOTE" not in web_folders
    assert "DOCUMENT" not in web_folders

    # 2. Device Listing (Root)
    device_res = await device_client.list_folder("/", recursive=False)
    device_folders = {e.name for e in device_res.entries}

    # Device should see: Export, Inbox, Screenshot, NOTE, DOCUMENT
    # But NOT Note, Document, MyStyle at root
    expected_device = {"Export", "Inbox", "Screenshot", "NOTE", "DOCUMENT"}
    assert expected_device.issubset(device_folders)
    assert "Note" not in device_folders
    assert "Document" not in device_folders
    assert "MyStyle" not in device_folders

    # 3. Verify IDs match for flattened folders
    # Note in Web should have same ID as Note in Device (under NOTE)
    web_note = next(f for f in web_res.user_file_vo_list if f.file_name == "Note")

    # Find Note in Device
    note_container = next(e for e in device_res.entries if e.name == "NOTE")
    note_container_id = int(note_container.id)
    device_children = await device_client.list_folder(folder_id=note_container_id)
    device_note = next(e for e in device_children.entries if e.name == "Note")

    assert web_note.id == str(device_note.id)
    assert web_note.directory_id == "0"
    assert device_note.parent_path == "/NOTE"
