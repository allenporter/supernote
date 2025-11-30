# Supernote Private Cloud Server

This package provides a self-hosted implementation of the Supernote Cloud server.

## Getting Started

### Prerequisites

- A Supernote device (A5 X, A6 X, Nomad, etc.)
- A computer running this server (accessible on your local network)

### Creating user accounts

You must create a private cloud user account in order to login to the
device. See [USERS.md](USERS.md) for instructions on managing the local
user accounts.

### Running the Server

You can start the server using the `supernote-server` CLI:

```bash
# Start the server on port 8080
supernote-server serve
```


To configure the port or host, use environment variables:

```bash
export SUPERNOTE_PORT=8080
export SUPERNOTE_HOST=0.0.0.0
supernote-server serve
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

The server logs all incoming requests to `server_trace.log` in the current directory. This is useful for reverse-engineering the protocol and debugging connection issues.

```bash
tail -f server_trace.log
```

## Development

The server is built using `aiohttp`.

-   **Entry Point**: `supernote/server/app.py`
-   **Configuration**: `supernote/server/config.py`
-   **Tests**: `tests/server/`
