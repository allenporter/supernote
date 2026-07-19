"""Admin CLI commands."""

import asyncio
import getpass
import hashlib
import sys

from supernote.client.admin import AdminClient
from supernote.client.exceptions import ApiException
from supernote.models.base import TaskType

from .client import create_session


async def add_user_async(
    url: str, email: str, password: str, display_name: str | None = None
):
    """Async implementation of add user."""
    async with create_session(url) as session:
        print(f"Attempting to register user '{email}' on {url}...")

        admin_client = AdminClient(session.client)

        # Hash password
        password_md5 = hashlib.md5(password.encode()).hexdigest()

        # Try Public Registration
        try:
            await admin_client.register(
                email=email,
                password=password_md5,
                username=display_name,
            )
            print("Success! User created (Public Registration).")
            return
        except ApiException:
            # If failed, we don't have detailed status code in simple try/except unless we check exception type
            # But client raises ApiException
            pass

        # Try Admin Creation API
        print("Public registration failed or disabled. Attempting Admin creation...")
        try:
            await admin_client.admin_create_user(
                email=email,
                password=password_md5,
                username=display_name,
            )
            print("Success! User created (Admin API).")
        except Exception as e:
            print(f"Admin creation failed: {e}")
            sys.exit(1)


async def list_users_async(url: str | None = None):
    """Async implementation of list users."""
    async with create_session(url) as session:
        client = session.client
        try:
            users = await client.get_json("/api/admin/users", list)

            print(f"\nTotal Users: {len(users)}\n")
            print(f"{'Username':<30} {'Email':<30} {'Capacity':<10}")
            print("-" * 75)
            for u in users:
                # users is a list of dicts if we passed list to get_json, or we need a VO
                # client.get_json returns data_cls.from_json(result)
                # But list doesn't have from_json.
                # We should probably use raw get or define a List[UserVO] type if we can.
                # For now let's just use raw request to get json list safely.
                pass
        except Exception:
            pass

        # Re-doing list fetch with raw request because of typing limitation in client.get_json for list[dict]
        try:
            resp = await client.get("/api/admin/users")
            users = await resp.json()

            print(f"\nTotal Users: {len(users)}\n")
            print(f"{'Email':<30} {'Name':<20} {'Capacity':<10}")
            print("-" * 65)
            for u in users:
                print(
                    f"{u.get('email', 'N/A'):<30} {u.get('userName', 'N/A'):<20} {u.get('totalCapacity', '0'):<10}"
                )

        except Exception as e:
            print(f"Failed to list users: {e}")


def add_user(args):
    password = args.password
    if not password:
        password = getpass.getpass(f"Password for {args.email}: ")

    display_name = args.name or args.email.split("@")[0]
    asyncio.run(add_user_async(args.url, args.email, password, display_name))


def list_users(args):
    asyncio.run(list_users_async(args.url))


async def reset_password_async(url: str, email: str, password: str):
    """Async implementation of password reset."""
    async with create_session(url) as session:
        print(f"Attempting to reset password for '{email}' on {url}...")
        admin_client = AdminClient(session.client)

        password_md5 = hashlib.md5(password.encode()).hexdigest()

        try:
            await admin_client.admin_reset_password(email, password_md5)
            print("Success! Password Reset.")
        except Exception as e:
            print(f"Failed to reset password: {e}")
            sys.exit(1)


def reset_password(args):
    password = args.password
    if not password:
        password = getpass.getpass(f"New password for {args.email}: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match.")
            sys.exit(1)

    asyncio.run(reset_password_async(args.url, args.email, password))


async def queue_status_async(url: str | None = None):
    """Show the background processing queue status."""
    async with create_session(url) as session:
        admin_client = AdminClient(session.client)
        try:
            status = await admin_client.get_queue_status()
            print()
            print("Queue Processing Status")
            print("=======================")
            print(f"Status:            {'PAUSED' if status.paused else 'RUNNING'}")
            print(f"Queue Size:        {status.queue_size}")
            print(
                f"Processing Files:  {', '.join(map(str, status.processing_files)) if status.processing_files else 'None'}"
            )
            print()
        except Exception as e:
            print(f"Failed to get queue status: {e}")
            sys.exit(1)


