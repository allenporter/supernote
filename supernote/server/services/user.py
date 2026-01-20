import datetime
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional

import jwt
from mashumaro.mixins.json import DataClassJSONMixin
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.models.auth import Equipment, LoginVO, UserVO
from supernote.models.user import (
    LoginRecordVO,
    UpdateEmailDTO,
    UpdatePasswordDTO,
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
    equipment_no: Optional[str] = None
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

    async def list_users(self) -> list[UserDO]:
        async with self._session_manager.session() as session:
            result = await session.execute(select(UserDO))
            return list(result.scalars().all())

    async def check_user_exists(self, account: str) -> bool:
        async with self._session_manager.session() as session:
            stmt = select(UserDO).where(UserDO.email == account)
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

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
        - System folders at root (Export, Inbox, Screenshot)
        - Category containers (NOTE, DOCUMENT) with children

        This structure is stored as-is in the database. The web API will
        flatten it during listing operations.
        """
        async with self._session_manager.session() as session:
            vfs = VirtualFileSystem(session)

            # System folders at root (directoryId=0) - always visible
            await vfs.create_directory(user_id, 0, "Export")
            await vfs.create_directory(user_id, 0, "Inbox")
            await vfs.create_directory(user_id, 0, "Screenshot")

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

    async def unregister(self, account: str) -> None:
        """Delete a user."""
        if not self._config.enable_registration:
            raise ValueError("Registration is disabled")
        async with self._session_manager.session() as session:
            # Find user ID first
            stmt = select(UserDO).where(UserDO.email == account)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if not user:
                return

            await session.execute(delete(DeviceDO).where(DeviceDO.user_id == user.id))
            await session.execute(
                delete(LoginRecordDO).where(LoginRecordDO.user_id == user.id)
            )
            await session.execute(delete(UserDO).where(UserDO.id == user.id))
            await session.commit()

    async def generate_random_code(self, account: str) -> tuple[str, str]:
        """Generate a random code for login challenge."""
        random_code = secrets.token_hex(4)  # 8 chars
        timestamp = str(int(time.time() * 1000))

        # Store in coordination service with short TTL (e.g. 5 mins)
        value = f"{random_code}|{timestamp}"
        await self._coordination_service.set_value(
            f"challenge:{account}", value, ttl=int(RANDOM_CODE_TTL.total_seconds())
        )

        return random_code, timestamp

    async def _get_user_do(self, account: str) -> UserDO | None:
        async with self._session_manager.session() as session:
            stmt = select(UserDO).where(UserDO.email == account)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_user_id(self, account: str) -> int:
        user = await self._get_user_do(account)
        if user:
            return user.id
        raise ValueError(f"User {account} not found")

    async def verify_login_hash(
        self, account: str, client_hash: str, timestamp: str
    ) -> bool:
        user = await self._get_user_do(account)
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

        expected_hash = hash_with_salt(user.password_md5, random_code)
        return expected_hash == client_hash

    async def login(
        self,
        account: str,
        password_hash: str,
        timestamp: str,
        equipment_no: Optional[str] = None,
        equipment: Equipment = Equipment.WEB,
        ip: Optional[str] = None,
        login_method: Optional[str] = None,
    ) -> LoginVO | None:
        user = await self._get_user_do(account)
        if not user or not user.is_active:
            logger.debug("User %s not found or not active", account)
            return None

        if not await self.verify_login_hash(account, password_hash, timestamp):
            logger.debug("Invalid login hash for user %s", account)
            return None

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

        if equipment in (Equipment.TERMINAL, Equipment.APP):
            ttl = self._config.device_expiration_hours * 3600
        else:
            ttl = self._config.expiration_hours * 3600

        payload = {
            "sub": account,
            "equipment_no": equipment_no or "",
            "iat": int(time.time()),
            "exp": int(time.time()) + ttl,
        }
        token = jwt.encode(payload, self._config.secret_key, algorithm=JWT_ALGORITHM)

        # Persist session in CoordinationService
        session_val = f"{account}|{equipment_no or ''}"
        await self._coordination_service.set_value(
            f"session:{token}", session_val, ttl=ttl
        )

        return LoginVO(
            token=token,
            counts="0",
            is_bind=is_bind,
            is_bind_equipment=is_bind_equipment,
            user_name=account,
        )

    async def verify_token(self, token: str) -> SessionState | None:
        """Verify token against persisted sessions and JWT signature."""
        try:
            # 1. Check if session exists in CoordinationService
            session_val = await self._coordination_service.get_value(f"session:{token}")

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
            if payload.get("sub") != username:
                return None

            return SessionState(
                token=token,
                email=username,
                equipment_no=equipment_no,
            )
        except jwt.PyJWTError as e:
            logger.warning("Token verification failed: %s", e)
            return None

    async def get_user_profile(self, account: str) -> UserVO | None:
        user = await self._get_user_do(account)
        if not user:
            return None

        return UserVO(
            user_name=user.display_name or account,
            email=user.email or account,
            phone=user.phone or "",
            total_capacity=user.total_capacity,
            file_server="",
            avatars_url=user.avatar or "",
            birthday="",
            sex="",
        )

    async def bind_equipment(self, account: str, equipment_no: str) -> bool:
        """Bind a device to the user."""
        user = await self._get_user_do(account)
        if not user:
            return False

        async with self._session_manager.session() as session:
            # Upsert
            existing = await session.execute(
                select(DeviceDO).where(DeviceDO.equipment_no == equipment_no)
            )
            if existing.scalar_one_or_none():
                # Device already exists, update binding to current user.
                await session.execute(
                    update(DeviceDO)
                    .where(DeviceDO.equipment_no == equipment_no)
                    .values(user_id=user.id)
                )
            else:
                session.add(DeviceDO(user_id=user.id, equipment_no=equipment_no))
            await session.commit()
            return True

    async def unlink_equipment(self, equipment_no: str) -> bool:
        """Unlink a device."""
        async with self._session_manager.session() as session:
            await session.execute(
                delete(DeviceDO).where(DeviceDO.equipment_no == equipment_no)
            )
            await session.commit()
        return True

    async def update_password(self, account: str, dto: UpdatePasswordDTO) -> bool:
        """Update user password."""
        if not re.match(MD5_REGEX, dto.password):
            raise ValueError("Invalid password format, must be md5 hash")

        async with self._session_manager.session() as session:
            await session.execute(
                update(UserDO)
                .where(UserDO.email == account)
                .values(password_md5=dto.password)
            )
            await session.commit()
        return True

    async def update_email(self, account: str, dto: UpdateEmailDTO) -> bool:
        """Update user email."""
        async with self._session_manager.session() as session:
            await session.execute(
                update(UserDO).where(UserDO.email == account).values(email=dto.email)
            )
            await session.commit()
        return True

    async def admin_reset_password(self, email: str, password_md5: str) -> None:
        """Force reset user password (Admin only)."""
        if not re.match(MD5_REGEX, password_md5):
            raise ValueError("Invalid password format, must be md5 hash")

        async with self._session_manager.session() as session:
            result = await session.execute(select(UserDO).where(UserDO.email == email))
            user = result.scalar_one_or_none()
            if not user:
                raise ValueError(f"User {email} not found")

            user.password_md5 = password_md5
            await session.commit()

    async def retrieve_password(self, account: str, password_md5: str) -> bool:
        """Retrieve/Reset password."""
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

            user.password_md5 = password_md5
            await session.commit()
        return True

    async def query_login_records(
        self, account: str, page: int, size: int
    ) -> tuple[list[LoginRecordVO], int]:
        """Query login records."""
        user = await self._get_user_do(account)
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
