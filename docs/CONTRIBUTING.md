# Contributing to Supernote-Lite

Supernote-Lite is evolving from a set of utilities into a **Personal Knowledge Management Hub**. We welcome contributions that help realize this vision—whether through better parsing, more robust server features, or new AI-powered insights.

## Code Style & Standards

### Testing

This project uses `pytest` and `pytest-asyncio` for testing.

- **Framework**: Use `pytest`.
- **Async**: We use async auto mode.
- **Fixtures**: Common fixtures are defined in `tests/conftest.py`.
- **Structure**:
    - **Model Tests**: Unit tests for data models (serialization).
    - **API Tests**: Functional tests for endpoints.

### Typing & Data Models

- **Dataclasses**: Use standard Python `dataclasses`.
- **Serialization**: Use `mashumaro`.
- **Strictness**: Define explicit types for all DTOs in `supernote/server/models/`.

### Server Architecture

- **Routes**: `supernote/server/routes/` - keep handlers thin.
- **Services**: `supernote/server/services/` - contain business logic.
- **Dependency Injection**: Services are injected into route handlers.

---

## Local Development Setup

We use standard scripts in the `script/` directory following the "Scripts to Rule Them All" pattern.

### Environment Setup

```bash
./script/bootstrap
```

This script will initialize a virtual environment using `uv`, install dependencies (`.[all]`), and set up `pre-commit` hooks.

### Standard Scripts

| Script | Purpose |
| :--- | :--- |
| `script/bootstrap` | Initial environment setup and dependency installation. |
| `script/setup` | Setup the project and help with venv activation. |
| `script/update` | Pulls latest changes and re-runs bootstrap. |
| `script/test` | Runs the full test suite using `pytest`. |
| `script/lint` | Runs linters and style checks via `pre-commit`. |
| `script/server` | Starts an ephemeral development server. |

---

## Development Workflow

### Ephemeral Mode

For rapid iteration, run an ephemeral server. It starts with a clean state and a pre-configured debug user.

```bash
# Enable AI features for development
export SUPERNOTE_GEMINI_API_KEY="your_api_key"

# Start the ephemeral server
supernote serve --ephemeral
```

The server will print the temporary storage path and login command:
```bash
Created default user: debug@example.com / password
Run command to login:
  supernote cloud login --url http://127.0.0.1:8080 debug@example.com --password password
```

### AI Skills & Agentic Coding

This project includes "AI Skills" to help developers (and AI agents) interact with the codebase effectively. See `.agent/skills` for more details on how we structure these for automated development.

### Uploading Files

Test the sync flow using the CLI:

```bash
# Upload a test file
supernote cloud upload tests/testdata/20251207_221454.note
```
