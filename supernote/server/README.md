# Supernote Private Cloud Server

This package provides a self-hosted implementation of the Supernote Cloud server.

## Getting Started

### Prerequisites
- A Supernote device (A5 X, A6 X, Nomad, etc.)
- A computer running this server (accessible on your local network)

### Running the Server

You can start the server using the `supernote-tool` CLI:

```bash
# Default port is 19072
supernote-tool serve
```

To configure the port or host, use environment variables:

```bash
export SUPERNOTE_PORT=8080
export SUPERNOTE_HOST=0.0.0.0
supernote-tool serve
```

### Connecting Your Device

1.  Ensure your Supernote device and computer are on the same Wi-Fi network.
2.  On your Supernote device, go to **Settings** > **Sync** > **Supernote Cloud**.
3.  Select **Private Cloud** (if available) or look for a custom server setting.
    *   *Note: The exact location of this setting may vary by firmware version. Refer to the [official Private Cloud setup guide](https://support.supernote.com/Whats-New/setting-up-your-own-supernote-private-cloud-beta).*
4.  Enter your computer's IP address and the port (default `19072`).
    *   Example: `http://192.168.1.100:19072`
5.  Attempt to Sync or Login.

### Debugging & Tracing

The server logs all incoming requests to `server_trace.log` in the current directory. This is useful for reverse-engineering the protocol and debugging connection issues.

```bash
tail -f server_trace.log
```

## Development

The server is built using `aiohttp`.

-   **Entry Point**: `supernote/server/app.py`
-   **Configuration**: `supernote/server/config.py`
-   **Tests**: `tests/server/`
