import logging

from supernote.client.client import Client
from supernote.models.auth import UserVO
from supernote.models.base import BaseResponse
from supernote.models.extended import SystemTaskListVO
from supernote.models.system import IntegrityReportVO, QueueStatusVO
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

    async def clear_account(self, *, confirm: bool = False) -> None:
        """Permanently delete the currently logged in user account and all cloud content.

        WARNING: This permanently and irreversibly deletes the user account and all
        associated files, blobs, recycle bin contents, summaries, schedule tasks,
        device bindings, and active sessions on the server.

        Args:
            confirm: Must be explicitly set to True to confirm permanent account and
                content deletion.
        """
        if confirm is not True:
            raise ValueError(
                "clear_account permanently deletes the user account and all cloud "
                "content. Pass confirm=True to proceed."
            )
        await self.client.post_json("/api/user/account/clear", BaseResponse)
        logger.info("Cleared user account")

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

    async def list_users(self) -> list[UserVO]:
        """List all users through the admin API."""
        resp = await self.client.get("/api/admin/users")
        data = await resp.json()
        return [UserVO.from_dict(item) for item in data]

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

    async def verify_integrity(
        self,
        user_id: int,
        file_id: int | None = None,
    ) -> IntegrityReportVO:
        """Verify VFS and blob storage integrity for a user."""
        params: dict[str, int] = {"user_id": user_id}
        if file_id is not None:
            params["file_id"] = file_id
        return await self.client.get_json(
            "/api/admin/integrity",
            IntegrityReportVO,
            params=params,
        )

    async def list_tasks(
        self,
        status: str | None = None,
        file_id: int | None = None,
        task_type: str | None = None,
        limit: int = 100,
    ) -> SystemTaskListVO:
        """List system processing tasks with optional filters."""
        params: dict[str, str | int] = {"limit": limit}
        if status is not None:
            params["status"] = status
        if file_id is not None:
            params["file_id"] = file_id
        if task_type is not None:
            params["task_type"] = task_type
        return await self.client.get_json(
            "/api/admin/tasks",
            SystemTaskListVO,
            params=params,
        )
