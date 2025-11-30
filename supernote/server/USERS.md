# User Account Management for supernote-lite

This file describes how to create and manage user accounts for your private Supernote server.

## Adding Users

1. **Generate a bcrypt password hash** for the desired password. You can use Python:

   ```python
  # User Account Management for supernote-lite

  This file describes how to create and manage user accounts for your private Supernote server.

  ## Adding Users

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

  ## Notes

  - Only users listed in this file can log in.
  - Passwords are never stored in plain text—only SHA256 hashes (see PLAN.md for security notes).
  - Set `is_active: false` to disable a user without deleting their entry.
  - This file is ignored by git for security.
