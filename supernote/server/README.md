# Supernote Private Cloud Server

This package provides a self-hosted implementation of the Supernote Cloud server.

## Getting Started

### Prerequisites

- A Supernote device (A5 X, A6 X, Nomad, etc.)
- A computer running this server (accessible on your local network)

### Managing User Accounts

You must create a private cloud user account in order to login to the
device.

Use the CLI tool to add, list, or deactivate users:

```sh
supernote-server user add alice
```

You will be prompted for a password, which will be securely hashed using SHA256 and stored in `config/users.yaml`.

To list users:

```sh
supernote-server user list
```

To deactivate a user:

```sh
supernote-server user deactivate alice
```

#### Notes

- Only users listed in this file can log in.
- Passwords are never stored in plain text—only SHA256 hashes (see PLAN.md for security notes).
- Set `is_active: false` to disable a user without deleting their entry.

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

#### Security Configuration

For production deployments, configure JWT authentication:

```bash
# Generate a secure random secret (recommended)
export SUPERNOTE_JWT_SECRET=$(openssl rand -hex 32)

# Configure token expiration (default: 24 hours)
export SUPERNOTE_JWT_EXPIRATION_HOURS=24

supernote-server serve
```

**Important**: Always set a unique `SUPERNOTE_JWT_SECRET` in production to prevent unauthorized access.

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

For coding standards and contribution guidelines, see [CONTRIBUTING.md](docs/CONTRIBUTING.md).
