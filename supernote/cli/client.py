"""Client CLI commands."""

import asyncio
import getpass
import logging
import os
import sys
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from supernote.client import Supernote, extended
from supernote.client.auth import ConstantAuth, FileCacheAuth
from supernote.client.exceptions import SmsVerificationRequired, SupernoteException
from supernote.client.schedule import ScheduleClient
from supernote.client.socket import SupernoteSocketClient
from supernote.models.extended import WebSummaryListVO
from supernote.models.socket import SocketHandshakeParams
from supernote.server.socket_auth import compute_handshake_signature

_LOGGER = logging.getLogger(__name__)


def load_cached_auth(url: str | None = None) -> tuple[FileCacheAuth, str]:
    """Load cached credentials."""
    cache_path = os.path.expanduser("~/.cache/supernote.pkl")
    if not os.path.exists(cache_path) and not url:
        print(f"Error: No cached credentials found at {cache_path}")
        print("Please run 'supernote cloud-login --url <URL>' first.")
        sys.exit(1)

    auth = FileCacheAuth(cache_path)
    if not url:
        url = auth.get_host()
        if not url:
            print("Error: No server URL found in cached credentials.")
            print("Please run 'supernote cloud-login --url <URL>' first.")
            sys.exit(1)

    return auth, url


@asynccontextmanager
async def create_session(url: str | None = None) -> Supernote:
    """Initialize Supernote session with cached credentials."""
    auth, url = load_cached_auth(url)
    async with Supernote.from_auth(auth, host=url) as sn:
        yield sn


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )
    # Enable debug logging for cloud modules and aiohttp
    if verbose:
        logging.getLogger("supernote").setLevel(logging.DEBUG)
        logging.getLogger("aiohttp").setLevel(logging.DEBUG)


async def async_cloud_login(
    email: str, password: str, url: str, verbose: bool = False
) -> None:
    """Perform cloud login with detailed debugging output.

    Args:
        email: User email/account
        password: User password
        url: Server URL (e.g. http://localhost:8080)
        verbose: Enable verbose HTTP logging
    """
    setup_logging(verbose)

    print("=" * 80)
    print("Supernote Cloud Login Debugging Tool")
    print("=" * 80)
    print(f"Email: {email}")
    print(f"URL: {url}")
    print(
        f"Verbose Mode: {'ENABLED' if verbose else 'DISABLED (use -v or --verbose for detailed logs)'}"
    )
    print("=" * 80)
    print()

    try:
        # Step 1: Login
        print("Step 1: Starting login flow...")
        print("  - This will get CSRF token")
        print("  - Call token endpoint")
        print("  - Get random code")
        print("  - Encode password")
        print("  - Submit login request")
        print()

        try:
            sn = await Supernote.login(email, password, host=url)
        except SmsVerificationRequired as err:
            sn = await _handle_sms_verification(email, url, err)

        async with sn:
            access_token = sn.token
            print("✓ Login successful!")
            print(
                f"Access Token: {access_token[:20]}..."
                if access_token and len(access_token) > 20
                else access_token
            )
            print()

            # Save token to cache
            cache_path = os.path.expanduser("~/.cache/supernote.pkl")
            print(f"Saving credentials to {cache_path}...")
            auth = FileCacheAuth(cache_path)
            auth.save_credentials(access_token, url)
            print("✓ Credentials saved!")
            print()

            await _run_login_sanity_tests(sn)

    except SupernoteException as err:
        print()
        print("=" * 80)
        print(f"✗ Error during login flow: {err}")
        print("=" * 80)
        if verbose:
            traceback.print_exc()
        sys.exit(1)
    except Exception as err:
        print()
        print("=" * 80)
        print(f"✗ Unexpected error: {err}")
        print("=" * 80)
        if verbose:
            traceback.print_exc()
        sys.exit(1)


