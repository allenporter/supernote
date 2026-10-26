"""Async Python SDK for Supernote Cloud and self-hosted Supernote Private Cloud servers.

Install the client extra to use this package:

```bash
pip install "supernote[client]"
```

---

## Architecture Overview

The `supernote.client.Supernote` session facade manages an underlying `aiohttp.ClientSession` and authenticated `supernote.client.Client` transport, providing direct properties for core APIs and access to specialized domain clients:

```mermaid
flowchart TD
    SN["Supernote\n(supernote.client.Supernote)"] --> BASE["sn.client : Client\n(CSRF + x-access-token + OSS upload)"]
    SN --> DEV["sn.device : DeviceClient\n(V2/V3 path & ID sync, upload/download, PNG/PDF)"]
    SN --> WEB["sn.web : WebClient\n(Directory tree, recycle bin, keyword search)"]
    SN --> LOGIN["sn.login_client : LoginClient\n(Challenge-response SHA256/MD5 & SMS auth)"]
    BASE --> SCHED["ScheduleClient(sn.client)\n(Task groups, tasks, batch updates, iCal feed)"]
    BASE --> SUM["SummaryClient(sn.client)\n(Summaries, summary groups, tags)"]
    BASE --> EXT["ExtendedClient(sn.client)\n(Semantic search, transcripts, AI insights)"]
    BASE --> ADM["AdminClient(sn.client)\n(Users, queue control, reprocess, integrity)"]
    SOCK["SupernoteSocketClient(host)\n(Real-time Socket.IO push & heartbeats)"]
```

| Client Class | Access / Construction | Responsibility |
| :--- | :--- | :--- |
| `supernote.client.Supernote` | `await Supernote.login(...)`, `Supernote.from_token(...)`, `Supernote.from_auth(...)` | Top-level async context manager and session entry point. |
| `supernote.client.client.Client` | `sn.client` | Low-level HTTP/JSON transport (`X-XSRF-TOKEN`, `x-access-token`, single & multipart OSS uploads). |
| `supernote.client.device.DeviceClient` | `sn.device` | Hardware V2/V3 file APIs: path-based listing, `upload_content`, `download_content`, sync locks, and server-side PNG/PDF conversion. |
| `supernote.client.web.WebClient` | `sn.web` | Web UI APIs: paginated directory queries, recycle bin management, rename/move/copy, and user profile queries. |
| `supernote.client.schedule.ScheduleClient` | `ScheduleClient(sn.client)` | Task lists (`create_group`, `list_groups`), tasks (`create_task`, `list_tasks`, `update_task`, `batch_update_tasks`), and RFC 5545 `.ics` feeds. |
| `supernote.client.summary.SummaryClient` | `SummaryClient(sn.client)` | Device-synced summaries, summary groups, and summary tags. |
| `supernote.client.extended.ExtendedClient` | `ExtendedClient(sn.client)` | Self-hosted server intelligence extensions: semantic chunk search, page transcripts, AI summaries, and task status. |
| `supernote.client.admin.AdminClient` | `AdminClient(sn.client)` | Account administration, processor queue pause/resume, task inspection, note reprocessing, and storage integrity verification. |
| `supernote.client.socket.SupernoteSocketClient` | `SupernoteSocketClient(host)` | Real-time Socket.IO listener for `FILE-SYN`, `TASK-SYN`, and `DIGEST-SYN` push notifications. |

---

## Authentication

`supernote.client.Supernote` supports three authentication patterns:

### 1. Interactive Challenge-Response Login (`Supernote.login`)

Performs the two-step random challenge + salted `SHA256(MD5(password) + randomCode)` handshake and returns an authenticated `Supernote` session:

```python
import asyncio
from supernote.client import Supernote


async def main() -> None:
    async with await Supernote.login(
        "alice@example.com",
        "password",
        host="http://127.0.0.1:8080",
    ) as sn:
        user = await sn.web.query_user()
        print(f"Authenticated as {user.user_name} ({user.email})")
        print(f"Access token: {sn.token}")


asyncio.run(main())
```

### 2. Existing JWT Access Token (`Supernote.from_token`)

Wrap a known `x-access-token` using `supernote.client.auth.ConstantAuth`:

```python
from supernote.client import Supernote

async with Supernote.from_token(
    "eyJhbGciOiJIUzI1NiIs...",
    host="http://127.0.0.1:8080",
) as sn:
    capacity = await sn.device.get_capacity()
    print(f"Used: {capacity.used_capacity} / {capacity.total_capacity} bytes")
```

### 3. Persistent File Cache (`Supernote.from_auth` + `FileCacheAuth`)

Share credentials with the `supernote cloud` CLI (`~/.cache/supernote.pkl`) or manage custom token storage by subclassing `supernote.client.auth.AbstractAuth`:

```python
import os
from supernote.client import Supernote
from supernote.client.auth import FileCacheAuth

cache_path = os.path.expanduser("~/.cache/supernote.pkl")
auth = FileCacheAuth(cache_path)

async with Supernote.from_auth(auth, host=auth.get_host()) as sn:
    folder = await sn.device.list_folder("/")
    for entry in folder.entries:
        print(entry.name, entry.id)
```

---

## Practical Examples

### Listing, Uploading, and Downloading `.note` Files (`DeviceClient`)

`supernote.client.device.DeviceClient` provides high-level path-based methods (`list_folder`, `upload_content`, `download_content`, `create_folder`, `delete_by_path`) that handle the 3-step `upload_apply -> OSS transfer -> upload_finish` flow and signed download URLs automatically:

```python
from pathlib import Path
from supernote.client import Supernote


async def sync_notes(sn: Supernote) -> None:
    # Ensure target folder exists
    await sn.device.create_folder("/NOTE/Projects", equipment_no="WEB")

    # Upload a local .note file (automatically chunks files >= 5 MiB)
    note_bytes = Path("local_meeting.note").read_bytes()
    finish_vo = await sn.device.upload_content(
        "/NOTE/Projects/Architecture_Review.note",
        note_bytes,
    )
    print(f"Uploaded with MD5: {finish_vo.content_hash}")

    # List folder contents (set recursive=True for full subtree)
    listing = await sn.device.list_folder("/NOTE/Projects", recursive=False)
    for item in listing.entries:
        print(f"[{item.tag}] {item.name} (id={item.id}, size={item.size})")

    # Download file content by path (or pass file_id=int(item.id))
    downloaded = await sn.device.download_content(
        path="/NOTE/Projects/Architecture_Review.note"
    )
    Path("downloaded_copy.note").write_bytes(downloaded)

    # Convert a remote .note file to PDF or per-page PNGs via the server
    info = await sn.device.query_by_path(
        "/NOTE/Projects/Architecture_Review.note", equipment_no="WEB"
    )
    if info.entries_vo:
        file_id = int(info.entries_vo.id)
        pdf_bytes = await sn.device.get_note_pdf(file_id)
        Path("Architecture_Review.pdf").write_bytes(pdf_bytes)
```

### Managing Task Groups and Tasks (`ScheduleClient`)

`supernote.client.schedule.ScheduleClient` wraps the `/api/file/schedule/*` endpoints with async iterators for automatic pagination and RFC 5545 `.ics` feed export:

```python
from supernote.client import Supernote
from supernote.client.schedule import ScheduleClient


async def manage_schedule(sn: Supernote) -> None:
    schedule = ScheduleClient(sn.client)

    # Create a task group (task list)
    group = await schedule.create_group("Q3 Engineering")
    group_id = group.task_list_id

    # Create a task inside the group (use group_id=None for the default Inbox)
    task = await schedule.create_task(
        group_id=group_id,
        title="Review VFS integrity report",
        detail="Run full-disk check before cutting release",
        status="needsAction",
        importance="high",
    )
    print(f"Created task: {task.task_id}")

    # Iterate through all task groups and tasks (auto-paginated)
    async for grp in schedule.list_groups():
        print(f"Group: {grp.title} ({grp.task_list_id})")

    async for item in schedule.list_tasks(group_id=group_id):
        print(f" - [{item.status}] {item.title} (id={item.task_id})")

    # Mark task completed
    if task.task_id:
        await schedule.update_task(
            task_id=task.task_id,
            title="Review VFS integrity report",
            status="completed",
        )

    # Export tasks as an RFC 5545 iCalendar (.ics) feed
    ics_text = await schedule.get_ical_feed(group_id=group_id)
    print(ics_text[:200])
```

### Semantic Search, Transcripts, and AI Summaries (`ExtendedClient`)

When connected to the self-hosted `supernote` server with AI processing enabled, `supernote.client.extended.ExtendedClient` queries the indexed knowledge base:

```python
from supernote.client import Supernote
from supernote.client.extended import ExtendedClient


async def query_knowledge_base(sn: Supernote, file_id: int) -> None:
    ext = ExtendedClient(sn.client)

    # 1. Semantic search across all notebook page chunks
    search_resp = await ext.search(
        query="database migration rollback strategy",
        top_n=5,
        name_filter="Architecture",
        date_after="2026-01-01",
    )
    for hit in search_resp.results:
        print(
            f"{hit.file_name} (p.{hit.page_index + 1}, score={hit.score:.2f}): "
            f"{hit.text_preview}"
        )

    # 2. Fetch full or page-range OCR transcript for a notebook
    transcript_resp = await ext.get_transcript(
        file_id=file_id, start_index=0, end_index=4
    )
    print(transcript_resp.transcript)

    # 3. List AI-generated synthesis summaries and OCR transcripts attached to a file
    summaries_resp = await ext.list_summaries(file_id=file_id)
    for summary in summaries_resp.summary_do_list:
        print(f"[{summary.data_source}] {summary.content}")

    # 4. Check background processing status for specific file IDs
    status_resp = await ext.get_processing_status([file_id])
    print(status_resp.status_map)
```

### Listening to Real-Time Push Events (`SupernoteSocketClient`)

`supernote.client.socket.SupernoteSocketClient` connects to the server's Socket.IO endpoint with a signed handshake and yields typed sync events (`SocketMessageData`, `SocketTaskMessageData`, `SocketDigestMessageData`):

```python
import time
from supernote.client.socket import SupernoteSocketClient
from supernote.models.socket import SocketHandshakeParams
from supernote.server.socket_auth import compute_handshake_signature


async def listen_events(host: str, token: str) -> None:
    conn_type = "ANDROID"
    random_val = str(int(time.time() * 1000))
    sign = compute_handshake_signature(token, conn_type, random_val)

    socket_client = SupernoteSocketClient(host)
    await socket_client.connect(
        SocketHandshakeParams(
            token=token,
            type=conn_type,
            random=random_val,
            sign=sign,
        )
    )

    try:
        # Verify heartbeats
        await socket_client.ping()
        await socket_client.check_status()

        # Stream real-time FILE-SYN, TASK-SYN, and DIGEST-SYN messages
        async for msg in socket_client.messages():
            print(f"Event type={msg.msg_type} code={msg.code} data={msg.data}")
    finally:
        await socket_client.disconnect()
```
"""

from . import (
    admin,
    api,
    auth,
    client,
    device,
    exceptions,
    extended,
    login_client,
    schedule,
    socket,
    summary,
    web,
)
from .api import Supernote
from .client import Client

__all__ = [
    "Client",
    "Supernote",
    "admin",
    "api",
    "auth",
    "client",
    "device",
    "exceptions",
    "extended",
    "login_client",
    "schedule",
    "socket",
    "summary",
    "web",
]
