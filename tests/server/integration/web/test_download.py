from urllib.parse import urlparse

import pytest

from supernote.client import Client
from supernote.client.exceptions import ApiException
from supernote.client.web import WebClient


async def test_web_download_returns_the_stored_bytes(
    authenticated_client: Client,
    web_client: WebClient,
) -> None:
    """The whole point: a file put in from the device comes back out again."""
    res = await web_client.list_query(directory_id=0)
    note_folder = next(f for f in res.user_file_vo_list if f.file_name == "Note")

    content = b"a stored notebook"
    await web_client.upload_file(
        parent_id=int(note_folder.id), name="MyNote.note", content=content
    )

    listed = await web_client.list_query(directory_id=int(note_folder.id))
    uploaded = next(f for f in listed.user_file_vo_list if f.file_name == "MyNote.note")

    res_url = await web_client.download_url(id=int(uploaded.id))
    assert res_url.url

    resp = await authenticated_client.get(_path_of(res_url.url))
    assert resp.status == 200
    assert await resp.read() == content


async def test_web_download_names_the_file_for_the_browser(
    authenticated_client: Client,
    web_client: WebClient,
) -> None:
    """Without this the browser saves every notebook as `download`."""
    res = await web_client.list_query(directory_id=0)
    note_folder = next(f for f in res.user_file_vo_list if f.file_name == "Note")

    await web_client.upload_file(
        parent_id=int(note_folder.id), name="MyNote.note", content=b"x"
    )
    listed = await web_client.list_query(directory_id=int(note_folder.id))
    uploaded = next(f for f in listed.user_file_vo_list if f.file_name == "MyNote.note")

    res_url = await web_client.download_url(id=int(uploaded.id))
    resp = await authenticated_client.get(_path_of(res_url.url))
    assert 'filename="MyNote.note"' in resp.headers["Content-Disposition"]


async def test_web_download_refuses_a_folder(web_client: WebClient) -> None:
    """A folder has no bytes; say so rather than signing a URL that 404s."""
    res = await web_client.list_query(directory_id=0)
    note_folder = next(f for f in res.user_file_vo_list if f.file_name == "Note")

    with pytest.raises(ApiException, match="Not a file"):
        await web_client.download_url(id=int(note_folder.id))


async def test_web_download_refuses_an_unknown_id(web_client: WebClient) -> None:
    with pytest.raises(ApiException, match="File not found"):
        await web_client.download_url(id=999999999)


def _path_of(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path + "?" + parsed.query
