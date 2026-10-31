"""CLI subcommands (`supernote admin`) for server administration and queue maintenance.

This module implements the `supernote admin` command group built on `supernote.client.admin.AdminClient`,
including user lifecycle management (`user add`, `user list`, `user reset-password`), background
processor queue control (`queue status`, `queue stop`, `queue start`), task inspection (`tasks`),
note reprocessing (`reprocess`), and two-way storage integrity checks (`verify-integrity`).
See `supernote.cli` and `supernote.guides.cli_reference`.
"""

import asyncio
import getpass
import hashlib
import json
import sys

from supernote.client.admin import AdminClient
from supernote.client.exceptions import ApiException
from supernote.models.base import ProcessingStatus, TaskType

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


async def integrity_async(
    url: str | None,
    email: str | None = None,
    file_id: int | None = None,
    full_disk: bool = False,
    as_json: bool = False,
) -> None:
    """Verify server storage integrity for a user or across the full disk."""
    async with create_session(url) as session:
        admin_client = AdminClient(session.client)
        try:
            report = await admin_client.verify_integrity(
                email=email, file_id=file_id, full_disk=full_disk
            )
        except Exception as e:
            print(f"Failed to verify integrity: {e}")
            sys.exit(1)

        if as_json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print()
            print("Storage Integrity Report")
            print("========================")
            print(f"Scanned Nodes:     {report.scanned}")
            print(f"OK Nodes:          {report.ok}")
            print(f"Total Issues:      {len(report.issues)}")
            for issue_type, count in report.issue_counts.items():
                print(f"  {issue_type.value + ':':<24} {count}")
            print()
            if report.issues:
                print(f"Issues Found ({len(report.issues)}):")
                print("-" * 75)
                for issue in report.issues:
                    print(
                        f"  [{issue.issue_type.value}] "
                        f"file={issue.file_id} ({issue.file_name}): {issue.detail}"
                    )
                print()
                if report.remediations:
                    print("Suggested Remediation:")
                    for hint in report.remediations:
                        print(f"  - {hint}")
                    print()

        has_failures = bool(report.issues)
        if not as_json:
            if has_failures:
                print("Integrity issues detected.")
            else:
                print("All integrity checks passed.")
        if has_failures:
            sys.exit(1)


def integrity(args) -> None:
    asyncio.run(
        integrity_async(
            url=args.url,
            email=args.email,
            file_id=args.file_id,
            full_disk=args.full_disk,
            as_json=args.json,
        )
    )


async def list_tasks_async(
    url: str | None = None,
    status: str | None = None,
    file_id: int | None = None,
    task_type: str | None = None,
    limit: int = 100,
    as_json: bool = False,
) -> None:
    """List system processing tasks."""
    async with create_session(url) as session:
        admin_client = AdminClient(session.client)
        try:
            resp = await admin_client.list_tasks(
                status=status,
                file_id=file_id,
                task_type=task_type,
                limit=limit,
            )
        except Exception as e:
            print(f"Failed to list tasks: {e}")
            sys.exit(1)

        if as_json:
            print(json.dumps(resp.to_dict(), indent=2))
            return

        tasks = resp.tasks
        print(f"\nSystem Tasks ({len(tasks)}):\n")
        if not tasks:
            print("No matching tasks found.")
            return

        print(
            f"{'File ID':<20} {'Type':<22} {'Key':<15} {'Status':<12} {'Retries':<8} {'Last Error'}"
        )
        print("-" * 95)
        for t in tasks:
            err = (t.last_error or "").replace("\n", " ")
            print(
                f"{t.file_id:<20} {t.task_type:<22} {t.key:<15} {t.status.value:<12} {t.retry_count:<8} {err}"
            )


def list_tasks(args) -> None:
    asyncio.run(
        list_tasks_async(
            url=args.url,
            status=args.status,
            file_id=args.file_id,
            task_type=args.type,
            limit=args.limit,
            as_json=args.json,
        )
    )


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

    # --- Storage Integrity ---
    parser_integrity = admin_subparsers.add_parser(
        "integrity",
        help="Verify VFS and blob storage integrity",
    )
    integrity_scope = parser_integrity.add_mutually_exclusive_group(required=True)
    integrity_scope.add_argument(
        "--email",
        type=str,
        default=None,
        help="Email address of the user to check",
    )
    integrity_scope.add_argument(
        "--full-disk",
        action="store_true",
        help="Perform a global two-way storage check across all users and disk buckets",
    )
    parser_integrity.add_argument(
        "--file-id",
        type=int,
        default=None,
        help="Check only a specific file ID belonging to the user (default: all files)",
    )
    parser_integrity.add_argument(
        "--json",
        action="store_true",
        help="Output the integrity report as JSON",
    )
    parser_integrity.set_defaults(func=integrity)

    # --- System Tasks Inspection ---
    parser_tasks = admin_subparsers.add_parser(
        "tasks",
        help="Inspect background note processing tasks and errors",
    )
    status_choices = [
        s.value.lower() for s in ProcessingStatus if s != ProcessingStatus.NONE
    ]
    parser_tasks.add_argument(
        "--status",
        choices=status_choices,
        type=str.lower,
        default=None,
        help="Filter tasks by status (pending, processing, completed, failed)",
    )
    parser_tasks.add_argument(
        "--file-id",
        type=int,
        default=None,
        help="Filter tasks by file ID",
    )
    parser_tasks.add_argument(
        "--type",
        choices=TaskType.friendly_names(),
        default=None,
        help="Filter tasks by task type (e.g. ocr, png, embedding, summary)",
    )
    parser_tasks.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of tasks to return (default: 100)",
    )
    parser_tasks.add_argument(
        "--json",
        action="store_true",
        help="Output the task list as JSON",
    )
    parser_tasks.set_defaults(func=list_tasks)
