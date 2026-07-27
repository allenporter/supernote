import logging

from supernote.client.client import Client
from supernote.models.base import BaseResponse
from supernote.models.system import QueueStatusVO
from supernote.models.user import (
    RetrievePasswordDTO,
    UpdateEmailDTO,
    UpdatePasswordDTO,
    UserRegisterDTO,
)

logger = logging.getLogger(__name__)


class AdminClient:
    """Client for administrative tasks (User Management)."""

    def __init__(self, client: Client) -> None:
        """Initialize with an existing client instance."""
        self.client = client

    async def register(
        self, email: str, password: str, username: str | None = None
    ) -> None:
        """Register a new user."""
        dto = UserRegisterDTO(email=email, password=password, user_name=username)
        await self.client.post_json(
            "/api/user/register", BaseResponse, json=dto.to_dict()
        )
        logger.info(f"Registered user {email}")

    async def unregister(self) -> None:
        """Delete currently logged in user."""
        await self.client.post_json("/api/user/unregister", BaseResponse)
        logger.info("Unregistered user")

    async def update_password(self, new_password: str) -> None:
        """Update password for currently logged in user."""
        dto = UpdatePasswordDTO(password=new_password)
        await self.client.put_json(
            "/api/user/password", BaseResponse, json=dto.to_dict()
        )
        logger.info("Password updated")

    async def update_email(self, new_email: str) -> None:
        """Update email for currently logged in user."""
        dto = UpdateEmailDTO(email=new_email)
        await self.client.put_json("/api/user/email", BaseResponse, json=dto.to_dict())
        logger.info("Email updated")

    async def retrieve_password(self, email: str, new_password: str) -> None:
        """Reset password (public endpoint)."""
        dto = RetrievePasswordDTO(email=email, password=new_password)
        await self.client.post_json(
            "/api/official/user/retrieve/password", BaseResponse, json=dto.to_dict()
        )
        logger.info(f"Password reset for {email}")

    async def admin_create_user(
        self, email: str, password: str, username: str | None = None
    ) -> None:
        """Register a new user through the admin API."""
        dto = UserRegisterDTO(email=email, password=password, user_name=username)
        await self.client.post_json(
            "/api/admin/users", BaseResponse, json=dto.to_dict()
        )
        logger.info(f"Registered user {email}")

    async def admin_reset_password(self, email: str, password_md5: str) -> None:
        """Force reset user password through admin API."""
        await self.client.post_json(
            "/api/admin/users/password",
            BaseResponse,
            json={"email": email, "password": password_md5},
        )
        logger.info(f"Password reset for {email}")

    async def stop_queue(self) -> None:
        """Stop/pause the queue processing."""
        await self.client.post_json("/api/admin/queue/stop", BaseResponse)
        logger.info("Stopped/paused background queue processing")

    async def start_queue(self) -> None:
        """Start/resume the queue processing."""
        await self.client.post_json("/api/admin/queue/start", BaseResponse)
        logger.info("Started/resumed background queue processing")

    async def get_queue_status(self) -> QueueStatusVO:
        """Get the background queue processing status."""
        return await self.client.get_json("/api/admin/queue/status", QueueStatusVO)

    async def admin_reprocess(self, task_type: str, file_id: int | None = None) -> None:
        """Force reprocessing of notes by clearing task states on the server."""
        payload: dict = {"task_type": task_type}
        if file_id is not None:
            payload["file_id"] = file_id

        await self.client.post_json(
            "/api/admin/reprocess",
            BaseResponse,
            json=payload,
        )
        logger.info(f"Triggered reprocessing of '{task_type}' tasks")
