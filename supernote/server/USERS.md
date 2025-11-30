# User Account Management for supernote-lite

This file describes how to create and manage user accounts for your private Supernote server.

## Adding Users

1. **Generate a bcrypt password hash** for the desired password. You can use Python:

   ```python
   import bcrypt
   password = b"yourpassword"
   print(bcrypt.hashpw(password, bcrypt.gensalt()).decode())
   ```
   Or use the `htpasswd` command-line tool with bcrypt support:
   ```sh
   htpasswd -bnBC 12 "" yourpassword | tr -d ':\n'
   ```
   (Copy the hash after the colon.)

2. **Edit `config/users.yaml`** and add a new user entry:

   ```yaml
   users:
     - username: alice
       password_hash: "$2b$12$..."
       is_active: true
     - username: bob
       password_hash: "$2b$12$..."
       is_active: true
   ```

3. **Save the file.**

## Notes
- Only users listed in this file can log in.
- Passwords are never stored in plain text—only bcrypt hashes.
- Set `is_active: false` to disable a user without deleting their entry.
- This file is ignored by git for security.
