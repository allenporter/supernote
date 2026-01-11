# Supernote Private Cloud Server

This package provides a self-hosted implementation of the Supernote Cloud server.

## Getting Started

### Prerequisites

- A Supernote device (A5 X, A6 X, Nomad, etc.)
- A computer running this server (accessible on your local network)

### Configuration

The server is configured via `config/config.yaml`. Configuration can also be overridden using environment variables.

For a comprehensive reference of all configuration options and their corresponding environment variables, see the [ServerConfig documentation](https://allenporter.github.io/supernote-lite/supernote/server.html#ServerConfig).

Example `config.yaml`:
```yaml
host: 0.0.0.0
port: 8080
storage_dir: storage
auth:
  secret_key: "your-secret-key"
```

### Running the Server

You can start the server using the `supernote-server` CLI:

```bash
# Start the server on port 8080
supernote-server serve
```

To configure the port or host, you can use environment variables (which override `config.yaml`):

```bash
export SUPERNOTE_PORT=8080
export SUPERNOTE_HOST=0.0.0.0
supernote-server serve
```
### Running with Docker

You can run the server using Docker.

1.  **Build the image**:
    ```bash
    ```bash
    docker build -t supernote-server .
    ```

2.  **Create configuration**:
    Create a `config` directory and generate the initial configuration.
    ```bash
    mkdir config
    # Generate default config
    docker run --rm supernote-server supernote-server config init > config/config.yaml
    ```

3.  **Run the container**:
    Mount the `storage` directory to persist data and config.
    ```bash
    docker run -d \
      -p 8080:8080 \
      -v $(pwd)/storage:/data \
      --name supernote-server \
      supernote-server
    ```

### Connecting Your Device

1.  Review the [official Private Cloud setup guide](https://support.supernote.com/Whats-New/setting-up-your-own-supernote-private-cloud-beta) for your firmware version or other pre-requisites. This guide assumes you are familiar
with the technology involved and can configure your own reverse proxy as needed, etc.
2.  Ensure your Supernote device and computer are on the same Wi-Fi network.
3.  On your Supernote device, go to **Settings** > **Sync** > **Supernote Cloud**.
4.  Select **Private Cloud** (if available) or look for a custom server setting.
    *   *Note: The exact location of this setting may vary by firmware version. Refer to the [official Private Cloud setup guide](https://support.supernote.com/Whats-New/setting-up-your-own-supernote-private-cloud-beta).*
5.  Enter your computer's IP address and the port (default `8080`).
    *   Example: `192.168.1.100` and `8080`
6.  Attempt to login using the user account you created.
7.  Go to **Settings** > **Drive** > **Private Cloud** to configure Sync settings including whether or not to automatically sync and which folders to sync (e.g. `EXPORTS`)

### Debugging & Tracing

The server logs all incoming requests to `storage/system/server_trace.log` in the current directory. This is useful for debugging connection issues.

```bash
tail -f storage/system/server_trace.log
```

## Development

The server is built using `aiohttp`.

-   **Entry Point**: `supernote/server/app.py`
-   **Configuration**: `supernote/server/config.py`
-   **Tests**: `tests/server/`

For coding standards and contribution guidelines, see [CONTRIBUTING.md](../docs/CONTRIBUTING.md).
