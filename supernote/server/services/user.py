import secrets
import time
import logging
from typing import Optional
from ..models.auth import UserVO

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self):
        # In a real implementation, we would inject a repository here
        pass

    def check_user_exists(self, account: str) -> bool:
        """Check if a user exists."""
        # For now, we assume all users exist
        return True

    def generate_random_code(self, account: str) -> tuple[str, str]:
        """Generate a random code for login challenge."""
        random_code = secrets.token_hex(4)  # 8 chars
        timestamp = str(int(time.time() * 1000))
        # In a real implementation, we should store this code associated with the account/timestamp
        # to verify the login hash later.
        return random_code, timestamp

    def login(
        self,
        account: str,
        password_hash: str,
        timestamp: str,
        equipment_no: Optional[str] = None,
    ) -> str:
        """
        Login user and return a token.

        :param account: User account (email/phone)
        :param password_hash: Hashed password provided by client
        :param timestamp: Timestamp used in hash
        :param equipment_no: Equipment number (optional)
        :return: JWT token
        """
        # In a real implementation, we would:
        # 1. Retrieve the stored random code for this account.
        # 2. Verify the password hash: sha256(sha256(real_password) + random_code + timestamp)
        # 3. Generate a real JWT signed with a secret key.

        token = f"eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.{secrets.token_urlsafe(32)}.{secrets.token_urlsafe(32)}"
        return token

    def get_user_profile(self, account: str) -> UserVO:
        """Get user profile."""
        return UserVO(
            user_name="Supernote User",
            email=account if "@" in account else "test@example.com",
            phone="" if "@" in account else account,
            country_code="1",
            total_capacity="25485312",
            file_server="0",  # 0 for ufile (or local?), 1 for aws
            avatars_url="",
            birthday="",
            sex="",
        )

    def bind_equipment(self, account: str, equipment_no: str) -> bool:
        """Bind a device to the user account."""
        logger.info(f"Binding equipment {equipment_no} to user {account}")
        return True

    def unlink_equipment(self, equipment_no: str) -> bool:
        """Unlink a device."""
        logger.info(f"Unlinking equipment {equipment_no}")
        return True
