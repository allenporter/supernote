import datetime
import hmac
import logging
import re
import secrets
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field

import jwt
from mashumaro.mixins.json import DataClassJSONMixin
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.auth import Equipment, LoginVO, UserVO
from supernote.models.base import ErrorCode
from supernote.models.equipment import UserEquipmentVO
from supernote.models.user import (
    LoginRecordVO,
    UpdateEmailDTO,
    UpdatePasswordDTO,
    UserCheckDTO,
    UserCheckVO,
    UserRegisterDTO,
)
from supernote.server.utils.hashing import hash_with_salt

from ..config import AuthConfig
from ..db.models.device import DeviceDO
from ..db.models.login_record import LoginRecordDO
from ..db.models.user import UserDO
from ..db.session import DatabaseSessionManager
from .coordination import CoordinationService
from .vfs import VirtualFileSystem

RANDOM_CODE_TTL = datetime.timedelta(minutes=5)
UNIQUE_MACHINE_ID_KEY = "system:unique_machine_id"
JWT_SECRET_KEY = "system:jwt_secret_key"
# CoordinationService requires a numeric expiry (defaults to 1 year if omitted);
# use a 100-year TTL for server-lifetime keys (unique_machine_id, jwt_secret_key, and sold_out_count).
UNIQUE_MACHINE_ID_TTL = 100 * 365 * 24 * 3600
SOLD_OUT_KEY_PREFIX = "user:sold_out_count:"

# Validate email format
# 1. No consecutive dots: (?!.*\.\.)
# 2. No leading dot: (?!^\.)
# 3. No trailing dot in local part: (?<!\.)@
EMAIL_REGEX = r"^(?!.*\.\.)(?!^\.)[a-zA-Z0-9_.+-]+(?<!\.)@[a-zA-Z0-9][a-zA-Z0-9-]*\.[a-zA-Z0-9-.]+$"

# Validate MD5 hash
MD5_REGEX = r"^[a-f0-9]{32}$"


@dataclass
class SessionState(DataClassJSONMixin):
    token: str
    email: str
    user_id: int
    equipment_no: str | None = None
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)


logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"