async def _handle_sms_verification(
    email: str, url: str, err: SmsVerificationRequired
) -> Supernote:
    """Handle SMS verification flow."""
    async with Supernote(host=url) as temp_sn:
        print()
        print("!" * 80)
        print("SMS Verification Required")
        print("!" * 80)
        print(f"Message: {err}")
        print("The server has sent an SMS verification code to your phone.")
        print()

        print("Requesting SMS verification code...")
        await temp_sn.login_client.request_sms_code(email)
        print("SMS code requested successfully.")
        print()

        code = input("Enter verification code: ").strip()
        print()
        print("Submitting verification code...")

        access_token = await temp_sn.login_client.sms_login(email, code, err.timestamp)
        # Create authenticated session
        return temp_sn.with_auth(ConstantAuth(access_token))


async def _run_login_sanity_tests(sn: Supernote) -> None:
    """Run basic functionality tests after login."""
    print("Step 3: Testing basic functionality...")

    # Test 1: Query user
    print("  Test 1: Querying user information...")
    try:
        user_resp = await sn.web.query_user()
        print("  ✓ User query successful!")
        print(f"    - User Name: {user_resp.user_name}")
        print(f"    - Email: {user_resp.email}")
        print(f"    - Country Code: {user_resp.country_code}")
        if user_resp.file_server:
            print(f"    - File Server: {user_resp.file_server}")
    except SupernoteException as err:
        print(f"  ✗ User query failed: {err}")
    print()

    # Test 2: Listing files
    print("  Test 2: Listing files in root directory...")
    try:
        list_resp = await sn.device.list_folder("/")
        print("  ✓ File list successful!")
        files = list_resp.entries
        print(f"    - Files count: {len(files)}")

        if files:
            print("    - First few files:")
            for file in files[:5]:
                folder_marker = "📁" if file.tag == "folder" else "📄"
                print(f"      {folder_marker} {file.name} (ID: {file.id})")
        else:
            print("    - No files found")
    except SupernoteException as err:
        print(f"  ✗ File list failed: {err}")
    print()

    print("=" * 80)
    print("All tests completed successfully!")
    print("=" * 80)


def subcommand_cloud_login(args) -> None:
    """Handler for cloud-login subcommand."""
    password = args.password
    if not password:
        password = getpass.getpass(f"Password for {args.email}: ")

    asyncio.run(async_cloud_login(args.email, password, args.url, args.verbose))


async def async_cloud_ls(path: str, verbose: bool = False) -> None:
    """List files in Supernote Cloud using cached credentials."""
    setup_logging(verbose)

    try:
        async with create_session() as sn:
            print(f"Using server: {sn.client.host}")

            print(f"Listing files in {path}...")
            list_resp = await sn.device.list_folder(path)
            files = list_resp.entries

            print(f"Total files: {len(files)}")
            if files:
                for file in files:
                    folder_marker = "📁" if file.tag == "folder" else "📄"
                    print(f"{folder_marker} {file.name} (ID: {file.id})")

    except SupernoteException as err:
        print(f"Error: {err}")
        if verbose:
            traceback.print_exc()
        sys.exit(1)
    except Exception as err:
        print(f"Unexpected error: {err}")
        if verbose:
            traceback.print_exc()
        sys.exit(1)


def subcommand_cloud_ls(args) -> None:
    """Handler for cloud-ls subcommand."""
    asyncio.run(async_cloud_ls(args.path, args.verbose))


async def async_cloud_upload(
    local_path: str, remote_path: str, verbose: bool = False
) -> None:
    """Upload a file to Supernote Cloud."""
    setup_logging(verbose)

    if not os.path.exists(local_path):
        print(f"Error: Local file not found: {local_path}")
        sys.exit(1)

    try:
        with open(local_path, "rb") as f:
            content = f.read()

        async with create_session() as sn:
            print(f"Uploading {local_path} to {remote_path}...")
            await sn.device.upload_content(remote_path, content)
            print("✓ Upload successful!")
    except SupernoteException as err:
        print(f"Error: {err}")
        sys.exit(1)


