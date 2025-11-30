import secrets
import time
import logging
import os
import yaml
import hashlib
import jwt
from typing import Optional
from ..models.auth import UserVO

logger = logging.getLogger(__name__)

# TODO: This should be generated on first startup and stored somewhere secure
JWT_SECRET = os.environ.get("SUPERNOTE_JWT_SECRET", "supernote-secret-key")
JWT_ALGORITHM = "HS256"


def _load_users(users_file: str) -> list[dict]:
    if not os.path.exists(users_file):
        return []
    with open(users_file, "r") as f:
        data = yaml.safe_load(f) or {"users": []}
        return data.get("users") or []


class UserService:
    def __init__(self, users_file: str):
        self._users_file = users_file
        self._users = _load_users(users_file)
        self._random_codes: dict[
            str, tuple[str, str]
        ] = {}  # account -> (code, timestamp)

    def list_users(self) -> list[dict]:
        return list(self._users)

    def add_user(self, username: str, password: str) -> bool:
        if any(u["username"] == username for u in self._users):
            return False
        password_sha256 = hashlib.sha256(password.encode()).hexdigest()
        self._users.append(
            {
                "username": username,
                "password_sha256": password_sha256,
                "is_active": True,
            }
        )
        with open(self._users_file, "w") as f:
            yaml.safe_dump({"users": self._users}, f, default_flow_style=False)
        return True

    def deactivate_user(self, username: str) -> bool:
        for user in self._users:
            if user["username"] == username:
                user["is_active"] = False
                with open(self._users_file, "w") as f:
                    yaml.safe_dump({"users": self._users}, f, default_flow_style=False)
                return True
        return False

    def check_user_exists(self, account: str) -> bool:
        return any(u["username"] == account for u in self._users)

    def generate_random_code(self, account: str) -> tuple[str, str]:
        """Generate a random code for login challenge."""
        random_code = secrets.token_hex(4)  # 8 chars
        timestamp = str(int(time.time() * 1000))
        # Only allow one active code per account at a time
        self._random_codes[account] = (random_code, timestamp)
        return random_code, timestamp

    def _get_user(self, account: str) -> dict | None:
        for user in self._users:
            if user["username"] == account:
                return user
        return None

    def verify_password(self, account: str, password: str) -> bool:
        user = self._get_user(account)
        if not user or not user.get("is_active", True):
            logger.info("User not found or inactive: %s", account)
            return False
        password_sha256 = user.get("password_sha256")
        if not password_sha256:
            logger.info("SHA256 password hash not found for user: %s", account)
            return False
        # Compute sha256(password) and compare
        password_bytes = password.encode()
        hash_hex = hashlib.sha256(password_bytes).hexdigest()
        return hash_hex == password_sha256

    def verify_login_hash(self, account: str, client_hash: str, timestamp: str) -> bool:
        user = self._get_user(account)
        if not user or not user.get("is_active", True):
            logger.info("User not found or inactive: %s", account)
            return False
        code_tuple = self._random_codes.get(account)
        if not code_tuple or code_tuple[1] != timestamp:
            logger.warning(
                "Random code not found or timestamp mismatch for %s", account
            )
            return False
        random_code = code_tuple[0]
        password_sha256 = user.get("password_sha256")
        if not password_sha256:
            logger.info("SHA256 password hash not found for user: %s", account)
            return False
        # Compute expected hash: sha256(password_sha256 + random_code + timestamp)
        concat = password_sha256 + random_code + timestamp
        expected_hash = hashlib.sha256(concat.encode()).hexdigest()
        if expected_hash == client_hash:
            return True
        logger.info("Login hash mismatch for user: %s", account)
        return False

    def login(
        self,
        account: str,
        password_hash: str,
        timestamp: str,
        equipment_no: Optional[str] = None,
    ) -> str | None:
        """Login user and return a token.

        Args:
          account: User account (email/phone)
          password_hash: Hashed password provided by client
          timestamp: Timestamp used in hash
          equipment_no: Equipment number (optional)

        Returns:
          JWT token if login is successful, None otherwise.
        """
        user = self._get_user(account)
        if not user or not user.get("is_active", True):
            # TODO: Raise exceptions so we can return a useful error message
            # to the web APIs.
            logger.warning("Login failed: user not found or inactive: %s", account)
            return None
        code_tuple = self._random_codes.get(account)
        if not code_tuple or code_tuple[1] != timestamp:
            logger.warning(
                "Login failed: random code missing or timestamp mismatch for %s",
                account,
            )
            return None
        # For now, skip hash verification (see verify_login_hash)
        payload = {
            "sub": account,
            "equipment_no": equipment_no or "",
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        return token

    def get_user_profile(self, account: str) -> UserVO | None:
        """Get user profile."""
        user = self._get_user(account)
        if not user:
            return None
        username = user["username"] if user else "Supernote User"
        return UserVO(
            user_name=username,
            email=username,
            phone="",
            country_code="1",
            total_capacity="25485312",
            file_server="0",  # 0 for ufile (or local?), 1 for aws
            avatars_url="",
            birthday="",
            sex="",
        )

    def bind_equipment(self, account: str, equipment_no: str) -> bool:
        """Bind a device to the user account."""
        logger.info("Binding equipment %s to user %s", equipment_no, account)
        return True

    def unlink_equipment(self, equipment_no: str) -> bool:
        """Unlink a device."""
        logger.info("Unlinking equipment %s", equipment_no)
        return True