async def queue_stop_async(url: str | None = None):
    """Stop/pause the background processing queue."""
    async with create_session(url) as session:
        admin_client = AdminClient(session.client)
        try:
            print("Attempting to stop/pause background queue processing...")
            await admin_client.stop_queue()
            print("Success: Queue processing stopped.")
        except Exception as e:
            print(f"Failed to stop queue: {e}")
            sys.exit(1)


async def queue_start_async(url: str | None = None):
    """Start/resume the background processing queue."""
    async with create_session(url) as session:
        admin_client = AdminClient(session.client)
        try:
            print("Attempting to start/resume background queue processing...")
            await admin_client.start_queue()
            print("Success: Queue processing started.")
        except Exception as e:
            print(f"Failed to start queue: {e}")
            sys.exit(1)


def queue_status(args):
    asyncio.run(queue_status_async(args.url))


def queue_stop(args):
    asyncio.run(queue_stop_async(args.url))


def queue_start(args):
    asyncio.run(queue_start_async(args.url))


async def reprocess_async(url: str, task_type: str, file_id: int | None = None):
    """Async implementation of note reprocessing."""
    async with create_session(url) as session:
        print("Connecting to server to trigger reprocessing...")
        admin_client = AdminClient(session.client)
        try:
            await admin_client.admin_reprocess(task_type, file_id)
            target = f"file ID {file_id}" if file_id is not None else "all files"
            print(f"Success! Triggered reprocessing of '{task_type}' for {target}.")
        except Exception as e:
            print(f"Failed to trigger reprocessing: {e}")
            sys.exit(1)


def reprocess(args):
    asyncio.run(reprocess_async(args.url, args.type, args.file_id))


def add_parser(subparsers):
    # 'admin' parent command
    parser_admin = subparsers.add_parser(
        "admin",
        help="Administrative commands for Supernote Server",
    )
    parser_admin.add_argument("--url", type=str, help="URL of the Supernote Server")

    admin_subparsers = parser_admin.add_subparsers(dest="admin_command")

    # --- User Management ---
    parser_user = admin_subparsers.add_parser("user", help="User management commands")
    user_subparsers = parser_user.add_subparsers(dest="user_command")

    # user list
    parser_user_list = user_subparsers.add_parser(
        "list",
        help="List all users",
    )
    parser_user_list.set_defaults(func=list_users)

    # user add
    parser_user_add = user_subparsers.add_parser(
        "add",
        help="Add a new user",
    )
    parser_user_add.add_argument(
        "email", type=str, help="Email address for the new user"
    )
    parser_user_add.add_argument(
        "--password", type=str, help="Password (if omitted, prompt interactively)"
    )
    parser_user_add.add_argument(
        "--name", type=str, help="Display name (optional)", default=None
    )
    parser_user_add.set_defaults(func=add_user)

    # user reset-password
    parser_user_reset = user_subparsers.add_parser(
        "reset-password",
        help="Reset user password",
    )
    parser_user_reset.add_argument("email", type=str, help="Email address of the user")
    parser_user_reset.add_argument(
        "--password", type=str, help="New password (if omitted, prompt interactively)"
    )
    parser_user_reset.set_defaults(func=reset_password)

    # --- Queue Management ---
    parser_queue = admin_subparsers.add_parser(
        "queue", help="Queue management commands"
    )
    queue_subparsers = parser_queue.add_subparsers(dest="queue_command")

    # queue status
    parser_queue_status = queue_subparsers.add_parser(
        "status",
        help="Show queue processing status",
    )
    parser_queue_status.set_defaults(func=queue_status)

    # queue stop
    parser_queue_stop = queue_subparsers.add_parser(
        "stop",
        help="Stop/pause the queue processing",
    )
    parser_queue_stop.set_defaults(func=queue_stop)

    # queue start
    parser_queue_start = queue_subparsers.add_parser(
        "start",
        help="Start/resume the queue processing",
    )
    parser_queue_start.set_defaults(func=queue_start)

    # --- Note Reprocessing ---
    parser_reprocess = admin_subparsers.add_parser(
        "reprocess",
        help="Force reprocessing of notes by clearing task states on the server",
    )
    reprocess_choices = ["all", *TaskType.friendly_names()]

    parser_reprocess.add_argument(
        "--type",
        choices=reprocess_choices,
        default="summary",
        help="Type of tasks to clear and reprocess (default: summary)",
    )
    parser_reprocess.add_argument(
        "--file-id",
        type=int,
        default=None,
        help="Specific file ID to reprocess (default: all files)",
    )
    parser_reprocess.set_defaults(func=reprocess)
