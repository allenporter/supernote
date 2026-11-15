"""Command-Line Interface (`supernote`) package for Open Private Cloud and `.note` tooling.

This package implements the `supernote` CLI entry point (`supernote.cli.main.main`) and
organizes subcommands into lazy-loaded modules so offline notebook commands (`create`,
`analyze`, `convert`, `merge`, `reconstruct`) run without importing server or cloud client
dependencies.

> **Looking for terminal usage and flags?** See the **[CLI Reference Guide](../../docs/cli_reference.md)** for complete examples of every `supernote` command.

## Module Structure

- **`supernote.cli.main`**: Top-level `argparse` dispatcher and lazy subcommand loader.
- **`supernote.cli.notebook`**: Offline `.note` inspection, PDF/PNG/SVG/TXT export, merging, reconstruction, and Markdown authoring (`supernote create`).
- **`supernote.cli.server`**: Private Cloud server launcher (`supernote serve`, `--ephemeral`, `--config`).
- **`supernote.cli.client`**: Authenticated user-level cloud operations (`supernote cloud login`, `keys`, `ls`, `upload`, `download`, `insights`, `search`, `socket`, `seed`).
- **`supernote.cli.admin`**: Operator and user management (`supernote admin user`, `set-quota`, `queue`, `tasks`, `reprocess`, `integrity`).
- **`supernote.cli.session`**: Shared CLI authentication helper supporting `FileCacheAuth`, `--api-key` (`SUPERNOTE_API_KEY`), and `--url` (`SUPERNOTE_URL`).
"""
