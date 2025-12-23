"""Server CLI commands."""

import argparse
import getpass

from supernote.server import app as server_app
from supernote.server.config import AuthConfig, ServerConfig
from supernote.server.services.user import UserService


def get_auth_config(config_dir: str | None) -> AuthConfig:
    # Load base config
    server_config = ServerConfig.load(config_dir)
    return server_config.auth


def list_users(config_dir: str | None):
    config = get_auth_config(config_dir)
    service = UserService(config)
    for user in service.list_users():
        status = "active" if user.is_active else "inactive"
        print(f"{user.username} ({status})")


def add_user(config_dir: str | None, username: str, password: str | None = None):
    config = get_auth_config(config_dir)
    service = UserService(config)
    if password is None:
        password = getpass.getpass(f"Password for {username}: ")
    if service.add_user(username, password):
        print(f"User '{username}' created.")
    else:
        print(f"User '{username}' already exists.")


def deactivate_user(config_dir: str | None, username: str):
    config = get_auth_config(config_dir)
    service = UserService(config)
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
    user_subparsers = parser_user.add_subparsers(dest="user_command")

    # user list
    parser_user_list = user_subparsers.add_parser("list", help="List all users")
    parser_user_list.set_defaults(func=lambda args: list_users(args.config_dir))

    # user add
    parser_user_add = user_subparsers.add_parser("add", help="Add a new user")
    parser_user_add.add_argument("username", type=str, help="Username to add")
    parser_user_add.add_argument(
        "--password", type=str, help="Password (if omitted, prompt interactively)"
    )
    parser_user_add.set_defaults(
        func=lambda args: add_user(args.config_dir, args.username, args.password)
    )

    # user deactivate
    parser_user_deactivate = user_subparsers.add_parser(
        "deactivate", help="Deactivate a user"
    )
    parser_user_deactivate.add_argument(
        "username", type=str, help="Username to deactivate"
    )
    parser_user_deactivate.set_defaults(
        func=lambda args: deactivate_user(args.config_dir, args.username)
    )


def main():
    parser = argparse.ArgumentParser(description="Supernote Server CLI")
    parser.add_argument(
        "--config-dir",
        type=str,
        default=None,
        help="Path to configuration directory (default: config/)",
    )
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)
    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
