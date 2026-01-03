from . import Client
from .device import DeviceClient
from .web import WebClient

DEFAULT_PAGE_SIZE = 50


class FileClient(DeviceClient, WebClient):
    """Client for File APIs (Device/Sync) using standard DTOs.

    This class aggregates access to both Device and Web APIs for backward compatibility.
    """

    def __init__(self, client: Client) -> None:
        """Initialize the FileClient."""
        self._client = client
        # Manually initialize parents because they just store the client
        DeviceClient.__init__(self, client)
        WebClient.__init__(self, client)