class UserService:
    """User service for authentication and authorization."""

    def __init__(
        self,
        config: AuthConfig,
        coordination_service: CoordinationService,
        session_manager: DatabaseSessionManager,
    ) -> None:
        """Initialize the user service."""
        self._config = config
        self._coordination_service = coordination_service
        self._session_manager = session_manager

    async def get_secret_key(self) -> str:
        """Return the JWT secret key, generating and persisting one in CoordinationService if unconfigured."""
        if self._config.secret_key:
            return self._config.secret_key
        secret = await self._coordination_service.get_value(JWT_SECRET_KEY)
        if not secret:
            secret = secrets.token_hex(32)
            await self._coordination_service.set_value(
                JWT_SECRET_KEY,
                secret,
                ttl=UNIQUE_MACHINE_ID_TTL,
            )
        self._config.secret_key = secret
        return secret

    @staticmethod
    def _sold_out_key(account: str) -> str:
        """Build the CoordinationService key for tracking account deletion count."""
        return f"{SOLD_OUT_KEY_PREFIX}{account}"

    async def get_sold_out_count(self, account: str) -> int:
        """Return the number of times an account with this email has been deleted."""
        val = await self._coordination_service.get_value(self._sold_out_key(account))
        return int(val) if val and val.isdigit() else 0

    @staticmethod
    def _session_prefix(user_id: int, equipment_no: str | None = None) -> str:
        """Build the CoordinationService key prefix for user or device sessions."""
        if equipment_no is None:
            return f"session:{user_id}:"
        encoded_eq = urllib.parse.quote(equipment_no, safe="")
        return f"session:{user_id}:{encoded_eq}:"

    @classmethod
    def _session_key(cls, user_id: int, equipment_no: str | None, token: str) -> str:
        """Build the CoordinationService key for a user session."""
        return f"{cls._session_prefix(user_id, equipment_no or '')}{token}"

    async def revoke_user_sessions(self, user_id: int) -> None:
        """Revoke all active sessions for a user."""
        await self._coordination_service.delete_by_prefix(self._session_prefix(user_id))

    async def revoke_equipment_sessions(self, user_id: int, equipment_no: str) -> None:
        """Revoke all active sessions for a specific device belonging to a user."""
        if not equipment_no:
            return
        await self._coordination_service.delete_by_prefix(
            self._session_prefix(user_id, equipment_no)
        )

    async def logout(self, token: str) -> None:
        """Revoke a single session token."""
        if not token:
            return
        secret_key = await self.get_secret_key()
        try:
            payload = jwt.decode(
                token,
                secret_key,
                algorithms=[JWT_ALGORITHM],
                options={"verify_exp": False},
            )
        except jwt.PyJWTError:
            logger.debug("Logout called with invalid JWT")
            return

        user_id = payload.get("user_id")
        equipment_no = payload.get("equipment_no")
        if type(user_id) is not int or not isinstance(equipment_no, str):
            return
        await self._coordination_service.delete_value(
            self._session_key(user_id, equipment_no, token)
        )

    @staticmethod
    def _to_user_vo(user: UserDO) -> UserVO:
        """Convert a UserDO database record to a UserVO API model."""
        return UserVO(
            user_id=user.id,
            user_name=user.display_name or user.email,
            email=user.email,
            phone=user.phone or "",
            total_capacity=user.total_capacity,
            file_server="",
            avatars_url=user.avatar or "",
            birthday="",
            sex="",
        )

    async def list_users(self) -> list[UserDO]:
        async with self._session_manager.session() as session:
            result = await session.execute(select(UserDO))
            return list(result.scalars().all())

    async def list_user_profiles(self) -> list[UserVO]:
        """List all users as UserVO profile models."""
        return [self._to_user_vo(u) for u in await self.list_users()]

    async def check_user_exists(self, account: str) -> bool:
        return (await self.get_user_by_email(account)) is not None

    async def get_unique_machine_id(self) -> str:
        """Return the persistent unique machine identifier for this server instance."""
        machine_id = await self._coordination_service.get_value(UNIQUE_MACHINE_ID_KEY)
        if machine_id:
            return machine_id
        machine_id = str(uuid.uuid4())
        await self._coordination_service.set_value(
            UNIQUE_MACHINE_ID_KEY,
            machine_id,
            ttl=UNIQUE_MACHINE_ID_TTL,
        )
        return machine_id

    async def check_user_server(self, dto: UserCheckDTO) -> UserCheckVO:
        """Check if a user exists on this server and return routing/machine metadata."""
        user = await self.get_user_by_email(dto.email) if dto.email else None
        if not user:
            return UserCheckVO(
                success=False,
                error_code=ErrorCode.ACCOUNT_NOT_EXIST.value,
                error_msg="User not found",
            )
        machine_id = await self.get_unique_machine_id()
        return UserCheckVO(
            user_id=user.id,
            unique_machine_id=machine_id,
            dms="ALL",
        )

    async def _create_user_entry(
        self, session: AsyncSession, dto: UserRegisterDTO, is_admin: bool = False
    ) -> UserDO:
        """Internal helper to insert user into DB."""
        if await self.check_user_exists(dto.email):
            raise ValueError("User already exists")

        if not re.match(EMAIL_REGEX, dto.email):
            raise ValueError("Invalid email address format")

        # Hash password before storage.
        if not re.match(MD5_REGEX, dto.password):
            raise ValueError("Invalid password format, must be md5 hash")
        new_user = UserDO(
            email=dto.email,
            password_md5=dto.password,
            display_name=dto.user_name,
            is_active=True,
            is_admin=is_admin,
        )
        session.add(new_user)
        # Flush to get ID, but let caller commit
        await session.flush()
        return new_user

    async def _create_system_directories(self, user_id: int) -> None:
        """Create the standard Supernote directory structure for a new user.

        Creates the real two-level structure used by device firmware:
        - System folders at root (EXPORT, INBOX, SCREENSHOT), named as the firmware names them
        - Category containers (NOTE, DOCUMENT) with children

        This structure is stored as-is in the database. The web API will
        flatten it during listing operations.
        """
        async with self._session_manager.session() as session:
            vfs = VirtualFileSystem(session)

            # System folders at root (directoryId=0) - always visible
            await vfs.create_directory(user_id, 0, "EXPORT")
            await vfs.create_directory(user_id, 0, "INBOX")
            await vfs.create_directory(user_id, 0, "SCREENSHOT")

            # Category containers with children (for device firmware compatibility)
            note_parent = await vfs.create_directory(user_id, 0, "NOTE")
            await vfs.create_directory(user_id, note_parent.id, "Note")
            await vfs.create_directory(user_id, note_parent.id, "MyStyle")

            doc_parent = await vfs.create_directory(user_id, 0, "DOCUMENT")
            await vfs.create_directory(user_id, doc_parent.id, "Document")

            await session.commit()

    async def register(self, dto: UserRegisterDTO) -> UserDO:
        """Register a new user (Public/Self-Service)."""
        async with self._session_manager.session() as session:
            # Check for bootstrapping condition (no users exist)
            user_count = (await session.execute(select(func.count(UserDO.id)))).scalar()
            is_bootstrap = user_count == 0

            if not self._config.enable_registration and not is_bootstrap:
                raise ValueError("Registration is disabled")

            new_user = await self._create_user_entry(
                session, dto, is_admin=is_bootstrap
            )
            await session.commit()
            await session.refresh(new_user)

        # Create system directories after user is committed
        await self._create_system_directories(new_user.id)
        return new_user

    async def create_user(self, dto: UserRegisterDTO) -> UserDO:
        """Create a new user (Admin/System). Skips registration enabled check."""
        async with self._session_manager.session() as session:
            new_user = await self._create_user_entry(session, dto, is_admin=False)
            await session.commit()
            await session.refresh(new_user)

        # Create system directories after user is committed
        await self._create_system_directories(new_user.id)
        return new_user

    async def clear_account(self, account: str) -> int | None:
        """Permanently delete a user account, its device bindings, login history, and sessions.

        WARNING: This permanently deletes the user record and revokes all active
        sessions. Callers are responsible for invoking domain service cleanup for
        the returned `user_id` to purge all user files, blobs, summaries, and
        schedule tasks.
        """
        if not self._config.enable_registration:
            raise ValueError("Registration is disabled")
        async with self._session_manager.session() as session:
            # Find user ID first
            stmt = select(UserDO).where(UserDO.email == account)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if not user:
                return None
            user_id = user.id

        await self.revoke_user_sessions(user_id)

        async with self._session_manager.session() as session:
            await session.execute(delete(DeviceDO).where(DeviceDO.user_id == user_id))
            await session.execute(
                delete(LoginRecordDO).where(LoginRecordDO.user_id == user_id)
            )
            await session.execute(delete(UserDO).where(UserDO.id == user_id))
            await session.commit()

        await self._coordination_service.increment(
            self._sold_out_key(account),
            ttl=UNIQUE_MACHINE_ID_TTL,
        )
        await self.revoke_user_sessions(user_id)
        return user_id

    async def generate_random_code(self, account: str) -> tuple[str, str]:
        """Generate a random code for login challenge."""
        random_code = secrets.token_hex(4)  # 8 chars
        ts_ms = int(time.time() * 1000)
        while (
            await self._coordination_service.get_value(f"challenge:{account}:{ts_ms}")
            is not None
        ):
            ts_ms += 1
        timestamp = str(ts_ms)

        # Store in coordination service with short TTL (e.g. 5 mins), scoped by account and timestamp
        await self._coordination_service.set_value(
            f"challenge:{account}:{timestamp}",
            random_code,
            ttl=int(RANDOM_CODE_TTL.total_seconds()),
        )

        return random_code, timestamp

    async def _get_user_by_id(self, user_id: int) -> UserDO | None:
        async with self._session_manager.session() as session:
            stmt = select(UserDO).where(UserDO.id == user_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_user_by_email(self, account: str) -> UserDO | None:
        """Get a user by their email address."""
        async with self._session_manager.session() as session:
            stmt = select(UserDO).where(UserDO.email == account)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_user_id(self, account: str) -> int:
        user = await self.get_user_by_email(account)
        if user:
            return user.id
        raise ValueError(f"User {account} not found")

    async def _verify_login_hash(
        self,
        account: str,
        password_md5: str,
        client_hash: str,
        timestamp: str,
    ) -> bool:
        if not timestamp:
            logger.warning("Login failed for %s: missing challenge timestamp", account)
            return False

        try:
            client_ts_ms = int(timestamp)
        except ValueError:
            logger.warning("Login failed for %s: invalid timestamp format", account)
            return False

        random_code = await self._coordination_service.pop_value(
            f"challenge:{account}:{client_ts_ms}"
        )
        if not random_code:
            logger.warning(
                "Login failed for %s: challenge expired or not found (timestamp=%d)",
                account,
                client_ts_ms,
            )
            return False

        expected_hash = hash_with_salt(password_md5, random_code)
        if not hmac.compare_digest(expected_hash, client_hash):
            logger.warning("Login failed for %s: password hash mismatch", account)
            return False

        return True

    async def login(
        self,
        account: str,
        password_hash: str,
        timestamp: str,
        equipment_no: str | None = None,
        equipment: Equipment = Equipment.WEB,
        ip: str | None = None,
        login_method: str | None = None,
    ) -> LoginVO:
        user = await self.get_user_by_email(account)
        if not user:
            logger.debug("User %s not found", account)
            return LoginVO(
                success=False,
                error_code=ErrorCode.ACCOUNT_NOT_EXIST.value,
                error_msg=ErrorCode.ACCOUNT_NOT_EXIST.message,
            )
        if not user.is_active:
            logger.debug("User %s is not active", account)
            return LoginVO(
                success=False,
                error_code=ErrorCode.USER_DISABLED.value,
                error_msg=ErrorCode.USER_DISABLED.message,
            )

        if not await self._verify_login_hash(
            account, user.password_md5, password_hash, timestamp
        ):
            logger.debug("Invalid login hash for user %s", account)
            return LoginVO(
                success=False,
                error_code=ErrorCode.PASSWORD_ERROR.value,
                error_msg=ErrorCode.PASSWORD_ERROR.message,
                counts="1",
            )

        # Check binding status from DB
        is_bind = "N"
        is_bind_equipment = "N"

        async with self._session_manager.session() as session:
            # Check devices
            stmt = select(DeviceDO).where(DeviceDO.user_id == user.id)
            devices = (await session.execute(stmt)).scalars().all()
            if devices:
                is_bind = "Y"
                if equipment_no and any(
                    d.equipment_no == equipment_no for d in devices
                ):
                    is_bind_equipment = "Y"

            # Record Login
            record = LoginRecordDO(
                user_id=user.id,
                login_method=login_method or "2",  # Default email
                equipment=equipment_no,
                ip=ip,
                create_time=datetime.datetime.now().isoformat(),
            )
            session.add(record)
            await session.commit()

        token = await self._create_session_for_user(
            user=user,
            equipment_no=equipment_no,
            equipment=equipment,
        )
        sold_out_count = await self.get_sold_out_count(account)

        return LoginVO(
            token=token,
            counts="0",
            is_bind=is_bind,
            is_bind_equipment=is_bind_equipment,
            user_name=user.email,
            sold_out_count=sold_out_count,
        )

    async def create_session(
        self,
        account: str,
        equipment_no: str | None = None,
        equipment: Equipment = Equipment.WEB,
    ) -> str:
        """Create and persist a new authenticated session token for an active account."""
        user = await self.get_user_by_email(account)
        if not user or not user.is_active:
            raise ValueError(f"Active user {account} not found")
        return await self._create_session_for_user(user, equipment_no, equipment)

    async def _create_session_for_user(
        self,
        user: UserDO,
        equipment_no: str | None = None,
        equipment: Equipment = Equipment.WEB,
    ) -> str:
        if equipment in (Equipment.TERMINAL, Equipment.APP):
            ttl = self._config.device_expiration_hours * 3600
        else:
            ttl = self._config.expiration_hours * 3600

        if equipment_no:
            await self.revoke_equipment_sessions(user.id, equipment_no)

        now = int(time.time())
        payload = {
            "sub": user.email,
            "user_id": user.id,
            "equipment_no": equipment_no or "",
            "iat": now,
            "exp": now + ttl,
            "jti": secrets.token_hex(8),
        }
        secret_key = await self.get_secret_key()
        token = jwt.encode(payload, secret_key, algorithm=JWT_ALGORITHM)

        session_state = SessionState(
            token=token,
            email=user.email,
            user_id=user.id,
            equipment_no=equipment_no or None,
        )
        session_key = self._session_key(user.id, equipment_no, token)
        await self._coordination_service.set_value(
            session_key, str(session_state.to_json()), ttl=ttl
        )
        return token

    async def verify_token(self, token: str) -> SessionState | None:
        """Verify token against JWT signature, persisted session state, and active user record."""
        if not token:
            return None
        secret_key = await self.get_secret_key()
        try:
            payload = jwt.decode(token, secret_key, algorithms=[JWT_ALGORITHM])
        except jwt.PyJWTError as err:
            logger.warning("Token verification failed: %s", err)
            return None

        sub = payload.get("sub")
        user_id = payload.get("user_id")
        equipment_no = payload.get("equipment_no")
        if (
            not isinstance(sub, str)
            or not sub
            or type(user_id) is not int
            or not isinstance(equipment_no, str)
        ):
            logger.warning("Token missing or malformed required claims")
            return None

        session_key = self._session_key(user_id, equipment_no, token)
        session_val = await self._coordination_service.get_value(session_key)
        if not session_val:
            logger.warning("Session not found in coordination service: %s", token[:10])
            return None

        try:
            session_state = SessionState.from_json(session_val)
        except (ValueError, TypeError, KeyError) as err:
            logger.warning("Invalid persisted session state: %s", err)
            return None

        if (
            session_state.user_id != user_id
            or session_state.email != sub
            or (session_state.equipment_no or "") != equipment_no
        ):
            logger.warning("Persisted session state mismatch for user_id=%s", user_id)
            return None

        user = await self._get_user_by_id(user_id)
        if not user or not user.is_active or user.email != sub:
            logger.warning("Token user invalid or inactive for user_id=%s", user_id)
            return None

        return session_state

    async def get_user_profile(self, account: str) -> UserVO | None:
        user = await self.get_user_by_email(account)
        if not user:
            return None
        return self._to_user_vo(user)

    async def bind_equipment(self, account: str, equipment_no: str) -> None:
        """Bind a device to the user."""
        user = await self.get_user_by_email(account)
        if not user:
            return

        async with self._session_manager.session() as session:
            existing = (
                await session.execute(
                    select(DeviceDO).where(DeviceDO.equipment_no == equipment_no)
                )
            ).scalar_one_or_none()
            if existing:
                if existing.user_id == user.id:
                    return
                raise ValueError(
                    f"Equipment {equipment_no} is already bound to another account"
                )
            session.add(DeviceDO(user_id=user.id, equipment_no=equipment_no))
            await session.commit()

    async def unlink_equipment(self, equipment_no: str) -> None:
        """Unlink a device."""
        async with self._session_manager.session() as session:
            await session.execute(
                delete(DeviceDO).where(DeviceDO.equipment_no == equipment_no)
            )
            await session.commit()

    async def query_equipment_by_no(self, equipment_no: str) -> UserEquipmentVO:
        """Query bound device details by equipment serial number."""
        async with self._session_manager.session() as session:
            result = await session.execute(
                select(DeviceDO).where(DeviceDO.equipment_no == equipment_no)
            )
            device = result.scalar_one_or_none()
            if not device:
                return UserEquipmentVO()
            return UserEquipmentVO(
                equipment_number=device.equipment_no,
                user_id=device.user_id,
                status="Y",
            )

    async def update_password(self, account: str, dto: UpdatePasswordDTO) -> None:
        """Update user password and revoke active sessions."""
        if not re.match(MD5_REGEX, dto.password):
            raise ValueError("Invalid password format, must be md5 hash")

        async with self._session_manager.session() as session:
            result = await session.execute(
                select(UserDO).where(UserDO.email == account)
            )
            user = result.scalar_one_or_none()
            if not user:
                raise ValueError(f"User {account} not found")
            user_id = user.id
            user.password_md5 = dto.password
            await session.commit()

        await self.revoke_user_sessions(user_id)

    async def update_email(self, account: str, dto: UpdateEmailDTO) -> None:
        """Update user email and revoke active sessions bound to the old email."""
        if not re.match(EMAIL_REGEX, dto.email):
            raise ValueError("Invalid email address format")

        async with self._session_manager.session() as session:
            result = await session.execute(
                select(UserDO).where(UserDO.email == account)
            )
            user = result.scalar_one_or_none()
            if not user:
                raise ValueError(f"User {account} not found")

            if dto.email != account:
                existing = await session.execute(
                    select(UserDO).where(UserDO.email == dto.email)
                )
                if existing.scalar_one_or_none() is not None:
                    raise ValueError("Email already registered")

            user_id = user.id
            user.email = dto.email
            try:
                await session.commit()
            except IntegrityError as err:
                await session.rollback()
                raise ValueError("Email already registered") from err

        await self.revoke_user_sessions(user_id)

    async def admin_reset_password(self, email: str, password_md5: str) -> None:
        """Force reset user password (Admin only) and revoke active sessions."""
        if not re.match(MD5_REGEX, password_md5):
            raise ValueError("Invalid password format, must be md5 hash")

        async with self._session_manager.session() as session:
            result = await session.execute(select(UserDO).where(UserDO.email == email))
            user = result.scalar_one_or_none()
            if not user:
                raise ValueError(f"User {email} not found")
            user_id = user.id
            user.password_md5 = password_md5
            await session.commit()

        await self.revoke_user_sessions(user_id)

    async def retrieve_password(self, account: str, password_md5: str) -> bool:
        """Retrieve/Reset password and revoke active sessions."""
        # Find user by alias (email/phone/username) and reset password.
        if not account:
            return False

        if not re.match(MD5_REGEX, password_md5):
            raise ValueError("Invalid password format, must be md5 hash")

        async with self._session_manager.session() as session:
            # Find user
            stmt = select(UserDO).where(
                (UserDO.email == account) | (UserDO.phone == account)
            )
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                return False

            user_id = user.id
            user.password_md5 = password_md5
            await session.commit()

        await self.revoke_user_sessions(user_id)
        return True

    async def query_login_records(
        self, account: str, page: int, size: int
    ) -> tuple[list[LoginRecordVO], int]:
        """Query login records."""
        user = await self.get_user_by_email(account)
        if not user:
            return [], 0

        async with self._session_manager.session() as session:
            count_stmt = (
                select(func.count())
                .select_from(LoginRecordDO)
                .where(LoginRecordDO.user_id == user.id)
            )
            total = (await session.execute(count_stmt)).scalar() or 0

            stmt = (
                select(LoginRecordDO)
                .where(LoginRecordDO.user_id == user.id)
                .order_by(LoginRecordDO.create_time.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
            records = (await session.execute(stmt)).scalars().all()

            vos = [
                LoginRecordVO(
                    user_id=str(user.id),
                    user_name=user.email,
                    create_time=r.create_time,
                    equipment=r.equipment,
                    ip=r.ip,
                    login_method=r.login_method,
                )
                for r in records
            ]

            return vos, total
