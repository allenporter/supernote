"""Client CLI commands."""

import asyncio
import getpass
import logging
import os
import sys
import traceback
from contextlib import asynccontextmanager

from supernote.client import Supernote
from supernote.client.auth import ConstantAuth, FileCacheAuth
from supernote.client.exceptions import SmsVerificationRequired, SupernoteException

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
        if user_resp.user:
            user = user_resp.user
            print(f"    - User Name: {user.user_name}")
            print(f"    - Email: {user.email}")
            print(f"    - Country Code: {user.country_code}")
            if user.file_server:
                print(f"    - File Server: {user.file_server}")
        else:
            print("    - No user information returned")
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


def subcommand_cloud_rm(args) -> None:
    """Handler for cloud-rm subcommand."""
    asyncio.run(async_cloud_rm(args.path, args.verbose))


def add_parser(subparsers):
    """Add the cloud subparser to the main subparsers."""
    cloud_parser = subparsers.add_parser("cloud", help="Interact with Supernote Cloud")
    cloud_subparsers = cloud_parser.add_subparsers(
        dest="cloud_command", help="Cloud command"
    )

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
