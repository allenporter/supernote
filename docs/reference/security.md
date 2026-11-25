# Security Architecture — Open Private Cloud for Supernote

This document outlines the security architecture, design decisions, accepted risks, and mitigation strategies for the Open Private Cloud for Supernote server.

## Overview

The system is designed to provide a secure, self-hosted environment for syncing Supernote devices. It prioritizes hardware compatibility with existing devices while implementing security controls for the server component.

## Authentication

### User Credentials
- **Password Storage**: Passwords are stored as MD5 hashes.
    - **Risk**: MD5 is considered cryptographically broken for collision resistance.
    - **Mitigation/Rationale**: This is an **ACCEPTED RISK**. The Supernote device firmware transmits MD5 hashes of passwords. To maintain compatibility with existing hardware clients, the server must store and verify these hashes. We mitigate this by assuming the server is run in a trusted private environment and has secure communication channels.
- **Login Challenge**: The login flow uses a challenge-response mechanism (Salted SHA256 of the stored MD5 + Random Code) to prevent replay attacks during the authentication handshake.

### Session Management & Static API Keys
- **JWT Sessions**: Interactive sessions use JSON Web Tokens (HS256) tracked in `CoordinationService` so sessions can be revoked on logout or password change.
- **OAuth Client Grants**: Every OAuth authorization is recorded in `oauth_grants`, which holds SHA-256 digests of its access and refresh tokens; no plaintext OAuth token is stored. Deleting the grant (`DELETE /api/extended/oauth/grants/{grantId}`, `/revoke` on its refresh token, or a password change or reset) ends both tokens at once. Each user keeps at most 50 grants; the oldest is evicted.
- **Static Bearer API Keys (`sn_<32-hex>`)**: Users can mint named, revocable API keys via `/api/extended/keys` or `supernote cloud keys create` for headless CLI scripts, SDK automation, and MCP agents.
    - **Storage**: Raw API keys are returned only once at creation. The `api_keys` table stores only the SHA-256 digest (`key_hash`), a truncated display prefix (`sn_xxxxxxxx...`), creation/last-used timestamps, and an optional expiration timestamp (`expires_at`).
    - **Transport**: API keys and session tokens are accepted via `Authorization: Bearer <token>` (or `x-access-token`) across REST APIs (`/api/extended/*`, `/api/file/*`, `/api/oss/*`, `/api/user/query`), Socket.IO, and `/mcp`.
    - **Privilege Boundaries (`@interactive_session_only`)**: Static API keys cannot be used to create/list/revoke API keys, list/revoke OAuth client grants, change passwords or emails, unbind hardware devices, authorize OAuth clients (`/login-bridge`), or call `/api/admin/*` endpoints. Password rotation revokes interactive sessions and OAuth client grants without revoking independent API keys; deleting a user cascades and revokes all of their API keys.

## Authorization

- **Role-Based Access**: The system differentiates between `Admin` and `User` roles.
    - **Admin**: Can manage users (create, list, reset passwords) using an interactive admin session. The first user created is automatically granted Admin privileges (Bootstrapping).
    - **User**: Can only access their own files and settings.

## URL Security & Sharing

### Signed URLs
Direct access to files (uploads/downloads) is secured using **Signed URLs**.
- **Mechanism**: URLs are signed with a JWT containing the scope (path), expiration, and a unique nonce.
- **Replay Protection**: The `UrlSigner` enforces **Single-Use Tokens** (Burn-after-reading) for critical operations.
    - **Implementation**: When a URL is signed, a nonce is generated and whitelisted in the `CoordinationService`. Upon verification, the nonce is atomically removed (`pop_value`). If the nonce is missing or already removed, the request is rejected.
    - **Benefit**: Prevents replay attacks where an intercepted signed URL could be reused.

### Log Redaction
- **Trace Logs**: The request tracing middleware automatically redacts sensitive query parameters (`signature`, `token`) and authentication headers (`Authorization`, `x-access-token`) from trace logs to prevent credentials from leaking into log files.

## Data Storage & Integrity

### Blob Storage
- **Content-Addressable Storage (CAS)**: Files are stored on disk using their MD5 hash as the filename.
    - **Risk**: theoretical MD5 collisions could allow a malicious user to overwrite/poison a file if they can generate a collision.
    - **Mitigation/Rationale**: This is an **ACCEPTED RISK**. Generating a valid file collision that is also a valid PDF/Note file is computationally expensive. Given the single-tenant/small-group nature of the private cloud, the risk is deemed low.

## User Management & Registration

### Registration
- **Public Registration**: Disabled by default (`enable_registration: false`).
- **User Creation**: Only the admin (first user) can create additional users via the CLI or Admin API.

### Password Reset
- **Remote Reset (Self-Service)**: The public `/api/official/user/retrieve/password` endpoint is **DISABLED** by default.
    - **Configuration**: Controlled by `SUPERNOTE_ENABLE_REMOTE_PASSWORD_RESET` (env) or `auth.enable_remote_password_reset` (yaml).
    - **Risk**: The legacy protocol allows resetting passwords with just an email/phone, which is insecure for a public endpoint.
    - **Secure Alternative**: Administrators should use the CLI to reset user passwords.

## Administration (CLI)

The `supernote` CLI provides secure administrative functions:

```bash
# Reset a user's password (admin only)
supernote admin user reset-password <email>

# Create a new user
supernote admin user add <email> --name <DisplayName>
```
