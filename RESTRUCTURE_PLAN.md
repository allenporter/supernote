# Supernote-Lite Restructuring Plan

**Status**: ✅ Completed
**Target Version**: v0.4.0
**Breaking Changes**: Yes (aggressive refactoring)
**Completed**: December 2025

## Vision

Transform `supernote-lite` into a **well-structured all-in-one toolkit** with:
- Clear module boundaries (notebook/cloud/server)
- Clean public API for library users
- Server-first focus with developer-friendly library access
- Foundation for future split into separate packages OR Home Assistant component

## Guiding Principles

1. **Server users first** - Optimize for Docker deployment and self-hosting
2. **Developer-friendly second** - Clean API for integration and reference
3. **Break aggressively** - Don't maintain backward compatibility
4. **Modular monolith** - Clean separation within single package
5. **Future-proof** - Easy to split later OR convert to HA component

---

## Phase 1: Foundation & Cleanup

### 1.1 Version & Documentation Fixes
- [x] Fix version mismatch (`__init__.py` vs `pyproject.toml`)
- [x] Update README.md with accurate description
- [x] We use github for releases which will automatically generate release change logs for tracking purposes based on PR descriptions
- [x] Update package description in `pyproject.toml`

### 1.2 Dependency Management
- [x] Move dependencies to optional extras:
  ```toml
  [project]
  dependencies = [
    # Core notebook parsing (always installed)
    "colour>=0.1.5",
    "numpy>=1.19.0",
    "Pillow>=7.2.0",
    "potracer>=0.0.1",
    "pypng>=0.0.20",
    "reportlab>=3.6.1",
    "svgwrite>=1.4",
  ]

  [project.optional-dependencies]
  cloud = [
    "aiohttp>=3.13.2",
    "mashumaro>=3.17",
  ]
  server = [
    "aiohttp>=3.13.2",
    "mashumaro>=3.17",
    "pyyaml>=6.0",
    "PyJWT>=2.10.1",
  ]
  all = ["supernote[cloud,server]"]
  ```

### 1.3 Git Cleanup
- [x] Review `.gitignore` for server artifacts (`storage/`, `*.log`, `config/*.yaml`)
- [x] Add `.gitattributes` if needed
- [x] Clean up any committed files that should be ignored

---

## Phase 2: Directory Restructuring

### 2.1 Create New Structure

**Target structure**:
```
supernote/
├── __init__.py              # Public API exports
├── notebook/                # Notebook parsing (moved from root)
│   ├── __init__.py
│   ├── parser.py
│   ├── converter.py
│   ├── decoder.py
│   ├── fileformat.py
│   ├── manipulator.py
│   ├── color.py
│   └── utils.py
├── cloud/                   # Cloud client (already exists, minor cleanup)
│   ├── __init__.py
│   ├── client.py
│   ├── auth.py
│   ├── login_client.py
│   ├── cloud_client.py
│   ├── api_model.py
│   └── exceptions.py
├── server/                  # Server (already exists, keep as-is)
│   ├── __init__.py
│   ├── app.py
│   ├── config.py
│   ├── models/
│   ├── routes/
│   └── services/
└── cli/                     # CLI tools (renamed from cmds/)
    ├── __init__.py
    ├── main.py              # Main entry point
    ├── notebook.py          # Notebook commands
    ├── cloud.py             # Cloud commands
    └── server.py            # Server commands
```

### 2.2 File Moves

**Commands**:
```bash
# Create new directories
mkdir -p supernote/notebook
mkdir -p supernote/cli

# Move notebook files from root to notebook/
git mv supernote/parser.py supernote/notebook/
git mv supernote/converter.py supernote/notebook/
git mv supernote/decoder.py supernote/notebook/
git mv supernote/fileformat.py supernote/notebook/
git mv supernote/manipulator.py supernote/notebook/
git mv supernote/color.py supernote/notebook/
git mv supernote/utils.py supernote/notebook/
git mv supernote/exceptions.py supernote/notebook/

# Rename cmds to cli
git mv supernote/cmds supernote/cli

# Create __init__.py files
touch supernote/notebook/__init__.py
touch supernote/cloud/__init__.py
touch supernote/server/__init__.py
```

### 2.3 Update Internal Imports

**Pattern**: Replace all internal imports to use new structure

```python
# OLD
from supernote.parser import parse_notebook
from supernote.converter import PngConverter

# NEW
from supernote.notebook.parser import parse_notebook
from supernote.notebook.converter import PngConverter
```

