import hashlib

from supernote.models.user import UpdatePasswordDTO, UserRegisterDTO
from supernote.server.services.user import UserService
from supernote.server.utils.hashing import hash_with_salt


async def test_register_login_flow(user_service: UserService) -> None:
    """Register and login a user."""
    # Register
    pw_md5 = hashlib.md5("password123".encode()).hexdigest()
    dto = UserRegisterDTO(
        email="unique_test_reg@example.com",
        password=pw_md5,
        user_name="Test User",
    )
    user = await user_service.register(dto)
    assert user.id is not None
    assert user.email == "unique_test_reg@example.com"

    # Login

    pw_hash = hashlib.md5("password123".encode()).hexdigest()

    # Need to mock the challenge flow
    code, ts = await user_service.generate_random_code("unique_test_reg@example.com")

    # Client logic: hash(md5(pw), code)
    client_hash = hash_with_salt(pw_hash, code)
    login_vo = await user_service.login(
        "unique_test_reg@example.com",
        client_hash,
        ts,
        equipment_no="dev1",
        ip="127.0.0.1",
        login_method="2",
    )
    assert login_vo is not None
    assert login_vo.token is not None

    # Verify records
    records, total = await user_service.query_login_records(
        "unique_test_reg@example.com", 1, 10
    )
    assert total == 1
    assert records[0].ip == "127.0.0.1"


async def test_update_password(user_service: UserService) -> None:
    """Update a user's password."""
    # Register
    # Register
    old_md5 = hashlib.md5("old".encode()).hexdigest()
    await user_service.register(UserRegisterDTO(email="pw@test.com", password=old_md5))

    # Update
    new_md5 = hashlib.md5("new".encode()).hexdigest()
    await user_service.update_password(
        "pw@test.com", UpdatePasswordDTO(password=new_md5)
    )

    # Login with old fails (we'd need a full login flow to test, strictly speaking)
    # But we can check DB directly via service internal method if we exposed it, or just trust update worked.
    # Let's try to login with NEW password
    code, ts = await user_service.generate_random_code("pw@test.com")
    new_hash = hashlib.md5("new".encode()).hexdigest()
    client_hash = hash_with_salt(new_hash, code)

    login_vo = await user_service.login("pw@test.com", client_hash, ts)
    assert login_vo is not None


async def test_unregister(user_service: UserService) -> None:
    """Unregister a user."""
    pw_md5 = hashlib.md5("pw".encode()).hexdigest()
    await user_service.register(UserRegisterDTO(email="del@test.com", password=pw_md5))
    assert await user_service.check_user_exists("del@test.com")

    await user_service.unregister("del@test.com")
    assert not await user_service.check_user_exists("del@test.com")
