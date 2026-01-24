# supernote

Personal Knowledge Management Hub for Supernote: parse notebooks, self-host services, and unlock AI insights.

This content is shared between the [documentation](https://allenporter.github.io/supernote-lite/) and github repository at [github.com/allenporter/supernote-lite](https://github.com/allenporter/supernote-lite).

## Features

- **Notebook Parsing**: Convert `.note` files to PDF, PNG, SVG, or text
- **AI-Powered Insights**: OCR, automated summarization, and key metadata extraction via Gemini API
- **Supernote Private Server**: Self-hosted Supernote Private Cloud with robust background processing
- **Developer API**: Interact with Supernote Cloud and local data through a modern async Python client
- **System Maintenance**: Background polling, auto-recovery for stalled tasks, and storage quota management

## AI & Automation

Supernote-Lite transforms your handwritten notes into structured knowledge. When configured with a Gemini API key, the server automatically:

- **OCR**: Transcribes handwriting with high accuracy.
- **Summarization**: Generates concise summaries of your note journals.
- **Entity Extraction**: Identifies dates, tasks, and key themes.
- **Retrieval Support**: Chunks and indexes notes for efficient search (Experimental).

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

## Quick Start

### Start the AI-Powered Server

1. **Bootstrap with Gemini**:
   ```bash
   export SUPERNOTE_GEMINI_API_KEY="your-api-key"
   supernote serve
   ```

2. **Register & Login**:
   ```bash
   # Add your first user (System Admin)
   supernote admin --url http://localhost:8080 user add email@example.com

   # Login via CLI
   supernote cloud login email@example.com --url http://localhost:8080
   supernote cloud ls
   ```

See the [Bootstrap Guide](docs/bootstrap_guide.md) for detailed deployment and security instructions.

### Parse a Notebook

```python
from supernote.notebook import parse_notebook

notebook = parse_notebook("mynote.note")
notebook.to_pdf("output.pdf")
```

The notebook parser is a fork and slightly lighter dependency version of [supernote-tool](https://github.com/jya-dev/supernote-tool). All credit goes to the original authors for providing an amazing low-level utility.

### Run with Docker

```bash
# Build & Run server
docker build -t supernote .
docker run -d -p 8080:8080 -v $(pwd)/storage:/storage supernote serve
```

See [Server Documentation](https://github.com/allenporter/supernote-lite/blob/main/supernote/server/README.md) for details.

### Developer API

Integrate Supernote into your own Python applications:

```python
from supernote.client import Supernote
# See library docstrings for usage examples
```


## CLI Usage

```bash
# Server & Admin
supernote serve
supernote admin user list

# Notebook operations
supernote notebook convert input.note output.pdf
supernote notebook analyze input.note

# Cloud operations
supernote cloud login --url http://localhost:8080 email@example.com
supernote cloud ls
```

## Contributing

We welcome contributions! Please see our [Contributing Guide](docs/CONTRIBUTING.md) for details on:
- Local development setup
- Project architecture
- Using **Ephemeral Mode** for fast testing
- AI Skills for agentic interaction

## Acknowledgments

This project is in support of the amazing [Ratta Supernote](https://supernote.com/) product and community. It aims to be a complementary, unofficial offering that is compatible with the [Private Cloud feature](https://support.supernote.com/Whats-New/setting-up-your-own-supernote-private-cloud-beta).

### Comparison with Official Private Cloud

| Feature | Official Private Cloud | Supernote-Lite (This Project) |
|---------|------------------------|-------------------------------|
| **Core AI** | No (Basic Sync) | **Yes** (OCR, Summaries, Insights) |
| **System** | Java / Spring | Python (Asyncio) |
| **Source** | Closed Source | Open Source |
| **Flexibility** | Set-and-forget | High (Developer-friendly, CLI) |
| **Hardware** | Docker Required | Python 3.13+ (Low resource) |
| **Status** | Stable Product | Community Innovation |

**Use the Official Private Cloud if:**
- You want a supported, "set-and-forget" solution.
- You prefer using Docker containers.

**Use Supernote-Lite if:**
- You want **AI insights** and OCR for your notes.
- You want to integrate Supernote data into your local scripts or knowledge workflows.
- You want to run on low-power hardware without Docker overhead.
- You want full control over how your data is processed.

## Community Projects

- [jya-dev/supernote-tool](https://github.com/jya-dev/supernote-tool) - Original parser foundation.
- [awesome-supernote](https://github.com/fharper/awesome-supernote) - Curated resource list.
- [sn2md](https://github.com/dsummersl/sn2md) - Supernote to text/image converter.
