import hashlib
import logging
import secrets
import time
from typing import Optional

import jwt
from sqlalchemy import select

from ..config import AuthConfig, UserEntry
from ..db.models.user import UserDO
from ..db.session import DatabaseSessionManager
from ..models.auth import LoginResult, UserVO
from .coordination import CoordinationService
from .state import SessionState, StateService

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"


class UserService:
    """User service for authentication and authorization."""

    def __init__(
        self,
        config: AuthConfig,
        state_service: StateService,
        coordination_service: CoordinationService,
        session_manager: DatabaseSessionManager,
    ) -> None:
        """Initialize the user service."""
        self._config = config
        self._state_service = state_service
        self._coordination_service = coordination_service
        self._session_manager = session_manager

    @property
    def _users(self) -> list[UserEntry]:
        return self._config.users

    def list_users(self) -> list[UserEntry]:
        return list(self._users)

    def check_user_exists(self, account: str) -> bool:
        return any(u.username == account for u in self._users)

    async def generate_random_code(self, account: str) -> tuple[str, str]:
        """Generate a random code for login challenge."""
        random_code = secrets.token_hex(4)  # 8 chars
        timestamp = str(int(time.time() * 1000))

        # Store in coordination service with short TTL (e.g. 5 mins)
        value = f"{random_code}|{timestamp}"
        await self._coordination_service.set_value(
            f"challenge:{account}", value, ttl=300
        )

        return random_code, timestamp

    def _get_user(self, account: str) -> UserEntry | None:
        for user in self._users:
            if user.username == account:
                return user
        return None

    async def get_user_id(self, account: str) -> int:
        """Get a stable integer ID for a username using the database.

        If the user exists in config but not DB, create them in DB.
        """
        async with self._session_manager.session() as session:
            # Try to find user
            stmt = select(UserDO).where(UserDO.username == account)
            result = await session.execute(stmt)
            user_do = result.scalar_one_or_none()

            if user_do:
                return user_do.id

            # If not found, create if valid in config
            if self.check_user_exists(account):
                # Retrieve details from config to populate DB (optional)
                config_user = self._get_user(account)
                email = config_user.email if config_user else None

                new_user = UserDO(username=account, email=email)
                session.add(new_user)
                await session.commit()
                await session.refresh(new_user)
                return new_user.id

            # If not in config either?
            # Logic: If we are asking for ID, presumably the caller thinks they exist?
            # Or we return -1? Or raise?
            # Existing logic was just hash.
            # If invalid user, hash would still return valid int.
            # But VFS relies on valid user.
            raise ValueError(f"User {account} not found")

    def verify_password(self, account: str, password: str) -> bool:
        user = self._get_user(account)
        if not user or not user.is_active:
            return False
        hash_hex = hashlib.md5(password.encode()).hexdigest()
        return bool(hash_hex == user.password_md5)

    async def verify_login_hash(
        self, account: str, client_hash: str, timestamp: str
    ) -> bool:
        user = self._get_user(account)
        if not user or not user.is_active:
            return False

        stored_value = await self._coordination_service.get_value(
            f"challenge:{account}"
        )
        if not stored_value:
            return False

        random_code, stored_timestamp = stored_value.split("|")
        if stored_timestamp != timestamp:
            return False

        concat = user.password_md5 + random_code
        expected_hash = hashlib.sha256(concat.encode()).hexdigest()

        return expected_hash == client_hash

    async def login(
        self,
        account: str,
        password_hash: str,
        timestamp: str,
        equipment_no: Optional[str] = None,
    ) -> LoginResult | None:
        user = self._get_user(account)
        if not user or not user.is_active:
            return None

        if not await self.verify_login_hash(account, password_hash, timestamp):
            return None

        # Check binding status from StateService
        # StateService access is sync (local file/memory), assuming it stays that way for binding.
        user_state = self._state_service.get_user_state(account)
        bound_devices = user_state.devices
        is_bind = "Y" if bound_devices else "N"
        is_bind_equipment = (
            "Y" if equipment_no and equipment_no in bound_devices else "N"
        )

        payload = {
            "sub": account,
            "equipment_no": equipment_no or "",
            "iat": int(time.time()),
            "exp": int(time.time()) + (self._config.expiration_hours * 3600),
        }
        token = jwt.encode(payload, self._config.secret_key, algorithm=JWT_ALGORITHM)

        # Persist session in CoordinationService
        # Key: session:{token}, Value: JSON or simple string.
        # Storing username|equipment_no for simple reconstruction
        session_val = f"{account}|{equipment_no or ''}"
        ttl = self._config.expiration_hours * 3600
        await self._coordination_service.set_value(
            f"session:{token}", session_val, ttl=ttl
        )

        # Also populate StateService for legacy compatibility/persistence?
        # The roadmap implies moving AWAY from StateService for tokens.
        # But if we want to support "list sessions" later, we might need a set or something.
        # For now, strictly following roadmap "Refactor AuthService to use CoordinationService".
        # self._state_service.create_session(token, account, equipment_no)

        return LoginResult(
            token=token,
            is_bind=is_bind,
            is_bind_equipment=is_bind_equipment,
        )

    async def verify_token(self, token: str) -> SessionState | None:
        """Verify token against persisted sessions and JWT signature."""
        try:
            # 1. Check if session exists in CoordinationService
            session_val = await self._coordination_service.get_value(f"session:{token}")

            # Fallback to StateService during migration?
            # session = self._state_service.get_session(token)

            if not session_val:
                logger.warning(
                    "Session not found in coordination service: %s", token[:10]
                )
                return None

            session_val_parts = session_val.split("|")
            username = session_val_parts[0]
            equipment_no = session_val_parts[1] if len(session_val_parts) > 1 else None

            # 2. Decode and verify JWT
            payload = jwt.decode(
                token, self._config.secret_key, algorithms=[JWT_ALGORITHM]
            )
            # Ensure the token subject matches the session username
            if payload.get("sub") != username:
                logger.warning(
                    "Token sub mismatch: %s != %s", payload.get("sub"), username
                )
                return None

            # Return SessionState object (constructing it on the fly)
            return SessionState(
                token=token,
                username=username,
                equipment_no=equipment_no,
            )
        except jwt.PyJWTError as e:
            logger.warning("Token verification failed: %s", e)
            return None

    def get_user_profile(self, account: str) -> UserVO | None:
        """Get user profile from static config."""
        user = self._get_user(account)
        if not user:
            return None

        return UserVO(
            user_name=user.display_name or account,
            email=user.email or account,
            phone=user.phone or "",
            country_code="1",
            total_capacity=user.total_capacity,
            file_server="0",
            avatars_url=user.avatar or "",
            birthday="",
            sex="",
        )

    def bind_equipment(self, account: str, equipment_no: str) -> bool:
        """Bind a device to the user account using StateService."""
        if not self.check_user_exists(account):
            return False
        self._state_service.add_device(account, equipment_no)
        return True

    def unlink_equipment(self, equipment_no: str) -> bool:
        """Unlink a device from all users using StateService."""
        self._state_service.remove_device(equipment_no)
        return True
