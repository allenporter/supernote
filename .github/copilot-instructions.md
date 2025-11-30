# Supernote Lite AI Instructions

## Project Overview
`supernote-lite` is a Python library for parsing and converting Ratta Supernote `.note` files, interacting with the Supernote Cloud API, and hosting a private Supernote Cloud server. It is a fork of `supernote-tool` with lighter dependencies.

## Architecture
- **Core (`supernote/`)**:
  - `parser.py`: Parses binary `.note` files into `SupernoteMetadata`.
  - `fileformat.py`: Defines file structure constants and metadata classes.
  - `converter.py`: Converts parsed data to PNG, SVG, PDF, TXT.
  - `decoder.py`: Decodes binary layer data.
- **Cloud (`supernote/cloud/`)**:
  - `client.py`: Async HTTP client using `aiohttp`.
  - `api_model.py`: Data models using `mashumaro` for JSON serialization.
  - `auth.py`: Authentication strategies (`AbstractAuth`, `FileCacheAuth`).
- **Server (`supernote/server/`)**:
  - **Protocol**: Implements the Supernote Cloud protocol (see `supernote/server/ARCHITECTURE.md`).
  - **Goal**: Provide a self-hosted alternative to the official cloud.
- **CLI (`supernote/cmds/`)**:
  - `supernote_tool.py`: Main entry point (`supernote-tool`).

## Development Workflow
- **Environment**: Managed with `uv`.
  ```bash
  uv venv --python=3.14
  source .venv/bin/activate
  uv pip install -r requirements_dev.txt
  ```
- **Type Checking**: Run `script/run-mypy.sh` to check types.
- **Testing**: Run `pytest` to execute tests in `tests/`.
  - **Mocking**: Use `unittest.mock.patch` instead of `monkeypatch`.
  - **Typing**: Ensure all test functions and fixtures have strict type hints.

## Coding Conventions
- **Async/Await**: Use `async`/`await` for all cloud API interactions.
- **Data Models**: Use `mashumaro`'s `DataClassJSONMixin` for API request/response models.
  - Example: `@dataclass class MyResponse(DataClassJSONMixin): ...`
- **Type Hinting**: Use strict type hints. Use `typing.Protocol` for interfaces.
- **Binary Parsing**: Use `parser.py` patterns for reading binary streams (seek/read).
- **Logging**: Use `logging.getLogger(__name__)`.
- **Server Implementation**:
  - Follow the protocol definitions in `supernote/server/ARCHITECTURE.md`.
  - Use `mashumaro` for server-side data models (DTOs/VOs) to match the client.

## Key Files
- `supernote/parser.py`: Entry point for parsing logic.
- `supernote/cloud/client.py`: Core API client logic.
- `supernote/cloud/api_model.py`: API data definitions.
- `supernote/server/ARCHITECTURE.md`: Documentation of the server protocol and architecture.
- `pyproject.toml`: Project configuration and dependencies.
