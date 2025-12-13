import hashlib
import logging
import os
import secrets
import time
from typing import Optional

import jwt
import yaml

from ..models.auth import LoginResult, UserVO

logger = logging.getLogger(__name__)

# TODO: This should be generated on first startup and stored somewhere secure
JWT_SECRET = os.environ.get("SUPERNOTE_JWT_SECRET", "supernote-secret-key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.environ.get("SUPERNOTE_JWT_EXPIRATION_HOURS", "24"))


def _load_users(users_file: str) -> list[dict]:
    if not os.path.exists(users_file):
        return []
    with open(users_file, "r") as f:
        data = yaml.safe_load(f) or {"users": []}
        return data.get("users") or []


def _save_users(users_file: str, users: list[dict]) -> None:
    with open(users_file, "w") as f:
        yaml.safe_dump({"users": users}, f, default_flow_style=False)


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
        password_md5 = hashlib.md5(password.encode()).hexdigest()
        self._users.append(
            {
                "username": username,
                "password_md5": password_md5,
                "is_active": True,
                "devices": [],  # List of bound equipment numbers
                "profile": {},  # User profile data
            }
        )
        _save_users(self._users_file, self._users)
        return True

    def deactivate_user(self, username: str) -> bool:
        for user in self._users:
            if user["username"] == username:
                user["is_active"] = False
                _save_users(self._users_file, self._users)
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
        if (password_md5 := user.get("password_md5")) is None:
            logger.info("MD5 password hash not found for user: %s", account)
            return False
        # Compute md5(password) and compare
        password_bytes = password.encode()
        hash_hex = hashlib.md5(password_bytes).hexdigest()
        return bool(hash_hex == password_md5)

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
        if (password_md5 := user.get("password_md5")) is None:
            logger.info("MD5 password hash not found for user: %s", account)
            return False
        # Compute expected hash: sha256(password_md5 + random_code + timestamp)
        concat = password_md5 + random_code
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
    ) -> LoginResult | None:
        """Login user and return token and status info.

        Args:
          account: User account (email/phone)
          password_hash: Hashed password provided by client
          timestamp: Timestamp used in hash
          equipment_no: Equipment number (optional)

        Returns:
          LoginResult if login is successful, None otherwise.
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
        if not self.verify_login_hash(account, password_hash, timestamp):
            logger.warning("Login failed: invalid password hash for %s", account)
            return None

        # Check binding status
        bound_devices = user.get("devices", [])
        is_bind = "Y" if bound_devices else "N"
        is_bind_equipment = "N"
        if equipment_no and equipment_no in bound_devices:
            is_bind_equipment = "Y"

        payload = {
            "sub": account,
            "equipment_no": equipment_no or "",
            "iat": int(time.time()),
            "exp": int(time.time()) + (JWT_EXPIRATION_HOURS * 3600),
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

        return LoginResult(
            token=token,
            is_bind=is_bind,
            is_bind_equipment=is_bind_equipment,
        )

    def get_user_profile(self, account: str) -> UserVO | None:
        """Get user profile."""
        user = self._get_user(account)
        if not user:
            return None

        # Default profile values
        username = user["username"]
        profile = user.get("profile", {})

        return UserVO(
            user_name=profile.get("user_name", username),
            email=profile.get("email", username),
            phone=profile.get("phone", ""),
            country_code=profile.get("country_code", "1"),
            total_capacity=profile.get("total_capacity", "25485312"),
            file_server=profile.get("file_server", "0"),
            avatars_url=profile.get("avatars_url", ""),
            birthday=profile.get("birthday", ""),
            sex=profile.get("sex", ""),
        )

    def bind_equipment(self, account: str, equipment_no: str) -> bool:
        """Bind a device to the user account."""
        logger.info("Binding equipment %s to user %s", equipment_no, account)
        user = self._get_user(account)
        if not user:
            logger.warning("User not found for binding: %s", account)
            return False

        devices = user.get("devices", [])
        if equipment_no not in devices:
            devices.append(equipment_no)
            user["devices"] = devices
            _save_users(self._users_file, self._users)

        return True

    def unlink_equipment(self, equipment_no: str) -> bool:
        """Unlink a device from all users (or specifically one if we knew context)."""
        logger.info("Unlinking equipment %s", equipment_no)
        found = False
        for user in self._users:
            devices = user.get("devices", [])
            if equipment_no in devices:
                devices.remove(equipment_no)
                user["devices"] = devices
                found = True

        if found:
            _save_users(self._users_file, self._users)

        return True
