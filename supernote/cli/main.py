"""Main CLI entry point."""

import argparse
import importlib
import sys

SUBPARERS = ["notebook", "client", "server", "admin"]


def main():
    parser = argparse.ArgumentParser(
        prog="supernote",
        description="Supernote toolkit for parsing, self hosting, and service access",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # We load subparsers lazily to handle missing optional dependencies
    # (e.g. 'client' requires aiohttp, 'server' requires sqlalchemy).
    for name in SUBPARERS:
        try:
            mod = importlib.import_module(f".{name}", package="supernote.cli")
            mod.add_parser(subparsers)
        except (ImportError, ModuleNotFoundError) as err:
            # Add a placeholder parser that explains the missing dependency
            p = subparsers.add_parser(
                name, help=f"(Disabled: missing dependencies: {err})"
            )

            def make_error_handler(name: str, err: Exception):
                def error_handler(args: argparse.Namespace):
                    print(
                        f"Error: Command '{name}' failed to load due to missing dependencies: {err}"
                    )
                    error_extra = name
                    if name == "admin":
                        error_extra = "client"
                    print(
                        f"Try installing with: pip install 'supernote[{error_extra}]'"
                    )
                    sys.exit(1)

                return error_handler

            p.set_defaults(func=make_error_handler(name, err))

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
