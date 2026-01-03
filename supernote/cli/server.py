"""Server CLI commands."""

import argparse
import logging

from supernote.server import app as server_app

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("supernote-cli")


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
    parser_serve.set_defaults(func=server_app.run)


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