def subcommand_cloud_upload(args) -> None:
    """Handler for cloud-upload subcommand."""
    # If remote_path is not provided, use the same filename in the root directory
    remote_path = args.remote_path
    if not remote_path:
        remote_path = "/" + os.path.basename(args.local_path)
    # If remote_path is a directory (ends with /), append the local filename
    elif remote_path.endswith("/"):
        remote_path += os.path.basename(args.local_path)

    asyncio.run(async_cloud_upload(args.local_path, remote_path, args.verbose))


async def async_cloud_download(
    remote_path: str, local_path: str, verbose: bool = False
) -> None:
    """Download a file from Supernote Cloud."""
    setup_logging(verbose)

    try:
        async with create_session() as sn:
            print(f"Downloading {remote_path} to {local_path}...")
            content = await sn.device.download_content(path=remote_path)

            with open(local_path, "wb") as f:
                f.write(content)
            print(f"✓ Downloaded to {local_path}")
    except SupernoteException as err:
        print(f"Error: {err}")
        sys.exit(1)


def subcommand_cloud_download(args) -> None:
    """Handler for cloud-download subcommand."""
    local_path = args.local_path
    if not local_path:
        local_path = os.path.basename(args.remote_path)
    elif os.path.isdir(local_path):
        local_path = os.path.join(local_path, os.path.basename(args.remote_path))

    asyncio.run(async_cloud_download(args.remote_path, local_path, args.verbose))


async def async_cloud_mkdir(path: str, verbose: bool = False) -> None:
    """Create a folder in Supernote Cloud."""
    setup_logging(verbose)

    try:
        async with create_session() as sn:
            print(f"Creating folder: {path}...")
            await sn.device.create_folder(path, equipment_no="WEB")
            print("✓ Folder created successfully!")
    except SupernoteException as err:
        print(f"Error: {err}")
        sys.exit(1)


def subcommand_cloud_mkdir(args) -> None:
    """Handler for cloud-mkdir subcommand."""
    asyncio.run(async_cloud_mkdir(args.path, args.verbose))


async def async_cloud_rm(path: str, verbose: bool = False) -> None:
    """Remove a file or folder from Supernote Cloud."""
    setup_logging(verbose)

    try:
        async with create_session() as sn:
            print(f"Removing {path}...")
            await sn.device.delete_by_path(path)
            print("✓ Removed successfully!")
    except SupernoteException as err:
        print(f"Error: {err}")
        sys.exit(1)


async def async_cloud_insights(path: str, verbose: bool = False) -> None:
    """Show AI insights for a file in Supernote Cloud."""
    setup_logging(verbose)

    try:
        async with create_session() as sn:
            print(f"Resolving path: {path}...")
            # Query by path to get ID
            info = await sn.device.query_by_path(path, equipment_no="CLI")
            if not info.entries_vo:
                print(f"Error: File not found: {path}")
                sys.exit(1)

            file_id = int(info.entries_vo.id)
            print(f"Fetching insights for {info.entries_vo.name} (ID: {file_id})...")

            # Using the extended client to list summaries
            extended_client = extended.ExtendedClient(sn.client)
            summaries_vo: WebSummaryListVO = await extended_client.list_summaries(
                file_id
            )
            summaries = summaries_vo.summary_do_list

            if not summaries:
                print(
                    "No insights found. The note might still be processing or Gemini is not configured."
                )
                return

            print("\n" + "=" * 40)
            print(" AI INSIGHTS & SYNCHRONIZED SYNTHESIS")
            print("=" * 40 + "\n")

            # Sort by creation time desc
            sorted_summaries = sorted(
                summaries, key=lambda x: x.creation_time or 0, reverse=True
            )

            for item in sorted_summaries:
                source = item.data_source or "AI Synthesis"
                date_str = ""
                if item.creation_time:
                    date_str = f" ({datetime.fromtimestamp(item.creation_time / 1000).strftime('%Y-%m-%d %H:%M')})"

                # Use blue color for header if in TTY
                header = f"[{source.upper()}]{date_str}"
                if sys.stdout.isatty():
                    print(f"\033[1;34m{header}\033[0m")
                else:
                    print(header)

                print("-" * len(header))
                print(item.content)
                print("\n")

    except SupernoteException as err:
        print(f"Error: {err}")
        sys.exit(1)
    except Exception as err:
        print(f"Unexpected error: {err}")
        if verbose:
            traceback.print_exc()
        sys.exit(1)


