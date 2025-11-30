import argparse
import os
import getpass
import yaml
import bcrypt

USERS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config", "users.yaml"
)


def load_users(users_file):
    if not os.path.exists(users_file):
        return {"users": []}
    with open(users_file, "r") as f:
        return yaml.safe_load(f) or {"users": []}


def save_users(data, users_file: str):
    with open(users_file, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False)


def list_users(users_file: str):
    users = load_users(users_file)["users"]
    for user in users:
        status = "active" if user.get("is_active", True) else "inactive"
        print(f"{user['username']} ({status})")


def add_user(users_file: str, username: str, password: str | None = None):
    users_data = load_users(users_file)
    users = users_data["users"]
    if any(u["username"] == username for u in users):
        print(f"User '{username}' already exists.")
        return
    if password is None:
        password = getpass.getpass(f"Password for {username}: ")
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    users.append(
        {"username": username, "password_hash": password_hash, "is_active": True}
    )
    save_users(users_data, users_file)
    print(f"User '{username}' created.")


def deactivate_user(users_file: str, username: str):
    users_data = load_users(users_file)
    users = users_data["users"]
    for user in users:
        if user["username"] == username:
            user["is_active"] = False
            save_users(users_data, users_file)
            print(f"User '{username}' deactivated.")
            return
    print(f"User '{username}' not found.")


def add_user_subparser(subparsers: argparse._SubParsersAction) -> None:
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
    parser_user_list.set_defaults(handler=lambda args: list_users(args.users_file))

    # user add
    parser_user_add = user_subparsers.add_parser(
        "add", help="Add a new user to users.yaml"
    )
    parser_user_add.add_argument("username", type=str, help="Username to add")
    parser_user_add.add_argument(
        "--password", type=str, help="Password (if omitted, prompt interactively)"
    )
    parser_user_add.set_defaults(
        handler=lambda args: add_user(args.users_file, args.username, args.password)
    )

    # user deactivate
    parser_user_deactivate = user_subparsers.add_parser(
        "deactivate", help="Deactivate a user in users.yaml"
    )
    parser_user_deactivate.add_argument(
        "username", type=str, help="Username to deactivate"
    )
    parser_user_deactivate.set_defaults(
        handler=lambda args: deactivate_user(args.users_file, args.username)
    )
