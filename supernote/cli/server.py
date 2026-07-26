import argparse
import logging
import os
import tempfile
from pathlib import Path

from supernote.server import app as server_app

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("supernote-cli")

# For ephemeral mode
DEBUG_EMAIL = "debug@example.com"
DEBUG_PASSWORD = "password"
LOGIN_COMMAND = "supernote cloud login --url http://{SUPERNOTE_HOST}:{SUPERNOTE_PORT} {DEBUG_EMAIL} --password {DEBUG_PASSWORD}"
EXAMPLE_COMMAND = "supernote cloud ls"


def serve_run(args: argparse.Namespace) -> None:
    """Wrapper for serve command to handle ephemeral mode."""
    if getattr(args, "ephemeral", False):
        with tempfile.TemporaryDirectory(prefix="supernote-ephemeral-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            # Create system directory for database
            (tmp_path / "system").mkdir(parents=True, exist_ok=True)

            # Set environment variables for the server process
            os.environ["SUPERNOTE_EPHEMERAL"] = "true"
            if not os.getenv("SUPERNOTE_PORT"):
                os.environ["SUPERNOTE_PORT"] = "8080"
            if not os.getenv("SUPERNOTE_HOST"):
                os.environ["SUPERNOTE_HOST"] = "127.0.0.1"
            os.environ["SUPERNOTE_STORAGE_DIR"] = str(tmp_path)

            print(f"Using ephemeral mode with storage directory: {tmp_path}")
            print(f"Created default user: {DEBUG_EMAIL} / {DEBUG_PASSWORD}")
            print("Run command to login:")
            print(
                "  "
                + LOGIN_COMMAND.format(
                    SUPERNOTE_HOST=os.getenv("SUPERNOTE_HOST"),
                    SUPERNOTE_PORT=os.getenv("SUPERNOTE_PORT"),
                    DEBUG_EMAIL=DEBUG_EMAIL,
                    DEBUG_PASSWORD=DEBUG_PASSWORD,
                )
            )
            print("Run command to test:")
            print("  " + EXAMPLE_COMMAND)
            server_app.run(args)
    else:
        server_app.run(args)


def add_parser(subparsers):
    # Common parent parser
    base_parser = argparse.ArgumentParser(add_help=False)
    base_parser.add_argument(
        "--config-dir",
        type=str,
        default=None,
        help="Path to configuration directory (default: config/)",
    )
    parser_serve = subparsers.add_parser(
        "serve",
        parents=[base_parser],
        help="Start the Supernote Private Cloud server",
    )
    parser_serve.add_argument(
        "--ephemeral",
        action="store_true",
        help="Run in isolated temporary environment with random port and debug user",
    )
    parser_serve.set_defaults(func=serve_run)


def main() -> None:
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