def subcommand_cloud_rm(args) -> None:
    """Handler for cloud-rm subcommand."""
    asyncio.run(async_cloud_rm(args.path, args.verbose))


def subcommand_cloud_insights(args) -> None:
    """Handler for cloud-insights subcommand."""
    asyncio.run(async_cloud_insights(args.path, args.verbose))


async def async_cloud_search(
    query: str,
    top_n: int = 5,
    name_filter: str | None = None,
    after: str | None = None,
    before: str | None = None,
    verbose: bool = False,
) -> None:
    """Perform semantic search."""
    setup_logging(verbose)
    try:
        async with create_session() as sn:
            extended_client = extended.ExtendedClient(sn.client)
            resp = await extended_client.search(
                query=query,
                top_n=top_n,
                name_filter=name_filter,
                date_after=after,
                date_before=before,
            )
            if not resp.results:
                print("No results found.")
                return

            print(f"\nSemantic Search Results for: '{query}'")
            print("=" * 60)
            for i, res in enumerate(resp.results, 1):
                score_pct = f"{res.score * 100:.1f}%"
                date_str = f" [{res.date}]" if res.date else ""
                print(
                    f"\n{i}. \033[1;36m{res.file_name}\033[0m (Page {res.page_index + 1}){date_str}"
                )
                print(f"   Relevance: \033[1;32m{score_pct}\033[0m")
                print("   ---")
                # Indent the text preview
                preview = res.text_preview.replace("\n", "\n   ")
                print(f"   {preview}")
            print("\n" + "=" * 60)
    except SupernoteException as err:
        print(f"Error: {err}")
        sys.exit(1)
    except Exception as err:
        print(f"Unexpected error: {err}")
        if verbose:
            traceback.print_exc()
        sys.exit(1)


def subcommand_cloud_search(args) -> None:
    """Handler for cloud-search subcommand."""
    asyncio.run(
        async_cloud_search(
            args.query,
            args.top_n,
            args.name_filter,
            args.after,
            args.before,
            args.verbose,
        )
    )


