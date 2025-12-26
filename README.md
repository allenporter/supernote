# supernote

All-in-one toolkit for Supernote devices: parse notebooks, self host, and access services.

This content is shared between the [documentation](https://allenporter.github.io/supernote-lite/) and github repository at [github.com/allenporter/supernote-lite](https://github.com/allenporter/supernote-lite).

## Features

- **Notebook Parsing**: Convert `.note` files to PDF, PNG, SVG, or text
- **Private Server**: Self-hosted Supernote Private Cloud implementation
- **Client**: Interact with Supernote service API

## Installation

```bash

# Install specific components
pip install supernote              # Notebook parsing only
pip install supernote[server]      # + Private server
pip install supernote[client]      # + Client

# Full installation (recommended for server users)
pip install supernote[all]
```

## Local Development

Install in a virtual environment:

```bash
uv venv --python=3.14
source .venv/bin/activate
uv pip install -r requirements_dev.txt
uv pip install -e ".[all]"
```

## Quick Start

### Parse a Notebook

```python
from supernote.notebook import parse_notebook

notebook = parse_notebook("mynote.note")
notebook.to_pdf("output.pdf")
```

The notebook parser is a fork and slightly lighter dependency version of [supernote-tool](https://github.com/jya-dev/supernote-tool) that drops svg dependencies not found in some containers. Generally, you should probably prefer to use that original library unless there is a specific reason you're also having a similar dependency
limitation. All credit goes to the original authors of [supernote-tool](https://github.com/jya-dev/supernote-tool) for providing an amazing low level utility.


### Run Private Server

```bash
# Generate configuration
supernote-server config init > config.yaml

# Generate users (outputs YAML, append to users.yaml)
supernote-server user add alice >> users.yaml

# Start server
supernote-server serve
```

### Run with Docker

```bash
# Build image
docker build -t supernote-server .

# Generate initial configuration
mkdir config
docker run --rm supernote-server supernote-server config init > config/config.yaml
docker run --rm -it supernote-server supernote-server user add alice >> config/users.yaml

# Run server
docker run -d -p 8080:8080 \
  -v $(pwd)/config:/config \
  -v $(pwd)/storage:/data \
  supernote-server
```

See [Server Documentation](supernote/server/README.md) for details.


### Access Supernote Services

```python

from supernote.client import SupernoteClient

async with SupernoteClient.from_credentials(email, password) as client:
    files = await client.list_files()
```


## CLI Usage

```bash
# Notebook operations
supernote convert input.note output.pdf
supernote analyze input.note

# Server operations
supernote-server serve
supernote-server user add alice


# Client operations
supernote client login
supernote client ls
```

## Development

This package is designed for:
1. **Server operators** - Self-hosting Supernote Private Cloud
2. **Developers** - Integrating Supernote into applications
3. **Reference** - Understanding Supernote protocols

See [ARCHITECTURE.md](supernote/server/ARCHITECTURE.md) for protocol details.

### Setup

```bash
uv venv --python=3.14
source .venv/bin/activate
uv pip install -r requirements_dev.txt
uv pip install -e ".[all]"
```

## Credits

The `supernote` library is a fork and slightly lighter dependency version of [supernote-tool](https://github.com/jya-dev/supernote-tool) that drops svg dependencies not found in some containers. Generally, you should probably prefer to use that library unless there is a specific reason you're also having a similar dependency limitation.

## Acknowledgments

This project is in support of the amazing [Ratta Supernote](https://supernote.com/) product and community. This project aims to be a complementary, unofficial offering that is compatible with the [Private Cloud feature](https://support.supernote.com/Whats-New/setting-up-your-own-supernote-private-cloud-beta), helping to support their open ecosystem, helping to reduce load on their servers etc (e.g. for AI
powered personal assistant integrations that need to process notebooks, etc)

### Comparison with Official Private Cloud

Ratta offers an [official Private Cloud solution](https://support.supernote.com/Whats-New/setting-up-your-own-supernote-private-cloud-beta) based on Docker. You
should generally prefer that solution, unless you are interested in lower level
integrations and are comfortable managing your own security, SSL, etc.

Here is how this project compares:

| Feature | Official Private Cloud | Supernote-Lite (This Project) |
|---------|------------------------|-------------------------------|
| **Type** | Official Product | Community Project |
| **Technology** | Docker Container (Java/Spring) | Python Package |
| **Source** | Closed Source | Open Source |
| **Focus** | Stability & End-Users | Hackability & Developers |
| **Requirements** | Docker Environment | Python 3.10+ |
| **Extensibility** | Low (Black Box) | High (Modular Codebase) |
| **Security/SSL** | Documented Guides Included | DIY (Bring Your Own Proxy) |

**Use the Official Private Cloud if:**
- You want a supported, "set-and-forget" solution.
- You prefer using Docker containers.

**Use Supernote-Lite if:**
- You want to understand how the protocol works.
- You want to run on low-power hardware without Docker overhead.
- You want to integrate Supernote sync into your own Python applications.
- You want to customize the server behavior.

### Community Projects

- [github.com/jya-dev/supernote-tool](https://github.com/jya-dev/supernote-tool) - Unofficial python tool for Ratta Supernote for parsing notebook files, which this projects notebook module is based on.
- [github.com/philips/supernote-typescript](https://github.com/philips/supernote-typescript) - Supernote file-format support in typescript
- [github.com/julianprester/sncloud](https://github.com/julianprester/sncloud) - Supernote Cloud API for Python
- [github.com/fharper/awesome-supernote](https://github.com/fharper/awesome-supernote) - A curated list of Supernote resources
- [github.com/philips/supernote-obsidian-plugin](https://github.com/philips/supernote-obsidian-plugin) - Obsidian plugin for Supernote
- [github.com/jbchouinard/supernote-sync](https://github.com/jbchouinard/supernote-sync) - Tool to automatically backup files from the Supernote using local WiFi using the Supernote Browse & Access feature
- [github.com/theburningbush/snbackup](https://github.com/theburningbush/snbackup) - CLI tool for wireless Supernote backups using the Browse & Access feature
- [github.com/dsummersl/sn2md](https://github.com/dsummersl/sn2md) - Supernote to text/image converter (sn2md)
- [github.com/calebc42/eink-template-gen](https://github.com/calebc42/eink-template-gen) - Generates pixel-perfect page templates for e-ink devices.
