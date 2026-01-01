"""Main CLI entry point."""

import argparse
import sys

from . import client, notebook, server

SUBPARSERS = [
    notebook,
    client,
    server,
]


def main():
    parser = argparse.ArgumentParser(
        prog="supernote",
        description="Supernote toolkit for parsing, self hosting, and service access",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    for subparser in SUBPARSERS:
        subparser.add_parser(subparsers)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # Dispatch
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