async def async_cloud_socket(
    duration: float = 10.0,
    conn_type: str = "ANDROID",
    verbose: bool = False,
) -> None:
    """Connect to Socket.IO real-time server, verify heartbeat, and listen for events."""
    setup_logging(verbose)
    try:
        auth_data, base_url = load_cached_auth()
        token = await auth_data.async_get_access_token()

        random_val = str(int(time.time() * 1000))
        sign = compute_handshake_signature(token, conn_type, random_val)

        params = SocketHandshakeParams(
            token=token,
            type=conn_type,
            random=random_val,
            sign=sign,
        )

        print(f"Connecting to Socket.IO server at {base_url}...")
        print(
            f"  Handshake parameters: type='{conn_type}', random='{random_val}', sign='{sign[:8]}...'"
        )

        socket_client = SupernoteSocketClient(base_url)
        await socket_client.connect(params)
        print("\033[1;32m[SUCCESS] Connected to Socket.IO real-time server!\033[0m")

        # Test heartbeat ping
        print("\nTesting heartbeat ping (ratta_ping)...")
        try:
            await socket_client.ping(timeout=3.0)
            print("  Ping: \033[1;32mOK (Received response)\033[0m")
        except Exception as err:
            print(f"  Ping failed: {err}")

        # Test status check
        print("Testing status check (ClientMessage status)...")
        try:
            await socket_client.check_status(timeout=3.0)
            print("  Status check: \033[1;32mOK (Received status confirmation)\033[0m")
        except Exception as err:
            print(f"  Status check failed: {err}")

        if duration > 0:
            print(
                f"\nListening for Socket.IO push events for {duration} seconds (Press Ctrl+C to stop)..."
            )
        else:
            print(
                "\nListening for Socket.IO push events indefinitely (Press Ctrl+C to stop)..."
            )
        print("=" * 60)

        async def _listen_loop() -> None:
            async for msg in socket_client.messages():
                print(
                    f"\n\033[1;34m[SOCKET EVENT]\033[0m Code: {msg.code}, Type: {msg.msg_type}, Msg: {msg.msg}"
                )
                if msg.data:
                    for item in msg.data:
                        print(f"  - Action: {item.message_type or item.action}")
                        if item.equipment_no:
                            print(f"    Equipment: {item.equipment_no}")
                        if item.id:
                            print(f"    Item ID: {item.id}")
                        if item.file_type:
                            print(f"    File Type: {item.file_type}")
                        if item.file_name:
                            print(f"    File Name: {item.file_name}")
                        if item.file_path:
                            print(f"    File Path: {item.file_path}")

        try:
            if duration > 0:
                await asyncio.wait_for(_listen_loop(), timeout=duration)
            else:
                await _listen_loop()
        except asyncio.TimeoutError:
            print(f"\nCompleted listening duration of {duration} seconds.")
        except KeyboardInterrupt:
            print("\nListening stopped by user.")
        finally:
            await socket_client.disconnect()
            print("Disconnected cleanly from Socket.IO server.")

    except SupernoteException as err:
        print(f"Error: {err}")
        sys.exit(1)
    except Exception as err:
        print(f"Unexpected error: {err}")
        if verbose:
            traceback.print_exc()
        sys.exit(1)


def subcommand_cloud_socket(args) -> None:
    """Handler for cloud-socket subcommand."""
    asyncio.run(
        async_cloud_socket(
            duration=args.duration,
            conn_type=args.type,
            verbose=args.verbose,
        )
    )