**Files to update**:
- [ ] `supernote/cli/*.py` - Update all imports
- [ ] `supernote/server/**/*.py` - Update if any reference notebook code
- [ ] `tests/**/*.py` - Update all test imports
- [ ] Any cross-module imports

---

## Phase 3: Public API Definition

### 3.1 Define Module APIs

**`supernote/__init__.py`**:
```python
"""Supernote toolkit for parsing, cloud access, and self-hosting."""

# Core notebook parsing (always available)
from .notebook import (
    parse_notebook,
    Notebook,
    PngConverter,
    SvgConverter,
    PdfConverter,
    TextConverter,
)

__all__ = [
    # Notebook
    "parse_notebook",
    "Notebook",
    "PngConverter",
    "SvgConverter",
    "PdfConverter",
    "TextConverter",
]

# Optional: Cloud client
try:
    from .cloud import CloudClient, login
    __all__.extend(["CloudClient", "login"])
except ImportError:
    pass

# Optional: Server
try:
    from .server import create_app, Server
    __all__.extend(["create_app", "Server"])
except ImportError:
    pass
```

**`supernote/notebook/__init__.py`**:
```python
"""Supernote notebook parsing and conversion."""

from .parser import parse_notebook, Notebook
from .converter import (
    PngConverter,
    SvgConverter,
    PdfConverter,
    TextConverter,
)

__all__ = [
    "parse_notebook",
    "Notebook",
    "PngConverter",
    "SvgConverter",
    "PdfConverter",
    "TextConverter",
]
```

**`supernote/cloud/__init__.py`**:
```python
"""Supernote Cloud client library."""

from .client import Client
from .auth import AbstractAuth, ConstantAuth, FileCacheAuth
from .cloud_client import SupernoteClient
from .login_client import LoginClient

# Convenience alias
CloudClient = SupernoteClient

__all__ = [
    "Client",
    "AbstractAuth",
    "ConstantAuth",
    "FileCacheAuth",
    "CloudClient",
    "SupernoteClient",
    "LoginClient",
]
```

**`supernote/server/__init__.py`**:
```python
"""Supernote private server implementation."""

from .app import create_app, run
from .config import Config

__all__ = [
    "create_app",
    "run",
    "Config",
]
```

### 3.2 CLI Reorganization

**`supernote/cli/main.py`** - Main entry point:
```python
"""Main CLI entry point."""

import argparse
import sys

from . import notebook, cloud, server


def main():
    parser = argparse.ArgumentParser(
        prog="supernote",
        description="Supernote toolkit for parsing, cloud access, and self-hosting",
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
```

**Split existing `supernote_tool.py` into**:
- `cli/notebook.py` - convert, analyze, merge, reconstruct
- `cli/cloud.py` - cloud-login, cloud-ls
- `cli/server.py` - serve, user management

### 3.3 Entry Points

**`pyproject.toml`**:
```toml
[project.scripts]
supernote = "supernote.cli.main:main"
supernote-server = "supernote.cli.server:main"  # Direct server entry
```

---

## Phase 4: Testing & Validation

### 4.1 Update Tests

- [x] Update all test imports to new structure
- [x] Ensure all existing tests pass
- [x] Add new import tests:
  ```python
  def test_public_api():
      import supernote
      assert hasattr(supernote, "parse_notebook")
      assert hasattr(supernote, "CloudClient")
      assert hasattr(supernote, "create_app")
  ```

### 4.2 CLI Testing

- [x] Test all notebook commands work
- [x] Test cloud commands work
- [x] Test server commands work
- [x] Test help text is clear

### 4.3 Integration Testing

- [x] Test notebook parsing still works
- [x] Test cloud client still works
- [x] Test server still runs
- [x] Test Docker deployment (if applicable)

---

## Phase 5: Documentation

### 5.1 Update README.md

**New structure**:
```markdown
# supernote-lite

All-in-one toolkit for Supernote devices: parse notebooks, access cloud, self-host.

## Features

- **Notebook Parsing**: Convert `.note` files to PDF, PNG, SVG, or text
- **Cloud Client**: Interact with Supernote Cloud API
- **Private Server**: Self-hosted Supernote Cloud replacement

## Installation

```bash
# Full installation (recommended for server users)
pip install supernote[all]

# Or install specific components
pip install supernote              # Notebook parsing only
pip install supernote[cloud]       # + Cloud client
pip install supernote[server]      # + Private server
```

## Quick Start

### Parse a Notebook
```python
from supernote import parse_notebook

