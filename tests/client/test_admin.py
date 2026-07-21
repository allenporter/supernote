"""Tests for supernote.client.admin module."""

from aiohttp import web
from pytest_aiohttp import AiohttpClient

from supernote.client import Client
from supernote.client.admin import AdminClient
from supernote.models.system import QueueStatusVO


async def handler_csrf(request: web.Request) -> web.Response:
    return web.Response(text="ok", headers={"X-XSRF-TOKEN": "test-token"})


async def test_admin_client_endpoints(aiohttp_client: AiohttpClient) -> None:
    """Test all AdminClient endpoints."""
    recorded_requests = []

    async def handler_register(request: web.Request) -> web.Response:
        data = await request.json()
        recorded_requests.append(("register", data))
        return web.json_response({"success": True})

    async def handler_unregister(request: web.Request) -> web.Response:
        recorded_requests.append(("unregister", None))
        return web.json_response({"success": True})

    async def handler_password(request: web.Request) -> web.Response:
        data = await request.json()
        recorded_requests.append(("password", data))
        return web.json_response({"success": True})

    async def handler_email(request: web.Request) -> web.Response:
        data = await request.json()
        recorded_requests.append(("email", data))
        return web.json_response({"success": True})

    async def handler_retrieve_password(request: web.Request) -> web.Response:
        data = await request.json()
        recorded_requests.append(("retrieve_password", data))
        return web.json_response({"success": True})

    async def handler_admin_users(request: web.Request) -> web.Response:
        data = await request.json()
        recorded_requests.append(("admin_create_user", data))
        return web.json_response({"success": True})

    async def handler_admin_users_password(request: web.Request) -> web.Response:
        data = await request.json()
        recorded_requests.append(("admin_reset_password", data))
        return web.json_response({"success": True})

    async def handler_queue_stop(request: web.Request) -> web.Response:
        recorded_requests.append(("queue_stop", None))
        return web.json_response({"success": True})

    async def handler_queue_start(request: web.Request) -> web.Response:
        recorded_requests.append(("queue_start", None))
        return web.json_response({"success": True})

    async def handler_queue_status(request: web.Request) -> web.Response:
        recorded_requests.append(("queue_status", None))
        return web.json_response(
            {
                "success": True,
                "paused": False,
                "queueSize": 5,
                "processingFiles": [1, 2],
            }
        )

    async def handler_reprocess(request: web.Request) -> web.Response:
        data = await request.json()
        recorded_requests.append(("reprocess", data))
        return web.json_response({"success": True})

    app = web.Application()
    app.router.add_get("/api/csrf", handler_csrf)
    app.router.add_post("/api/user/register", handler_register)
    app.router.add_post("/api/user/unregister", handler_unregister)
    app.router.add_put("/api/user/password", handler_password)
    app.router.add_put("/api/user/email", handler_email)
    app.router.add_post(
        "/api/official/user/retrieve/password", handler_retrieve_password
    )
    app.router.add_post("/api/admin/users", handler_admin_users)
    app.router.add_post("/api/admin/users/password", handler_admin_users_password)
    app.router.add_post("/api/admin/queue/stop", handler_queue_stop)
    app.router.add_post("/api/admin/queue/start", handler_queue_start)
    app.router.add_get("/api/admin/queue/status", handler_queue_status)
    app.router.add_post("/api/admin/reprocess", handler_reprocess)

    test_client = await aiohttp_client(app)
    base_url = str(test_client.make_url(""))

    client = Client(test_client.session, host=base_url)
    admin = AdminClient(client)

    # 1. register
    await admin.register("user@example.com", "pass123", "User Name")
    req, data = recorded_requests[-1]
    assert req == "register"
    assert data["email"] == "user@example.com"
    assert data["password"] == "pass123"
    assert data["userName"] == "User Name"

    # 2. unregister
    await admin.unregister()
    req, data = recorded_requests[-1]
    assert req == "unregister"

    # 3. update_password
    await admin.update_password("newpass123")
    req, data = recorded_requests[-1]
    assert req == "password"
    assert data["password"] == "newpass123"

    # 4. update_email
    await admin.update_email("newemail@example.com")
    req, data = recorded_requests[-1]
    assert req == "email"
    assert data["email"] == "newemail@example.com"

    # 5. retrieve_password
    await admin.retrieve_password("user@example.com", "resetpass")
    req, data = recorded_requests[-1]
    assert req == "retrieve_password"
    assert data["email"] == "user@example.com"
    assert data["password"] == "resetpass"

    # 6. admin_create_user
    await admin.admin_create_user("adminuser@example.com", "adminpass", "Admin User")
    req, data = recorded_requests[-1]
    assert req == "admin_create_user"
    assert data["email"] == "adminuser@example.com"
    assert data["password"] == "adminpass"

    # 7. admin_reset_password
    await admin.admin_reset_password("target@example.com", "md5hash123")
    req, data = recorded_requests[-1]
    assert req == "admin_reset_password"
    assert data["email"] == "target@example.com"
    assert data["password"] == "md5hash123"

    # 8. stop_queue
    await admin.stop_queue()
    req, data = recorded_requests[-1]
    assert req == "queue_stop"

    # 9. start_queue
    await admin.start_queue()
    req, data = recorded_requests[-1]
    assert req == "queue_start"

    # 10. get_queue_status
    status = await admin.get_queue_status()
    req, data = recorded_requests[-1]
    assert req == "queue_status"
    assert isinstance(status, QueueStatusVO)
    assert status.success is True
    assert status.paused is False
    assert status.queue_size == 5
    assert status.processing_files == [1, 2]

    # 11. admin_reprocess without file_id
    await admin.admin_reprocess("ocr")
    req, data = recorded_requests[-1]
    assert req == "reprocess"
    assert data == {"task_type": "ocr"}

    # 12. admin_reprocess with file_id
    await admin.admin_reprocess("transcribe", file_id=42)
    req, data = recorded_requests[-1]
    assert req == "reprocess"
    assert data == {"task_type": "transcribe", "file_id": 42}
