"""Server CLI commands."""

import argparse
import getpass
import hashlib
import secrets

from supernote.server import app as server_app
from supernote.server.config import ServerConfig, UserEntry


def list_users(config_dir: str | None):
    # Load base config
    server_config = ServerConfig.load(config_dir)
    for user in server_config.auth.users:
        status = "active" if user.is_active else "inactive"
        print(f"{user.username} ({status})")


def add_user(username: str, password: str | None = None):
    if password is None:
        password = getpass.getpass(f"Password for {username}: ")

    # Generate the YAML snippet for a single user
    password_md5 = hashlib.md5(password.encode()).hexdigest()
    user_entry = UserEntry(
        username=username,
        password_md5=password_md5,
        display_name=username,
    )

    # Print YAML to stdout
    print("# Generated Supernote User Entry")
    print("# Add this entry to the 'users' list in your config.yaml file.")
    print("- " + user_entry.to_yaml(omit_none=True).strip().replace("\n", "\n  "))


def config_init():
    """Output a default config.yaml with a generated secret."""
    secret = secrets.token_hex(32)
    config = ServerConfig()
    config.auth.secret_key = secret
    config.trace_log_file = None  # Use system storage default

    # Add a sample user entry to the output
    sample_user = UserEntry(
        username="user@example.com",
        password_md5=hashlib.md5(b"password").hexdigest(),
        display_name="Sample User",
    )
    config.auth.users = [sample_user]

    print("# Generated Supernote Server Configuration")
    print("# Save this as config.yaml.")
    print("# You should change the sample user entry below.")
    print(config.to_yaml(omit_none=True))


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