async def async_cloud_seed(
    url: str = "http://127.0.0.1:8080",
    email: str = "debug@example.com",
    password: str = "password",
    verbose: bool = False,
) -> None:
    """Populate development server with sample notes and schedule tasks."""

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    print(f"==> Connecting to server at {url}...")
    try:
        sn = await Supernote.login(email, password, host=url)
    except Exception:
        print(f"User {email} not found, attempting registration via AdminClient...")
        import aiohttp  # noqa: PLC0415

        from supernote.client.admin import AdminClient  # noqa: PLC0415

        async with aiohttp.ClientSession() as session:
            admin_client = AdminClient(session, host=url)
            await admin_client.register(email, password, "Debug User")
        sn = await Supernote.login(email, password, host=url)

    async with sn:
        print(f"✓ Logged in as {email}")

        schedule = ScheduleClient(sn.client)

        print("\n--- Creating Task Groups & Tasks ---")

        # Group 0: Inbox
        print("Created Inbox Tasks (group_id=0)")
        await schedule.create_task(
            0,
            "Review handwritten meeting notes",
            detail="Check OCR transcripts and summarize key takeaways",
            status="needsAction",
            importance="high",
        )
        await schedule.create_task(
            0,
            "Organize Supernote inbox folder",
            detail="Sort recent .note files into projects and document categories",
            status="needsAction",
            importance="normal",
        )

        # Group 1: Work & Projects
        g1 = await schedule.create_group("Work & Projects")
        g1_id = int(g1.task_list_id)
        print(f"Created Group: Work & Projects (id={g1_id})")

        await schedule.create_task(
            g1_id,
            "Finalize Q3 Supernote Architecture Proposal",
            detail="Review VFS layer and MCP server integration.",
            status="needsAction",
            importance="high",
        )
        await schedule.create_task(
            g1_id,
            "Deploy Partner App Integration",
            detail="Verify OAuth & API sync flows against server",
            status="needsAction",
            importance="high",
        )
        await schedule.create_task(
            g1_id,
            "Setup CI/CD Pipeline for Supernote",
            detail="Automate ruff, mypy and pytest runs on PR",
            status="completed",
            importance="normal",
        )

        # Group 2: Personal & Notes
        g2 = await schedule.create_group("Personal & Notes")
        g2_id = int(g2.task_list_id)
        print(f"Created Group: Personal & Notes (id={g2_id})")

        await schedule.create_task(
            g2_id,
            "Buy Stylus Replacement Nibs",
            detail="Check Supernote store for FeelWrite 2 nibs",
            status="needsAction",
            importance="normal",
        )
        await schedule.create_task(
            g2_id,
            "Weekly Journal Review",
            detail="Review handwritten notes from last week",
            status="needsAction",
            importance="high",
        )

        print("\n--- Creating Cloud Directories & Uploading Files ---")
        folders = [
            "/NOTE",
            "/NOTE/Note",
            "/NOTE/MyStyle",
            "/DOCUMENT",
            "/DOCUMENT/Document",
            "/EXPORT",
            "/SCREENSHOT",
            "/INBOX",
        ]
        for folder in folders:
            try:
                await sn.device.create_folder(folder, equipment_no="WEB")
                print(f"Created folder: {folder}")
            except Exception:
                pass

        test_notes = [
            ("tests/testdata/20251207_221454.note", "/NOTE/Note/20251207_221454.note"),
            ("tests/testdata/philips/test.note", "/NOTE/Note/Meeting_Notes.note"),
            ("tests/testdata/philips/manta.note", "/NOTE/Note/Project_Ideas.note"),
            (
                "tests/testdata/dsummersl/sn2md_20260618.note",
                "/NOTE/Note/Weekly_Journal.note",
            ),
            (
                "tests/testdata/mmujynya/stroller.note",
                "/DOCUMENT/Document/Stroller_Specs.note",
            ),
            (
                "tests/testdata/philips/horizontal_1090.note",
                "/DOCUMENT/Document/Horizontal_Diagram.note",
            ),
        ]

        for local_file, remote_path in test_notes:
            path_obj = Path(local_file)
            if path_obj.exists():
                content = path_obj.read_bytes()
                print(
                    f"Uploading {local_file} -> {remote_path} ({len(content)} bytes)..."
                )
                await sn.device.upload_content(remote_path, content, equipment_no="WEB")
                print(f"  ✓ Uploaded {remote_path}")

        print("\n=== Server Seed Completed Successfully! ===")


def subcommand_cloud_seed(args) -> None:
    """Handler for cloud-seed subcommand."""
    asyncio.run(
        async_cloud_seed(
            url=args.url,
            email=args.email,
            password=args.password,
            verbose=args.verbose,
        )
    )


