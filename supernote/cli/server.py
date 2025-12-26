"""Server CLI commands."""

import argparse
import getpass
import secrets

import yaml

from supernote.server import app as server_app
from supernote.server.config import AuthConfig, ServerConfig, UsersConfig
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


def add_user(username: str, password: str | None = None):
    if password is None:
        password = getpass.getpass(f"Password for {username}: ")

    # Generate the YAML snippet for a single user
    user_entry = UserService.create_user_entry(username, password)
    users_config = UsersConfig(users=[user_entry])

    # Print YAML to stdout
    print("# Generated Supernote User Entry")
    print("# Append this to your users.yaml file.")
    print(yaml.safe_dump(users_config.to_dict(), default_flow_style=False))


def config_init():
    """Output a default config.yaml with a generated secret."""
    secret = secrets.token_hex(32)
    config = ServerConfig()
    config.auth.secret_key = secret

    print("# Generated Supernote Server Configuration")
    print("# Save this as config.yaml.")
    print(yaml.safe_dump(config.to_dict(), default_flow_style=False))


def generate_secret():
    """Output a 32-byte random hex secret."""
    print(secrets.token_hex(32))


def add_parser(subparsers):
    # Common parent parser for server-related commands that need config access
    base_parser = argparse.ArgumentParser(add_help=False)
    base_parser.add_argument(
        "--config-dir",
        type=str,
        default=None,
        help="Path to configuration directory (default: config/)",
    )

    # 'serve' subcommand
    parser_serve = subparsers.add_parser(
        "serve",
        parents=[base_parser],
        help="Start the Supernote Private Cloud server",
    )
    parser_serve.set_defaults(func=server_app.run)

    # User management
    parser_user = subparsers.add_parser("user", help="User management commands")
    user_subparsers = parser_user.add_subparsers(dest="user_command")

    # user list
    parser_user_list = user_subparsers.add_parser(
        "list",
        parents=[base_parser],
        help="List all users in the current config file",
    )
    parser_user_list.set_defaults(
        func=lambda args: list_users(getattr(args, "config_dir", None))
    )

    # user add
    parser_user_add = user_subparsers.add_parser(
        "add",
        parents=[base_parser],
        help="Generate a user configuration snippet",
    )
    parser_user_add.add_argument("username", type=str, help="Username for the new user")
    parser_user_add.add_argument(
        "--password", type=str, help="Password (if omitted, prompt interactively)"
    )
    parser_user_add.set_defaults(
        func=lambda args: add_user(args.username, args.password)
    )

    # config group
    parser_config = subparsers.add_parser("config", help="Configuration utilities")
    config_subparsers = parser_config.add_subparsers(dest="config_command")

    # config init
    parser_config_init = config_subparsers.add_parser(
        "init",
        parents=[base_parser],
        help="Generate a default config.yaml",
    )
    parser_config_init.set_defaults(func=lambda _: config_init())

    # config secret
    parser_config_secret = config_subparsers.add_parser(
        "generate-secret",
        parents=[base_parser],
        help="Generate a secure random secret",
    )
    parser_config_secret.set_defaults(func=lambda _: generate_secret())


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
