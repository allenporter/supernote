import hashlib
import logging
import secrets
import time
from typing import Optional

import jwt

from ..config import AuthConfig, UserEntry, UsersConfig
from ..models.auth import LoginResult, UserVO

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"


class UserService:
    def __init__(self, config: AuthConfig):
        self._config = config
        self._users_config = UsersConfig.load(config.users_file)
        self._random_codes: dict[
            str, tuple[str, str]
        ] = {}  # account -> (code, timestamp)

    @property
    def _users(self) -> list[UserEntry]:
        return self._users_config.users

    def list_users(self) -> list[UserEntry]:
        return list(self._users)

    @staticmethod
    def create_user_entry(username: str, password: str) -> UserEntry:
        """Create a new UserEntry with hashed password."""
        password_md5 = hashlib.md5(password.encode()).hexdigest()
        return UserEntry(
            username=username,
            password_md5=password_md5,
            is_active=True,
            devices=[],
            profile={},
        )

    def add_user(self, username: str, password: str) -> bool:
        """Add a new user to the in-memory config. Does NOT save to disk."""
        if any(u.username == username for u in self._users):
            return False
        new_user = self.create_user_entry(username, password)
        self._users.append(new_user)
        return True

    def save(self) -> None:
        """Save the current users configuration to disk."""
        self._users_config.save(self._config.users_file)

    def deactivate_user(self, username: str) -> bool:
        """Deactivate a user in-memory. Does NOT save to disk."""
        for user in self._users:
            if user.username == username:
                user.is_active = False
                return True
        return False

    def check_user_exists(self, account: str) -> bool:
        return any(u.username == account for u in self._users)

    def generate_random_code(self, account: str) -> tuple[str, str]:
        """Generate a random code for login challenge."""
        random_code = secrets.token_hex(4)  # 8 chars
        timestamp = str(int(time.time() * 1000))
        # Only allow one active code per account at a time
        self._random_codes[account] = (random_code, timestamp)
        return random_code, timestamp

    def _get_user(self, account: str) -> UserEntry | None:
        for user in self._users:
            if user.username == account:
                return user
        return None

    def verify_password(self, account: str, password: str) -> bool:
        user = self._get_user(account)
        if not user or not user.is_active:
            logger.info("User not found or inactive: %s", account)
            return False
        if not user.password_md5:
            logger.info("MD5 password hash not found for user: %s", account)
            return False
        # Compute md5(password) and compare
        password_bytes = password.encode()
        hash_hex = hashlib.md5(password_bytes).hexdigest()
        return bool(hash_hex == user.password_md5)

    def verify_login_hash(self, account: str, client_hash: str, timestamp: str) -> bool:
        user = self._get_user(account)
        if not user or not user.is_active:
            logger.info("User not found or inactive: %s", account)
            return False

        code_tuple = self._random_codes.get(account)
        if not code_tuple or code_tuple[1] != timestamp:
            logger.warning(
                "Random code not found or timestamp mismatch for %s", account
            )
            return False
        random_code = code_tuple[0]

        if not user.password_md5:
            logger.info("MD5 password hash not found for user: %s", account)
            return False

        # Compute expected hash: sha256(password_md5 + random_code)
        concat = user.password_md5 + random_code
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
        if not user or not user.is_active:
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
        bound_devices = user.devices
        is_bind = "Y" if bound_devices else "N"
        is_bind_equipment = "N"
        if equipment_no and equipment_no in bound_devices:
            is_bind_equipment = "Y"

        payload = {
            "sub": account,
            "equipment_no": equipment_no or "",
            "iat": int(time.time()),
            "exp": int(time.time()) + (self._config.expiration_hours * 3600),
        }
        token = jwt.encode(payload, self._config.secret_key, algorithm=JWT_ALGORITHM)

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
        username = user.username
        profile = user.profile

        return UserVO(
            user_name=profile.get("user_name", username),
            email=user.email or profile.get("email", username),
            phone=user.mobile or profile.get("phone", ""),
            country_code=profile.get("country_code", "1"),
            total_capacity=profile.get("total_capacity", "25485312"),
            file_server=profile.get("file_server", "0"),
            avatars_url=user.avatar or profile.get("avatars_url", ""),
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

        if equipment_no not in user.devices:
            user.devices.append(equipment_no)
            self._users_config.save(self._config.users_file)

        return True

    def unlink_equipment(self, equipment_no: str) -> bool:
        """Unlink a device from all users (or specifically one if we knew context)."""
        logger.info("Unlinking equipment %s", equipment_no)
        found = False
        for user in self._users:
            if equipment_no in user.devices:
                user.devices.remove(equipment_no)
                found = True

        if found:
            self._users_config.save(self._config.users_file)

        return True
