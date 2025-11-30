"""Server CLI commands."""

import argparse
import getpass
import os

import yaml

from supernote.server import app as server_app
from supernote.server.services.user import UserService


def load_users(users_file):
    if not os.path.exists(users_file):
        return {"users": []}
    with open(users_file, "r") as f:
        return yaml.safe_load(f) or {"users": []}


def save_users(data, users_file: str):
    with open(users_file, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False)


def list_users(users_file: str):
    service = UserService(users_file)
    for user in service.list_users():
        status = "active" if user.get("is_active", True) else "inactive"
        print(f"{user['username']} ({status})")


def add_user(users_file: str, username: str, password: str | None = None):
    service = UserService(users_file)
    if password is None:
        password = getpass.getpass(f"Password for {username}: ")
    if service.add_user(username, password):
        print(f"User '{username}' created.")
    else:
        print(f"User '{username}' already exists.")


def deactivate_user(users_file: str, username: str):
    service = UserService(users_file)
    if service.deactivate_user(username):
        print(f"User '{username}' deactivated.")
    else:
        print(f"User '{username}' not found.")


def add_parser(subparsers):
    # 'serve' subcommand
    parser_serve = subparsers.add_parser(
        "serve", help="Start the Supernote Private Cloud server"
    )
    parser_serve.set_defaults(func=server_app.run)

    # User management
    parser_user = subparsers.add_parser("user", help="User management commands")
    parser_user.add_argument(
        "--users-file",
        type=str,
        default="./config/users.yaml",
        help="Path to users.yaml file",
    )
    user_subparsers = parser_user.add_subparsers(dest="user_command")

    # user list
    parser_user_list = user_subparsers.add_parser(
        "list", help="List all users in users.yaml"
    )
    parser_user_list.set_defaults(func=lambda args: list_users(args.users_file))

    # user add
    parser_user_add = user_subparsers.add_parser(
        "add", help="Add a new user to users.yaml"
    )
    parser_user_add.add_argument("username", type=str, help="Username to add")
    parser_user_add.add_argument(
        "--password", type=str, help="Password (if omitted, prompt interactively)"
    )
    parser_user_add.set_defaults(
        func=lambda args: add_user(args.users_file, args.username, args.password)
    )

    # user deactivate
    parser_user_deactivate = user_subparsers.add_parser(
        "deactivate", help="Deactivate a user in users.yaml"
    )
    parser_user_deactivate.add_argument(
        "username", type=str, help="Username to deactivate"
    )
    parser_user_deactivate.set_defaults(
        func=lambda args: deactivate_user(args.users_file, args.username)
    )


def main():
    parser = argparse.ArgumentParser(description="Supernote Server CLI")
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)
    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
