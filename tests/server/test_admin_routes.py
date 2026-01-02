import pytest

from supernote.client.admin import AdminClient
from supernote.client.client import Client


@pytest.fixture
def admin_client(authenticated_client: Client) -> AdminClient:
    return AdminClient(authenticated_client)


@pytest.mark.asyncio
async def test_admin_update_password(admin_client: AdminClient) -> None:
    # This just ensures the client makes the call without error.
    # The server logic is verified in server tests.
    await admin_client.update_password("newpass123")


@pytest.mark.asyncio
async def test_admin_unregister(admin_client: AdminClient) -> None:
    await admin_client.unregister()
