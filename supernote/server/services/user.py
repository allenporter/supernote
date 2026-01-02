import datetime
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional

import jwt
from mashumaro.mixins.json import DataClassJSONMixin
from sqlalchemy import delete, func, select, update

from supernote.models.auth import LoginVO, UserVO
from supernote.models.user import (
    LoginRecordVO,
    RetrievePasswordDTO,
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

RANDOM_CODE_TTL = datetime.timedelta(minutes=5)


@dataclass
class SessionState(DataClassJSONMixin):
    token: str
    username: str
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
            stmt = select(UserDO).where(UserDO.username == account)
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    async def register(self, dto: UserRegisterDTO) -> UserDO:
        """Register a new user."""
        if not self._config.enable_registration:
            raise ValueError("Registration is disabled")

        if await self.check_user_exists(dto.email):
            raise ValueError("User already exists")

        # Hash password before storage.
        # Future improvement: Upgrade to stronger hashing (e.g., bcrypt/argon2).
        password_md5 = hashlib.md5(dto.password.encode()).hexdigest()

        async with self._session_manager.session() as session:
            new_user = UserDO(
                username=dto.email,
                email=dto.email,
                password_md5=password_md5,
                display_name=dto.user_name,
                is_active=True,
            )
            session.add(new_user)
            await session.commit()
            await session.refresh(new_user)
            return new_user

    async def unregister(self, account: str) -> None:
        """Delete a user."""
        if not self._config.enable_registration:
            raise ValueError("Registration is disabled")
        async with self._session_manager.session() as session:
            # Find user ID first
            stmt = select(UserDO).where(UserDO.username == account)
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
            stmt = select(UserDO).where(UserDO.username == account)
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
        ip: Optional[str] = None,
        login_method: Optional[str] = None,
    ) -> LoginVO | None:
        user = await self._get_user_do(account)
        if not user or not user.is_active:
            return None

        if not await self.verify_login_hash(account, password_hash, timestamp):
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
                username=username,
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
            country_code="1",
            total_capacity=user.total_capacity,
            file_server="0",
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
        new_md5 = hashlib.md5(dto.password.encode()).hexdigest()

        async with self._session_manager.session() as session:
            await session.execute(
                update(UserDO)
                .where(UserDO.username == account)
                .values(password_md5=new_md5)
            )
            await session.commit()
        return True

    async def update_email(self, account: str, dto: UpdateEmailDTO) -> bool:
        """Update user email."""
        async with self._session_manager.session() as session:
            await session.execute(
                update(UserDO).where(UserDO.username == account).values(email=dto.email)
            )
            await session.commit()
        return True

    async def retrieve_password(self, dto: RetrievePasswordDTO) -> bool:
        """Retrieve/Reset password."""
        # Find user by alias (email/phone/username) and reset password.
        target = dto.email or dto.telephone
        if not target:
            return False

        new_md5 = hashlib.md5(dto.password.encode()).hexdigest()

        async with self._session_manager.session() as session:
            # Find user
            stmt = select(UserDO).where(
                (UserDO.email == target)
                | (UserDO.phone == target)
                | (UserDO.username == target)
            )
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                return False

            user.password_md5 = new_md5
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
                    user_name=user.username,
                    create_time=r.create_time,
                    equipment=r.equipment,
                    ip=r.ip,
                    login_method=r.login_method,
                )
                for r in records
            ]

            return vos, total
