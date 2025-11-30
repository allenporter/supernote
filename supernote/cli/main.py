"""Main CLI entry point."""

import argparse
import sys

import supernote as sn
from . import notebook, cloud, server


def main():
    parser = argparse.ArgumentParser(
        prog="supernote",
        description="Supernote toolkit for parsing, cloud access, and self-hosting",
    )
    parser.add_argument(
        "--version",
        help="show version information and exit",
        action="version",
        version=f"%(prog)s {sn.__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Notebook commands
    notebook.add_parser(subparsers)

    # Cloud commands
    cloud.add_parser(subparsers)

    # Server commands
    server.add_parser(subparsers)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # Dispatch to appropriate handler
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
