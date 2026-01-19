# Contributing to Supernote-Lite

This package is designed for:
1. **Server operators** - Self-hosting Supernote Private Cloud
2. **Developers** - Integrating Supernote into applications
3. **Reference** - Understanding Supernote protocols

Thank you for your interest in contributing to Supernote-Lite! This document outlines the setup, architecture, and standards used in this project.

## Code Style & Standards

### Testing

This project uses `pytest` and `pytest-asyncio` for testing. We are migrating away from `unittest`.

-   **Framework**: Use `pytest`.
-   **Async**: We use async auto mode so no need to use `@pytest.mark.
-   **Fixtures**: Use `pytest` fixtures for setup/teardown. Common fixtures are defined in `tests/conftest.py` rather than repeating them in each test file.
-   **Structure**:
    -   **Model Tests**: Unit tests for data models (serialization/deserialization) should be separate from API tests.
    -   **API Tests**: Functional tests for endpoints using `aiohttp.test_utils`.
-   **Test Data**:
    -   Do not hardcode large JSON blobs in test files.
    -   Store test data in `tests/data/` as JSON files.
    -   Load strictly typed objects from JSON in tests.

### Typing & Data Models

-   **Dataclasses**: Use standard Python `dataclasses`.
-   **Serialization**: Use `mashumaro.DataClassJSONMixin` for JSON serialization/deserialization.
-   **Strictness**: Define explicit types for all DTOs (Data Transfer Objects) in `supernote/server/models/` to handle request parsing.
-   **Naming**: Match the naming conventions of the external API where possible (snake_case vs camelCase is handled by configuration in Mashumaro).

### Server Architecture

The server is built with `aiohttp`.

-   **Routes**: `supernote/server/routes/`
    -   Keep route handlers thin. They should parse the request, call a service, and return a typed response.
-   **Services**: `supernote/server/services/`
    -   Contain the business logic.
    -   Should be independent of the HTTP layer where possible.
-   **Dependency Injection**:
    -   Services are injected into route handlers. Avoid global state.

### Code Organization

-   **Imports**: Use absolute imports `from supernote...`.
-   **Async**: All I/O operations (file, network) must be non-blocking.

## Local Development Setup

We use standard scripts in the `script/` directory to manage the development environment, following the "Scripts to Rule Them All" pattern.

### Environment Setup

To set up your development environment, run:

```bash
./script/bootstrap
```

This script will:
1. Initialize a virtual environment using `uv`.
2. Install all core and optional dependencies (`.[all]`).
3. Install developer-specific dependencies (`requirements_dev.txt`).
4. Install `pre-commit` hooks.

### Standard Scripts

| Script | Purpose |
| :--- | :--- |
| `script/bootstrap` | Initial environment setup and dependency installation. |
| `script/setup` | Setup the project and help with venv activation. |
| `script/update` | Pulls latest changes and re-runs bootstrap. |
| `script/test` | Runs the full test suite using `pytest`. |
| `script/lint` | Runs linters and style checks via `pre-commit`. |
| `script/server` | Starts an ephemeral development server. |

## Running Tests

You can run the tests using the standard script:

```bash
./script/test
```

Or manually:

```bash
pytest
```

## Development Workflow

### Running an Ephemeral Server

For rapid development and testing, you can run an ephemeral server. This server starts with a clean state, a random port, and a pre-configured debug user. It is destroyed when the process exits.

**Basic Usage:**

```bash
python3 -m supernote.cli.main serve --ephemeral
```

**With Gemini API Support:**

To enable OCR and AI features during development, set the `SUPERNOTE_GEMINI_API_KEY` environment variable:

```bash
export SUPERNOTE_GEMINI_API_KEY="your_api_key_here"
supernote serve --ephemeral
```

The server startup log will display the temporary storage directory and the default credentials.

**Example Output:**

```text
Using ephemeral mode with storage directory: /var/folders/.../supernote-ephemeral-xyz
Created default user: debug@example.com / password
Run command to login:
  supernote cloud login --url http://127.0.0.1:8080 debug@example.com --password password
```

### Uploading Files

You can use the CLI to upload`.note` files to your running server.

```bash
# Login using the command provided in the ephemeral server output
supernote cloud login --url http://127.0.0.1:8080 debug@example.com --password password

# Upload a file
supernote cloud upload tests/testdata/20251207_221454.note
```
