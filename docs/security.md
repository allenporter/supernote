# Lite Server Security Architecture

This document outlines the security architecture, design decisions, accepted risks, and mitigation strategies for the Lite Private Cloud server.

## Overview

The system is designed to provide a secure, self-hosted environment for syncing Supernote devices. It prioritizes hardware compatibility with existing devices while implementing security controls for the server component.

## Authentication

### User Credentials
- **Password Storage**: Passwords are stored as MD5 hashes.
    - **Risk**: MD5 is considered cryptographically broken for collision resistance.
    - **Mitigation/Rationale**: This is an **ACCEPTED RISK**. The Supernote device firmware transmits MD5 hashes of passwords. To maintain compatibility with existing hardware clients, the server must store and verify these hashes. We mitigate this by assuming the server is run in a trusted private environment and has secure communication channels.
- **Login Challenge**: The login flow uses a challenge-response mechanism (Salted SHA256 of the stored MD5 + Random Code) to prevent replay attacks during the authentication handshake.

### Session Management
- **JWT**: Stateless session management using JSON Web Tokens (HS256).
- **Session Tracking**: While JWTs are stateless, valid sessions are tracked in a `CoordinationService` (backed by the database) to allow for revocation and to limit concurrent sessions per user/device.

## Authorization

- **Role-Based Access**: The system differentiates between `Admin` and `User` roles.
    - **Admin**: Can manage users (create, list, reset passwords). The first user created is automatically granted Admin privileges (Bootstrapping).
    - **User**: Can only access their own files and settings.

## URL Security & Sharing

### Signed URLs
Direct access to files (uploads/downloads) is secured using **Signed URLs**.
- **Mechanism**: URLs are signed with a JWT containing the scope (path), expiration, and a unique nonce.
- **Replay Protection**: The `UrlSigner` enforces **Single-Use Tokens** (Burn-after-reading) for critical operations.
    - **Implementation**: When a URL is signed, a nonce is generated and whitelisted in the `CoordinationService`. Upon verification, the nonce is atomically removed (`pop_value`). If the nonce is missing or already removed, the request is rejected.
    - **Benefit**: Prevents replay attacks where an intercepted signed URL could be reused.

### Log Redaction
- **Trace Logs**: The request tracing middleware automatically redacts sensitive query parameters (`signature`, `token`) from logs to prevent credentials from leaking into log files.

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
