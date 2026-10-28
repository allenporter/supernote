# Supernote Private Cloud & Knowledge Hub

**A lightweight, self-hosted private cloud server and optional AI intelligence layer for your Ratta Supernote.**

This toolkit is a self-hosted, SQLite-based implementation of the **Supernote Private Cloud** protocol. It provides a simple and resource-efficient sync server with a minimal resource footprint (~135MB flat in bare sync mode, or ~160MB idle and ~310MB peak when rendering and processing large notebooks). It implements **100% of the community [Supernote OpenAPI Specification](api-spec/openapi.yaml)**, and can optionally be enhanced with an **AI-driven synthesis engine**—transforming your handwritten notes into structured, searchable knowledge using Google Gemini or local OpenAI-compatible models (such as Ollama).

<p align="center">
  <img src="docs/static-assets/hero-overview.jpg" alt="Supernote Overview" width="800">
</p>

[![Documentation](https://img.shields.io/badge/docs-manual-blue.svg)](https://allenporter.github.io/supernote/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

## Why Supernote Private Cloud & Knowledge Hub?

This project is designed to be **fully compatible** with the official Supernote Private Cloud protocol, serving as a lightweight alternative that operates on a single SQLite database and runs comfortably on low-power NAS setups and home lab servers:

- **⚡ Lightweight Sync**: Runs on a simple, efficient Python/Asyncio stack with SQLite. Consumes ~135MB in bare sync mode, or ~160MB idle (~310MB peak) with the Web UI, MCP server, and background notebook processing enabled.
- **📋 OpenAPI Spec Compliant**: Implements **100% of the community [Supernote OpenAPI specification](api-spec/openapi.yaml)**.
- **🛡️ Private & Secure**: You own your database and files. Runs locally on your NAS or local server with no external data leakage.
- **🖥️ Sleek Web UI**: Browse notes, manage tasks, and export iCalendar (`.ics`) task feeds for Home Assistant, Apple Calendar, Google Calendar, and Outlook.
- **📜 Optional AI Synthesis**: When configured with an AI provider (Google Gemini or a local OpenAI-compatible model such as Ollama), it automatically transcribes handwriting and generates summaries (Daily, Weekly, Monthly).
- **🔍 Optional Semantic Search**: Vectorizes content for concept-based search across all notebooks.
- **🤖 Agent Ready (MCP)**: Securely connect your notes to AI agents (Claude, Gemini, ChatGPT) via the built-in [Model Context Protocol](https://modelcontextprotocol.io/) server.

## Synthesis & AI in Action

Beyond simple storage, Supernote provides an active processing pipeline to increase the utility of your notes:

1.  **Sync**: Your device uploads `.note` files using the official Private Cloud protocol.
2.  **Transcribe**: The server extracts pages and uses a vision model (Gemini or local VLM) to OCR your handwriting.
3.  **Synthesize**: AI Analyzers review your journals to find tasks, themes, and summaries.
4.  **Index**: Every word is vectorized, enabling semantic search across your entire library.

### Web Interface

The integrated frontend allows you to review your notes, manage task lists, and view AI insights side-by-side.

<p align="center">
  <img src="docs/static-assets/note-synthesis-1.jpg" alt="Note Synthesis View" width="400">
  <img src="docs/static-assets/note-synthesis-2.jpg" alt="Notebook Explorer" width="400">
</p>

<p align="center">
  <img src="docs/static-assets/tasks-dashboard.png" alt="Tasks & Schedule Dashboard" width="800">
</p>

## Quick Start

You can run the server either as a **Lite Sync Server (Zero-Config)** or with the **AI & Semantic Search features enabled**.

### 1. Launch the Server

Choose one of the options below to start the server.

#### Option A: Lite Sync Server (Zero-Config)
No API keys or external services required. Runs locally with SQLite (~160MB idle, ~310MB peak when rendering notebook previews).

*   **Using Python**:
    ```bash
    pip install "supernote[server]"
    supernote serve
    ```
*   **Using Docker**:
    ```bash
    # Build the docker image locally
    docker build -t supernote .

    # Run the container (maps the local storage/ folder to the container's /data volume)
    docker run -d \
      -p 8080:8080 \
      -v $(pwd)/storage:/data \
      --name supernote-server \
      supernote
    ```
*   **Bare Sync Mode (~135MB flat RAM)**: To run a minimal headless sync server without the Web UI, background PNG rasterization, or MCP server, disable `web_enabled` and `mcp_enabled` via environment variables or `config.yaml`:
    ```bash
    SUPERNOTE_MCP_ENABLED=false SUPERNOTE_WEB_ENABLED=false supernote serve
    ```
    ```yaml
    # config/config.yaml
    mcp_enabled: false
    web_enabled: false
    ```

#### Option B: AI & Knowledge Hub (With Gemini)
Enables handwriting transcription, summarization, and semantic search. Requires a Google Gemini API Key.

*   **Using Python**:
    ```bash
    export SUPERNOTE_GEMINI_API_KEY="your-gemini-api-key"
    pip install "supernote[all]"
    supernote serve
    ```
*   **Using Docker**:
    ```bash
    # Build the docker image locally
    docker build -t supernote .

    # Run the container with your Gemini API key
    docker run -d \
      -p 8080:8080 \
      -v $(pwd)/storage:/data \
      -e SUPERNOTE_GEMINI_API_KEY="your-gemini-api-key" \
      --name supernote-server \
      supernote
    ```

#### Option C: AI & Knowledge Hub (With a Local Model)
Runs the same features against a model server on your own hardware, such as [Ollama](https://ollama.com/), llama.cpp, vLLM or LM Studio, so your notes never leave your network. You need a vision-capable chat model for OCR and summaries, and an embedding model for search. Configure the `openai` provider in `config/config.yaml` (`/data/config/config.yaml` in Docker) as described in the [server AI configuration](supernote/server/README.md#ai-configuration).

When the server runs in Docker and Ollama runs on the host, use `http://host.docker.internal:11434/v1` as the `base_url` (on Linux, also pass `--add-host=host.docker.internal:host-gateway`).

### 2. Bootstrap Your User

Once the server is running, register your administrator account:

*   **Using Python CLI**:
    ```bash
    # Create the initial admin account
    supernote admin --url http://localhost:8080 user add you@example.com

    # Authenticate your CLI
    supernote cloud login you@example.com --url http://localhost:8080
    ```
*   **Using Docker CLI**:
    ```bash
    # Create the initial admin account
    docker exec -it supernote-server supernote admin --url http://localhost:8080 user add you@example.com
    ```

### 3. Connect Your Device

1. On your Supernote, go to **Settings > Sync > Private Cloud**.
2. Enter your server URL (e.g., `http://192.168.1.5:8080`).
3. Log in with the email and password you created in Step 2.
4. Tap **Sync** to begin syncing your notes.

### 4. Explore Your Insights

Once your notes sync and process, you can view the AI synthesis from the terminal or browser:

```bash
# Get a high-level summary and transcription
supernote cloud insights /Notes/NOTE/Journal.note

# Semantic search across all notebooks
supernote cloud search "What were my project goals for February?"
```

<p align="center">
  <img src="docs/static-assets/cli-insights.jpg" alt="CLI AI Insights" width="700">
</p>

You can access the insights from the MCP server at `http://<your ip:port>/mcp`

> [!TIP]
> **Semantic Search**: Supernote doesn't just look for words—it understands concepts. Searching for "budget" will find notes about "expenses" or "money," even if the specific word isn't there.

## Features Deep Dive

- **Official Protocol Compatibility**: Implements the official **Supernote Private Cloud** protocol for seamless device synchronization. While Ratta's official service provides a robust and managed sync experience, this project allows for local data ownership and custom background processing.
- **Notebook Parsing**: Native, high-fidelity conversion of `.note` files to PDF, PNG, SVG, or plain text.
- **Developer API**: Modern `asyncio` client to build your own automation around Supernote data.
- **iCalendar Feed Export (.ics)**: Preview, copy, and download task feeds in RFC 5545 VTODO `.ics` format for Home Assistant, Apple Calendar, Google Calendar, and Outlook.
- **Observability**: Built-in request tracing and background task monitoring.

<p align="center">
  <img src="docs/static-assets/admin-processing-status.jpg" alt="Admin Task Monitor" width="450">
  <img src="docs/static-assets/mobile-friendly.jpg" alt="Mobile View" width="250">
</p>

## Installation

```bash
# Install specific components
pip install supernote              # Notebook parsing only
pip install supernote[server]      # + Private server & AI features
pip install supernote[client]      # + API Client

# Full installation (recommended for server users)
pip install supernote[all]
```

## Local Development Setup

To set up the project for development, please refer to the [Contributing Guide](docs/CONTRIBUTING.md).

## CLI Usage

```bash
# Server & Admin
supernote serve                      # Start the cloud
supernote admin user list           # Manage your users

# AI Synthesis & Insights
supernote cloud insights /Note.note # View synthesis from CLI

# File Operations
supernote cloud ls /                # List remote files
supernote cloud download /Note.note # Download to local machine
```

## Notebook Operations & Developer API

You can use the built-in notebook parser or async client directly in your own Python applications:

```python
from pathlib import Path
from supernote.notebook import PdfConverter, load_notebook

note = load_notebook("journal.note")
pdf_bytes = PdfConverter(note).convert(-1)  # Multi-page PDF conversion
Path("journal.pdf").write_bytes(pdf_bytes)
```

```python
from supernote.client import Supernote

async with await Supernote.login("user@example.com", "password", host="http://localhost:8080") as sn:
    files = await sn.device.list_folder("/")
```

The notebook parser originally started as a fork of [supernote-tool](https://github.com/jya-dev/supernote-tool) with lighter dependencies and modern type hints. All credit goes to the original authors for providing the foundational parser utility.

## Customizing AI Prompts

You can customize the prompts used for Gemini OCR (transcription) and Summarization by pointing the server to a custom prompts directory.

### 1. Configuration
Set the custom prompts directory using either:
*   **Environment Variable**:
    ```bash
    export SUPERNOTE_PROMPTS_DIR="path/to/your/prompts"
    ```
*   **Config File (`config.yaml`)**:
    ```yaml
    prompts_dir: "path/to/your/prompts"
    ```

### 2. Directory Structure
The custom prompts directory should mirror the structure of the default prompts:
```text
my-prompts/
├── ocr/                     # Prompt templates for handwriting OCR
│   ├── common/              # Appended to all OCR requests
│   │   └── legend.md
│   ├── default/             # Fallback default OCR prompt
│   │   └── system.md
│   └── daily/               # Custom OCR prompt for "daily" notebooks
│       └── prompt.md
└── summary/                 # Prompt templates for summaries
    ├── common/              # Appended to all summary requests
    │   └── instruction.md
    ├── default/             # Fallback default summary prompt
    │   └── prompt.md
    └── daily/               # Custom summary prompt for "daily" notebooks
        └── prompt.md
```

### 3. Filename-Based Prompt Routing
The server dynamically routes prompts based on the notebook's file name:
1.  When a notebook (e.g., `Daily.note` or `Weekly_Review.note`) is synced, the lowercased stem of the filename is extracted (`daily` or `weekly_review`).
2.  The server looks under the `ocr/` and `summary/` directories for a subfolder matching that stem (e.g., `daily/` or `weekly_review/`).
3.  If found, the templates inside that custom folder are loaded. If not found, it falls back to the `default/` templates.
4.  Templates found in the `common/` folder are always concatenated first.

### 4. Vocabulary
OCR prompts also list the names and terms a person uses, so that a handwritten
word that closely matches one is spelled the way they spell it. The model is
told never to insert a listed term the handwriting does not support.

*   **Harvested automatically**: keywords added to a notebook on the device are
    added for the top folder it is in (`Note/Work` for a notebook in
    `Note/Work/Weeks`). Common words, keywords without letters, and keywords
    longer than four words are skipped.
*   **Added by hand**: `POST /api/extended/vocabulary/add` with
    `{"terms": [...], "scopeId": 0}`. `scopeId` is a folder or notebook ID, or
    `0` for every notebook.
*   **Moved**: `POST /api/extended/vocabulary/move` with `{"id": ..., "scopeId": ...}`
    applies a term somewhere else; it becomes the user's own term.
*   **Removed**: `POST /api/extended/vocabulary/delete` with `{"id": ...}`. A
    removed harvested term is not harvested again, and can be brought back with
    `POST /api/extended/vocabulary/restore`.
*   **Listed**: `POST /api/extended/vocabulary/list`, with
    `{"includeSuppressed": true}` to include removed harvested terms.

A notebook's prompt uses the terms scoped to it, to each folder above it, and to
every notebook, nearest first, up to 200 terms.

## Contributing

We welcome contributions! Please see our [Contributing Guide](docs/CONTRIBUTING.md) for details on:
- Local development setup
- Project architecture
- Using **Ephemeral Mode** for fast testing
- AI Skills for agentic interaction

## Acknowledgments

This project is in support of the amazing [Ratta Supernote](https://supernote.com/) product and community. It aims to be a complementary, unofficial offering that is fully compatible with the official [Private Cloud protocol](https://support.supernote.com/Whats-New/setting-up-your-own-supernote-private-cloud-beta).

### Choosing Your Private Cloud Experience

While the official Supernote Private Cloud by Ratta provides a production-grade managed sync experience, this toolkit offers a highly efficient self-hosted alternative with opt-in AI enhancement.

| Capability | Official Private Cloud (Ratta) | Supernote Private Cloud (This Project) |
|------------|-------------------------------|-----------------------------|
| **Core Sync** | ✅ Robust & Validated | ✅ Fully Compatible (100% OpenAPI compliant) |
| **Memory Footprint**| ⚠️ High (~2 GB+ RAM required) | **⚡ Low (~135MB bare sync, ~160MB idle / ~310MB active full)** |
| **AI Analysis** | Basic OCR (Device-side) | **Optional: AI-powered Transcriptions & Synthesis (Gemini or Local Models)** |
| **Search** | Path/Filename | **Optional: Semantic Concept Search** |
| **Stack** | Java / Spring Boot + Redis + MariaDB | Python / Asyncio + SQLite |
| **Database** | Heavy MariaDB Instance | **Single SQLite File** |

**This toolkit is a great fit if:**
- You want a **lightweight, resource-friendly** private cloud that runs easily on a basic NAS or low-power server.
- You want **100% compliance** with the local OpenAPI sync protocols.
- You want **AI-generated summaries** and insights from your notebooks (optional).
- You want to perform **semantic searches** across your entire handwriting library (optional).
- You want to integrate your notes into local scripts via a Python API or CLI.
- You want to use the **Model Context Protocol (MCP)** to [chat with your notes](docs/mcp.md) using AI agents.

## Community Projects

- [jya-dev/supernote-tool](https://github.com/jya-dev/supernote-tool) - Original parser foundation.
- [awesome-supernote](https://github.com/fharper/awesome-supernote) - Curated resource list.
- [sn2md](https://github.com/dsummersl/sn2md) - Supernote to text/image converter.
