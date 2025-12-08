# Contributing to Supernote-Lite

Thank you for your interest in contributing to Supernote-Lite! This document outlines the coding standards and conventions used in this project.

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

## Enabling virtual environment

We use `uv` to manage virtual environments. To create a virtual environment:

```bash
uv venv --python=3.14
uv sync  # Install dependencies
```

## Running Tests

Load the virtual environment:
```bash
source .venv/bin/activate
```

Run tests:

```bash
pytest
```
