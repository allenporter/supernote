# Bootstrap Guide

This guide describes how to set up your Supernote Private Cloud server for the first time, including creating your initial admin account.

## Overview

Supernote Private Cloud uses an **"Admin-First"** bootstrap model:
1. The server starts with no users.
2. The **first user registered** is automatically granted **Admin** privileges.
3. Once an admin exists, **Public Registration is closed** by default for security.
4. Additional users must be added by an Admin using the CLI or Admin API.

---

## Step 1: Start the Server

Start the server using the CLI:

```bash
# Optional: Set Gemini API Key for AI features (OCR, Summaries)
export SUPERNOTE_GEMINI_API_KEY="your-api-key"

# Start with default configuration (port 8080)
supernote serve
```

> [!TIP]
> Use `--config-dir` to specify a custom location for your `config.yaml` and database.

---

## Step 2: Register the Admin User

Since no users exist yet, you can register the first user from any client (including the CLI) and they will become the admin.

```bash
# Replace with your email
supernote admin user add your-email@example.com --url http://localhost:8080
```

You will be prompted to enter a password. Upon success, this user is now the system administrator.

---

## Step 3: Login and Authenticate the CLI

To perform further administrative actions, you must authenticate your CLI session.

```bash
# This caches your credentials locally in ~/.cache/supernote.pkl
supernote cloud login your-email@example.com --url http://localhost:8080
```

---

## Step 4: Adding Additional Users

Once you (the admin) are logged in, you can add other users to your server. Since registration is now closed to the public, you must use the admin command:

```bash
# Add a standard user
supernote admin user add member@example.com --name "New Member"
```

---

## Security & Advanced Configuration

### Environment Variables

For production, it is recommended to set secrets via environment:
- `SUPERNOTE_JWT_SECRET`: The secret key for signing tokens.
- `SUPERNOTE_ENABLE_REGISTRATION`: "true" or "false".
- `SUPERNOTE_GEMINI_API_KEY`: API key for AI processing features.

You can control registration behavior in your `config.yaml`:

```yaml
auth:
  # Set to true to allow anyone to register even if an admin exists
  enable_registration: false
```
