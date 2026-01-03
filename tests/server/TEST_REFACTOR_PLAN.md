# Test Restructuring Plan

## Goals
1.  Separate tests into `tests/server/device` and `tests/server/web` to mirror the API and Model separation.
2.  Stop using the aggregate `FileClient` in tests. Instead, use specific `DeviceClient` and `WebClient` to ensure we aren't accidentally relying on the wrong API.

## 1. Directory Structure Changes
Create two new directories:
- `tests/server/device`: For V2/V3 Device API tests (Sync, Upload, Device Listing).
- `tests/server/web`: For Web API tests (Search, Recycle Bin, Web Listing).

## 2. Fixture Updates (`tests/server/conftest.py`)
Add specific fixtures and deprecate `file_client`.

```python
# conftest.py updates

from supernote.client.web import WebClient
from supernote.client.device import DeviceClient


@pytest.fixture
def device_client(authenticated_client: Client) -> Generator[DeviceClient, None, None]:
    """Create a DeviceClient."""
    yield DeviceClient(authenticated_client)

@pytest.fixture
def web_client(authenticated_client: Client) -> Generator[WebClient, None, None]:
    """Create a WebClient."""
    yield WebClient(authenticated_client)

# Eventually remove this
@pytest.fixture
def file_client(...)
```

## 3. Migration Tasks

| Original Test File | Action | Destination | Client Usage |
| :--- | :--- | :--- | :--- |
| `test_recycle.py` | **Move** | `tests/server/web/test_recycle.py` | `WebClient` |
| `test_search.py` | **Move** | `tests/server/web/test_search.py` | `WebClient` |
| `test_connectivity.py` | **Move** | `tests/server/device/test_sync.py` | `DeviceClient` |
| `test_upload.py` | **Move** | `tests/server/device/test_upload.py` | `DeviceClient` |
| `test_download.py` | **Move** | `tests/server/device/test_download.py` | `DeviceClient` |
| `test_move_copy.py` | **Move** | `tests/server/device/test_move_copy.py` | `DeviceClient` |
| `test_query_v3.py` | **Move** | `tests/server/device/test_query.py` | `DeviceClient` |
| `test_device_binding.py`| **Move** | `tests/server/device/test_binding.py`| `DeviceClient` |
| `test_file_list.py` | **Split** | `tests/server/web/test_listing.py`<br>`tests/server/device/test_listing.py` | `WebClient`<br>`DeviceClient` |
| `test_capacity.py` | **Split** | `tests/server/web/test_capacity.py`<br>`tests/server/device/test_capacity.py` | `WebClient`<br>`DeviceClient` |

## 4. Execution Order
1.  **Setup**: Create directories and update `conftest.py`.
2.  **Easy Moves**: Move `recycle`, `search`, `connectivity` (they are clean one-sided tests).
3.  **Device Core**: Move `upload`, `download`, `move_copy`.
4.  **Splitting**: Handle `file_list` and `capacity` which mix both APIs.
5.  **Cleanup**: Remove `file_client` fixture and audit any leftovers.