def add_parser(subparsers):
    """Add the cloud subparser to the main subparsers."""
    cloud_parser = subparsers.add_parser("cloud", help="Interact with Supernote Cloud")
    cloud_subparsers = cloud_parser.add_subparsers(dest="cloud_command", required=True)

    # 'cloud seed' subcommand
    parser_seed = cloud_subparsers.add_parser(
        "seed", help="Seed development server with sample notes and schedule tasks"
    )
    parser_seed.add_argument(
        "--url", type=str, default="http://127.0.0.1:8080", help="Server URL"
    )
    parser_seed.add_argument(
        "--email", type=str, default="debug@example.com", help="User email"
    )
    parser_seed.add_argument(
        "--password", type=str, default="password", help="User password"
    )
    parser_seed.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser_seed.set_defaults(func=subcommand_cloud_seed)

    # 'cloud login' subcommand
    parser_login = cloud_subparsers.add_parser(
        "login", help="Authenticate with Supernote Cloud"
    )
    parser_login.add_argument("email", type=str, help="user email/account")
    parser_login.add_argument(
        "--password", type=str, help="user password (prompt if omitted)"
    )
    parser_login.add_argument(
        "--url", type=str, required=True, help="Server URL (e.g. http://localhost:8080)"
    )
    parser_login.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser_login.set_defaults(func=subcommand_cloud_login)

    # 'cloud ls' subcommand
    parser_ls = cloud_subparsers.add_parser("ls", help="List files in Supernote Cloud")
    parser_ls.add_argument(
        "path", type=str, nargs="?", default="/", help="Path to list"
    )
    parser_ls.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser_ls.set_defaults(func=subcommand_cloud_ls)

    # 'cloud upload' subcommand
    parser_upload = cloud_subparsers.add_parser(
        "upload", help="Upload a file to Supernote Cloud"
    )
    parser_upload.add_argument("local_path", type=str, help="Local file path")
    parser_upload.add_argument(
        "remote_path", type=str, nargs="?", help="Cloud destination path (optional)"
    )
    parser_upload.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser_upload.set_defaults(func=subcommand_cloud_upload)

    # 'cloud download' subcommand
    parser_download = cloud_subparsers.add_parser(
        "download", help="Download a file from Supernote Cloud"
    )
    parser_download.add_argument("remote_path", type=str, help="Cloud file path")
    parser_download.add_argument(
        "local_path", type=str, nargs="?", help="Local destination path (optional)"
    )
    parser_download.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser_download.set_defaults(func=subcommand_cloud_download)

    # 'cloud mkdir' subcommand
    parser_mkdir = cloud_subparsers.add_parser(
        "mkdir", help="Create a folder in Supernote Cloud"
    )
    parser_mkdir.add_argument("path", type=str, help="Cloud folder path")
    parser_mkdir.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser_mkdir.set_defaults(func=subcommand_cloud_mkdir)

    # 'cloud rm' subcommand
    parser_rm = cloud_subparsers.add_parser(
        "rm", help="Remove a file or folder from Supernote Cloud"
    )
    parser_rm.add_argument("path", type=str, help="Cloud file or folder path")
    parser_rm.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser_rm.set_defaults(func=subcommand_cloud_rm)

    # 'cloud insights' subcommand
    parser_insights = cloud_subparsers.add_parser(
        "insights", help="Show AI insights and synthesis for a notebook"
    )
    parser_insights.add_argument("path", type=str, help="Cloud file path (.note)")
    parser_insights.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser_insights.set_defaults(func=subcommand_cloud_insights)

    # 'cloud search' subcommand
    parser_search = cloud_subparsers.add_parser(
        "search", help="Perform semantic search across all your notebooks"
    )
    parser_search.add_argument("query", type=str, help="Search query")
    parser_search.add_argument(
        "--top-n", type=int, default=5, help="Number of results to return"
    )
    parser_search.add_argument(
        "--name-filter", type=str, help="Filter by notebook name"
    )
    parser_search.add_argument(
        "--after", type=str, help="Filter by date after (YYYY-MM-DD)"
    )
    parser_search.add_argument(
        "--before", type=str, help="Filter by date before (YYYY-MM-DD)"
    )
    parser_search.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser_search.set_defaults(func=subcommand_cloud_search)

    # 'cloud socket' subcommand
    parser_socket = cloud_subparsers.add_parser(
        "socket",
        help="Connect to Socket.IO real-time server and listen for push events",
    )
    parser_socket.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Duration in seconds to listen for events (0 for indefinite)",
    )
    parser_socket.add_argument(
        "--type",
        type=str,
        default="ANDROID",
        help="Handshake connection type parameter (default: ANDROID)",
    )
    parser_socket.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser_socket.set_defaults(func=subcommand_cloud_socket)