notebook = parse_notebook("mynote.note")
notebook.to_pdf("output.pdf")
```

### Access Supernote Cloud
```python
from supernote.cloud import CloudClient

async with CloudClient.from_credentials(email, password) as client:
    files = await client.list_files()
```

### Run Private Server
```bash
# Configure users
supernote-server user add alice

# Start server
supernote-server serve
```

See [Server Documentation](supernote/server/README.md) for details.

## CLI Usage

```bash
# Notebook operations
supernote convert input.note output.pdf
supernote analyze input.note

# Cloud operations
supernote cloud login
supernote cloud ls

# Server operations
supernote-server serve
supernote-server user add alice
```

## Development

This package is designed for:
1. **Server operators** - Self-hosting Supernote Cloud
2. **Developers** - Integrating Supernote into applications
3. **Reference** - Understanding Supernote protocols

See [ARCHITECTURE.md](supernote/server/ARCHITECTURE.md) for protocol details.
```

### 5.2 Add API Documentation

- [x] We use pdoc for all documentation. Documentation lives at https://allenporter.github.io/supernote-lite.
- [ ] Include README.md in docstrings such as this example:

    ```python
    """
    .. include:: ../README.md
    """
    ```

- [ ] Move advanced README.md sections into documentation within the project.
- [ ] Add docstrings to all public functions
- [ ] Add usage examples

---

## Phase 6: Release

### 6.1 Pre-release Checklist

- [x] All tests pass
- [x] Documentation updated
- [x] Version bumped to 0.4.0
- [x] Git tag created

### 6.2 Release Notes

**v0.4.0 - Major Restructuring**

**Breaking Changes**:
- Moved root-level modules to `supernote.notebook.*`
- Renamed `cmds` to `cli`
- Changed import paths (see MIGRATION.md)

**New Features**:
- Optional dependencies via extras (`[cloud]`, `[server]`, `[all]`)
- Clean public API in `supernote.__init__`
- Separate `supernote-server` CLI entry point

**Improvements**:
- Clear module boundaries
- Better documentation
- Easier to use as library

---

## Future Considerations

### Option A: Docker Container
If you go the Docker route:
- Create `Dockerfile` in repo root
- Add `docker-compose.yml` for easy deployment
- Server is primary product, library is secondary

### Option B: Home Assistant Component
If you go the HA route:
- Extract server logic to reusable classes
- Create separate `custom_components/supernote/` repo
- Use `supernote` as library dependency
- Server becomes reference implementation

### Option C: Separate Packages (Later)
If you eventually split:
- `supernote-core` - Notebook parsing
- `supernote-cloud` - Cloud client
- `supernote-server` - Server application
- Current structure makes this easy

---

## Implementation Checklist

### Phase 1: Foundation (Day 1)
- [ ] Fix version mismatch
- [ ] Update README.md
- [ ] Update `pyproject.toml` dependencies
- [ ] Review `.gitignore`

### Phase 2: Restructure (Day 1-2)
- [ ] Create new directories
- [ ] Move files with `git mv`
- [ ] Create `__init__.py` files
- [ ] Update all internal imports
- [ ] Update test imports

### Phase 3: API (Day 2)
- [ ] Define public API in `__init__.py` files
- [ ] Reorganize CLI into separate modules
- [ ] Update entry points in `pyproject.toml`

### Phase 4: Testing (Day 2-3)
- [ ] All existing tests pass
- [ ] Add new import tests
- [ ] Test CLI commands
- [ ] Integration testing

### Phase 5: Documentation (Day 3)
- [ ] Update README.md
- [ ] Add API documentation
- [ ] Update server docs

### Phase 6: Release (Day 3)
- [ ] Final testing
- [ ] Create git tag
- [ ] Release v0.4.0

---

## Success Criteria

✅ **Clean structure**: Clear separation of notebook/cloud/server
✅ **Public API**: Easy to import and use as library
✅ **Server-first**: Optimized for Docker deployment
✅ **Developer-friendly**: Good reference for custom implementations
✅ **Future-proof**: Easy to split OR convert to HA component
✅ **All tests pass**: No regressions
✅ **Documentation**: Clear usage examples

---

## Notes

- This is an **aggressive refactoring** - expect breaking changes
- Target users are **server operators** and **developers**
- Keep **modular monolith** structure for flexibility
- Decision on Docker vs HA can be made later
- Structure supports both paths equally well
