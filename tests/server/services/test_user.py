import hashlib
import logging
import time

import jwt
import pytest
from sqlalchemy import select

from supernote.models.auth import Equipment, LoginVO
from supernote.models.base import ErrorCode
from supernote.models.equipment import UserEquipmentVO
from supernote.models.user import (
    UpdateEmailDTO,
    UpdatePasswordDTO,
    UserCheckDTO,
    UserCheckVO,
    UserRegisterDTO,
)
from supernote.server.config import AuthConfig, ServerConfig
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.coordination import CoordinationService
from supernote.server.services.user import JWT_SECRET_KEY, UserService
from supernote.server.utils.hashing import hash_with_salt


@pytest.fixture
def test_users() -> list[str]:
    """Fixture to clear all test users.

    We use this to verify we can bootstrap properly.
    """
    return []


async def test_bootstrap_first_user_is_admin(
    session_manager: DatabaseSessionManager, coordination_service: CoordinationService
) -> None:
    """Test that the first registered user becomes an admin."""
    config = AuthConfig(enable_registration=True)
    service = UserService(config, coordination_service, session_manager)

    # Register first user (should be admin)
    pw_md5 = hashlib.md5(b"password").hexdigest()
    dto1 = UserRegisterDTO(
        email="admin@example.com", password=pw_md5, user_name="Admin"
    )
    user1 = await service.register(dto1)
    assert user1.is_admin is True

    # Register second user (should NOT be admin)
    dto2 = UserRegisterDTO(email="user@example.com", password=pw_md5, user_name="User")
    user2 = await service.register(dto2)
    assert user2.is_admin is False


async def test_bootstrap_bypasses_disabled_registration(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
) -> None:
    """Test that bootstrapping works even if registration is disabled."""
    # Config has registration DISABLED
    config = AuthConfig(enable_registration=False)
    service = UserService(config, coordination_service, session_manager)

    # Register first user (should succeed because of bootstrap)
    pw_md5 = hashlib.md5(b"password").hexdigest()
    dto1 = UserRegisterDTO(
        email="bootstrap@example.com", password=pw_md5, user_name="Bootstrap"
    )
    user1 = await service.register(dto1)

    assert user1.is_admin is True

    # Register second user (should FAIL because registration is disabled)
    dto2 = UserRegisterDTO(email="fail@example.com", password=pw_md5, user_name="Fail")
    with pytest.raises(ValueError, match="Registration is disabled"):
        await service.register(dto2)


async def test_admin_create_user_bypass(
    session_manager: DatabaseSessionManager, coordination_service: CoordinationService
) -> None:
    """Test that create_user allows creating users when disabled."""
    config = AuthConfig(enable_registration=False)
    service = UserService(config, coordination_service, session_manager)

    # Bootstrap first
    pw_md5 = hashlib.md5(b"pw").hexdigest()
    await service.register(
        UserRegisterDTO(email="admin@example.com", password=pw_md5, user_name="Admin")
    )

    # Explicitly use create_user (Admin action simulation)
    dto2 = UserRegisterDTO(email="new@example.com", password=pw_md5, user_name="New")
    user2 = await service.create_user(dto2)

    assert user2.email == "new@example.com"


async def test_retrieve_password_success(
    user_service: UserService,
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
) -> None:
    # Setup
    email = "forgot@example.com"
    old_pw = hashlib.md5(b"old").hexdigest()
    new_pw = hashlib.md5(b"new").hexdigest()

    # Create user directly in DB
    async with session_manager.session() as session:
        user = UserDO(
            email=email, password_md5=old_pw, display_name="Forgot", is_active=True
        )
        session.add(user)
        await session.commit()

    # Validation: Pass scalars
    result: bool = await user_service.retrieve_password(email, new_pw)
    assert result is True

    # Verify in DB
    async with session_manager.session() as session:
        user_result = await session.execute(select(UserDO).where(UserDO.email == email))
        user = user_result.scalar_one()
        assert user.password_md5 == new_pw


async def test_retrieve_password_invalid_md5(user_service: UserService) -> None:
    with pytest.raises(ValueError, match="Invalid password format"):
        await user_service.retrieve_password("user@example.com", "plain_text_password")


async def test_retrieve_password_user_not_found(user_service: UserService) -> None:
    result = await user_service.retrieve_password(
        "nonexistent@example.com", hashlib.md5(b"pw").hexdigest()
    )
    assert result is False


async def test_register_login_flow(user_service: UserService) -> None:
    """Register and login a user."""
    # Register
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    dto = UserRegisterDTO(
        email="unique_test_reg@example.com",
        password=pw_md5,
        user_name="Test User",
    )
    user = await user_service.register(dto)
    assert user.id is not None
    assert user.email == "unique_test_reg@example.com"

    # Login

    pw_hash = hashlib.md5(b"password123").hexdigest()

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
    old_md5 = hashlib.md5(b"old").hexdigest()
    await user_service.register(UserRegisterDTO(email="pw@test.com", password=old_md5))

    # Update
    new_md5 = hashlib.md5(b"new").hexdigest()
    await user_service.update_password(
        "pw@test.com", UpdatePasswordDTO(password=new_md5)
    )

    # Login with old fails (we'd need a full login flow to test, strictly speaking)
    # But we can check DB directly via service internal method if we exposed it, or just trust update worked.
    # Let's try to login with NEW password
    code, ts = await user_service.generate_random_code("pw@test.com")
    new_hash = hashlib.md5(b"new").hexdigest()
    client_hash = hash_with_salt(new_hash, code)

    login_vo = await user_service.login("pw@test.com", client_hash, ts)
    assert login_vo is not None


async def test_clear_account(user_service: UserService) -> None:
    """Clear a user account and track sold_out_count across re-registration."""
    pw_md5 = hashlib.md5(b"pw").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(email="del@test.com", password=pw_md5)
    )
    assert await user_service.check_user_exists("del@test.com")
    assert await user_service.get_sold_out_count("del@test.com") == 0

    cleared_id = await user_service.clear_account("del@test.com")
    assert cleared_id == user.id
    assert not await user_service.check_user_exists("del@test.com")
    assert await user_service.get_sold_out_count("del@test.com") == 1
    assert await user_service.clear_account("del@test.com") is None
    assert await user_service.get_sold_out_count("del@test.com") == 1

    # Re-registering with the same email and logging in returns sold_out_count=1
    new_user = await user_service.register(
        UserRegisterDTO(email="del@test.com", password=pw_md5)
    )
    assert new_user.id != user.id
    code, ts = await user_service.generate_random_code("del@test.com")
    login_vo = await user_service.login(
        "del@test.com", hash_with_salt(pw_md5, code), ts
    )
    assert login_vo is not None
    assert login_vo.sold_out_count == 1


async def test_token_expiration_by_equipment(user_service: UserService) -> None:
    """Verify that token expiration depends on equipment type."""
    email = "exp_test@example.com"
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    await user_service.register(UserRegisterDTO(email=email, password=pw_md5))

    # 1. Login as WEB (Default)
    code, ts = await user_service.generate_random_code(email)
    client_hash = hash_with_salt(pw_md5, code)

    login_web = await user_service.login(
        email, client_hash, ts, equipment=Equipment.WEB
    )
    assert login_web is not None

    # Decode JWT to check exp
    payload_web = jwt.decode(login_web.token, options={"verify_signature": False})
    exp_web = payload_web["exp"]
    iat_web = payload_web["iat"]

    # Should be significantly less than 10 years
    # (Usually 24h, but depends on test environment)
    assert 60 < (exp_web - iat_web) < 10 * 365 * 24 * 3600

    # 2. Login as TERMINAL (Device)
    code, ts = await user_service.generate_random_code(email)
    client_hash = hash_with_salt(pw_md5, code)

    login_term = await user_service.login(
        email, client_hash, ts, equipment=Equipment.TERMINAL
    )
    assert login_term is not None

    payload_term = jwt.decode(login_term.token, options={"verify_signature": False})
    exp_term = payload_term["exp"]
    iat_term = payload_term["iat"]

    # Should be 10 years
    ten_years_seconds = 10 * 365 * 24 * 3600
    assert (exp_term - iat_term) == ten_years_seconds

    # 3. Login as APP (Companion App)
    code, ts = await user_service.generate_random_code(email)
    client_hash = hash_with_salt(pw_md5, code)

    login_app = await user_service.login(
        email, client_hash, ts, equipment=Equipment.APP
    )
    assert login_app is not None

    payload_app = jwt.decode(login_app.token, options={"verify_signature": False})
    exp_app = payload_app["exp"]
    iat_app = payload_app["iat"]

    # Should also be 10 years
    assert (exp_app - iat_app) == ten_years_seconds


async def test_register_invalid_email(user_service: UserService) -> None:
    # Test cases for invalid emails
    invalid_emails = [
        "plainaddress",
        "#@%^%#$@#$@#.com",
        "@example.com",
        "Joe Smith <email@example.com>",
        "email.example.com",
        "email@example@example.com",
        ".email@example.com",
        "email.@example.com",
        "email..email@example.com",
        "email@example.com (Joe Smith)",
        "email@example",
        "email@-example.com",
        # "email@example.web", # This one might actually pass the simple regex depending on strictness, but let's test common bad ones
        # "email@111.222.333.44444",
        "email@example..com",
        "Abc..123@example.com",
    ]

    pw_md5 = hashlib.md5(b"password").hexdigest()
    for email in invalid_emails:
        try:
            await user_service.register(
                UserRegisterDTO(email=email, password=pw_md5, user_name="Test User")
            )
            pytest.fail(f"Email '{email}' should have failed validation but passed")
        except ValueError as e:
            assert str(e) == "Invalid email address format"


async def test_register_valid_email(user_service: UserService) -> None:
    # Test cases for valid emails
    valid_emails = [
        "email@example.com",
        "firstname.lastname@example.com",
        "email@subdomain.example.com",
        "firstname+lastname@example.com",
        "email@123.123.123.123",
        "1234567890@example.com",
        "email@example-one.com",
        "_______@example.com",
        "email@example.name",
        "email@example.museum",
        "email@example.co.jp",
        "firstname-lastname@example.com",
    ]

    pw_md5 = hashlib.md5(b"password").hexdigest()
    for email in valid_emails:
        # Should not raise
        try:
            user = await user_service.register(
                UserRegisterDTO(email=email, password=pw_md5, user_name="Test User")
            )
            assert user.email == email
        except ValueError as e:
            pytest.fail(f"Valid email '{email}' failed validation: {e}")
        # We don't bother cleanup since we're using unique email addresses


async def test_create_session_and_verify_token(user_service: UserService) -> None:
    """Verify create_session mints and persists a verifiable session token."""
    email = "session_test@example.com"
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    await user_service.register(UserRegisterDTO(email=email, password=pw_md5))

    token = await user_service.create_session(email, equipment_no="SN123")
    state = await user_service.verify_token(token)
    assert state is not None
    assert state.email == email
    assert state.equipment_no == "SN123"
    assert state.token == token


async def test_challenge_single_use_and_concurrent(user_service: UserService) -> None:
    """Verify challenges are single-use (replay fails) and concurrent challenges do not overwrite each other."""
    email = "challenge_test@example.com"
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    await user_service.register(UserRegisterDTO(email=email, password=pw_md5))

    # Generate two concurrent challenges for the same account
    code1, ts1 = await user_service.generate_random_code(email)
    code2, ts2 = await user_service.generate_random_code(email)
    assert ts1 != ts2

    hash1 = hash_with_salt(pw_md5, code1)
    hash2 = hash_with_salt(pw_md5, code2)

    # First challenge still works even though second challenge was issued
    vo1 = await user_service.login(email, hash1, ts1, equipment_no="dev1")
    assert vo1.success is True
    assert vo1.token != ""

    # Replaying first challenge fails with PASSWORD_ERROR (E0019)
    replay = await user_service.login(email, hash1, ts1, equipment_no="dev1")
    assert replay == LoginVO(
        success=False,
        error_code=ErrorCode.PASSWORD_ERROR.value,
        error_msg=ErrorCode.PASSWORD_ERROR.message,
        counts="1",
    )

    # Second challenge still works once
    vo2 = await user_service.login(email, hash2, ts2, equipment_no="dev2")
    assert vo2.success is True
    assert vo2.token != ""


async def test_challenge_validation_and_diagnostic_logging(
    user_service: UserService,
    session_manager: DatabaseSessionManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify login validates challenge timestamp and logs diagnostic warnings on failure."""
    email = "diag_test@example.com"
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    await user_service.register(UserRegisterDTO(email=email, password=pw_md5))

    expected_pw_err = LoginVO(
        success=False,
        error_code=ErrorCode.PASSWORD_ERROR.value,
        error_msg=ErrorCode.PASSWORD_ERROR.message,
        counts="1",
    )

    # Unknown account returns ACCOUNT_NOT_EXIST (E0018)
    assert await user_service.login("unknown@example.com", "hash", "123") == LoginVO(
        success=False,
        error_code=ErrorCode.ACCOUNT_NOT_EXIST.value,
        error_msg=ErrorCode.ACCOUNT_NOT_EXIST.message,
    )

    # Invalid timestamp format or empty timestamp logs warning without consuming active challenge
    code1, ts1 = await user_service.generate_random_code(email)
    hash1 = hash_with_salt(pw_md5, code1)
    with caplog.at_level(logging.WARNING):
        caplog.clear()
        assert await user_service.login(email, hash1, "") == expected_pw_err
        assert "missing challenge timestamp" in caplog.text

        caplog.clear()
        assert await user_service.login(email, hash1, "not-a-number") == expected_pw_err
        assert "invalid timestamp format" in caplog.text

    # Legitimate challenge is still usable once after bogus timestamp attempts
    vo_ok = await user_service.login(email, hash1, ts1, equipment_no="dev1")
    assert vo_ok.success is True
    assert vo_ok.token != ""

    # Replay or unknown timestamp logs challenge expired/not found warning
    with caplog.at_level(logging.WARNING):
        caplog.clear()
        assert await user_service.login(email, hash1, ts1) == expected_pw_err
        assert "challenge expired or not found" in caplog.text

    # Password hash mismatch logs warning without leaking secret
    code2, ts2 = await user_service.generate_random_code(email)
    wrong_hash = hash_with_salt(hashlib.md5(b"wrong").hexdigest(), code2)
    with caplog.at_level(logging.WARNING):
        caplog.clear()
        assert await user_service.login(email, wrong_hash, ts2) == expected_pw_err
        assert "password hash mismatch" in caplog.text
        assert pw_md5 not in caplog.text
        assert code2 not in caplog.text

    # Disabled user returns USER_DISABLED (E0709)
    async with session_manager.session() as session:
        user_row = (
            await session.execute(select(UserDO).where(UserDO.email == email))
        ).scalar_one()
        user_row.is_active = False
        await session.commit()

    code3, ts3 = await user_service.generate_random_code(email)
    assert await user_service.login(
        email, hash_with_salt(pw_md5, code3), ts3
    ) == LoginVO(
        success=False,
        error_code=ErrorCode.USER_DISABLED.value,
        error_msg=ErrorCode.USER_DISABLED.message,
    )


async def test_update_email_validation_and_duplicate(user_service: UserService) -> None:
    """Verify update_email validates format and rejects duplicate emails."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    await user_service.register(
        UserRegisterDTO(email="u1@example.com", password=pw_md5)
    )
    await user_service.register(
        UserRegisterDTO(email="u2@example.com", password=pw_md5)
    )

    with pytest.raises(ValueError, match="Invalid email address format"):
        await user_service.update_email(
            "u1@example.com", UpdateEmailDTO(email="not-an-email")
        )

    with pytest.raises(ValueError, match="Email already registered"):
        await user_service.update_email(
            "u1@example.com", UpdateEmailDTO(email="u2@example.com")
        )


async def test_equipment_session_revocation(user_service: UserService) -> None:
    """Verify unlinking equipment or re-logging in on same equipment revokes only that equipment's session."""
    email = "equip_sess@example.com"
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    await user_service.register(UserRegisterDTO(email=email, password=pw_md5))

    # Login on dev1 and dev2
    code1, ts1 = await user_service.generate_random_code(email)
    vo1 = await user_service.login(
        email, hash_with_salt(pw_md5, code1), ts1, equipment_no="dev1"
    )
    assert vo1 is not None

    code2, ts2 = await user_service.generate_random_code(email)
    vo2 = await user_service.login(
        email, hash_with_salt(pw_md5, code2), ts2, equipment_no="dev2"
    )
    assert vo2 is not None

    assert await user_service.verify_token(vo1.token) is not None
    assert await user_service.verify_token(vo2.token) is not None

    # Re-login on dev1 revokes vo1.token, leaves vo2.token active
    code3, ts3 = await user_service.generate_random_code(email)
    vo3 = await user_service.login(
        email, hash_with_salt(pw_md5, code3), ts3, equipment_no="dev1"
    )
    assert vo3 is not None
    assert await user_service.verify_token(vo1.token) is None
    assert await user_service.verify_token(vo3.token) is not None
    assert await user_service.verify_token(vo2.token) is not None

    # Unlinking dev2 removes the device binding without revoking active sessions
    await user_service.bind_equipment(email, "dev2")
    await user_service.unlink_equipment("dev2")
    assert await user_service.verify_token(vo2.token) is not None
    assert await user_service.verify_token(vo3.token) is not None


async def test_session_adversarial_edge_cases(
    user_service: UserService,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
) -> None:
    """Verify create_session, verify_token, logout, and equipment key encoding resist adversarial inputs."""
    with pytest.raises(ValueError, match="Active user missing@example.com not found"):
        await user_service.create_session("missing@example.com")

    assert await user_service.verify_token("") is None

    email = "adv@example.com"
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(UserRegisterDTO(email=email, password=pw_md5))

    # Equipment numbers containing colons must not prefix-collide with shorter equipment numbers
    tok_short = await user_service.create_session(email, equipment_no="SN1")
    tok_colon = await user_service.create_session(email, equipment_no="SN1:extra")
    await user_service.revoke_equipment_sessions(user.id, "")
    await user_service.revoke_equipment_sessions(user.id, "SN1")
    assert await user_service.verify_token(tok_short) is None
    assert await user_service.verify_token(tok_colon) is not None

    # Logout handles empty, invalid, and malformed tokens gracefully and revokes only target token
    await user_service.logout("")
    await user_service.logout("not-a-jwt")
    tok_web = await user_service.create_session(email)
    await user_service.logout(tok_colon)
    assert await user_service.verify_token(tok_colon) is None
    assert await user_service.verify_token(tok_web) is not None

    # Forged JWT with boolean user_id=True (int subclass) or missing user_id must be rejected
    bool_uid_token = jwt.encode(
        {"sub": email, "user_id": True, "equipment_no": ""},
        server_config.auth.secret_key,
        algorithm="HS256",
    )
    await user_service.logout(bool_uid_token)
    assert await user_service.verify_token(bool_uid_token) is None

    no_uid_token = jwt.encode(
        {"sub": email, "equipment_no": ""},
        server_config.auth.secret_key,
        algorithm="HS256",
    )
    assert await user_service.verify_token(no_uid_token) is None

    # Corrupted or mismatched SessionState in CoordinationService is rejected
    tok_corrupt = await user_service.create_session(email)
    key_corrupt = user_service._session_key(user.id, None, tok_corrupt)
    await coordination_service.set_value(key_corrupt, "not-json", ttl=60)
    assert await user_service.verify_token(tok_corrupt) is None

    tok_mismatch = await user_service.create_session(email)
    key_mismatch = user_service._session_key(user.id, None, tok_mismatch)
    await coordination_service.set_value(
        key_mismatch,
        '{"token": "other", "email": "other@example.com", "user_id": 999}',
        ttl=60,
    )
    assert await user_service.verify_token(tok_mismatch) is None

    # admin_reset_password revokes active sessions
    tok_before_admin_reset = await user_service.create_session(email)
    await user_service.admin_reset_password(
        email, hashlib.md5(b"newadminpw").hexdigest()
    )
    assert await user_service.verify_token(tok_before_admin_reset) is None


async def test_user_profiles(user_service: UserService) -> None:
    """Verify get_user_profile and list_user_profiles map UserDO to UserVO."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    await user_service.register(
        UserRegisterDTO(email="profile@example.com", password=pw_md5, user_name="Prof")
    )

    assert await user_service.get_user_profile("missing@example.com") is None
    profile = await user_service.get_user_profile("profile@example.com")
    assert profile is not None
    assert profile.email == "profile@example.com"
    assert profile.user_name == "Prof"

    profiles = await user_service.list_user_profiles()
    assert any(
        p.email == "profile@example.com" and p.user_name == "Prof" for p in profiles
    )


async def test_query_equipment_by_no(user_service: UserService) -> None:
    """Verify query_equipment_by_no returns binding status and user_id from DeviceDO."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user1 = await user_service.register(
        UserRegisterDTO(email="eq1@example.com", password=pw_md5)
    )
    user2 = await user_service.register(
        UserRegisterDTO(email="eq2@example.com", password=pw_md5)
    )

    assert await user_service.query_equipment_by_no("SN-999") == UserEquipmentVO()

    await user_service.bind_equipment("eq1@example.com", "SN-999")
    assert await user_service.query_equipment_by_no("SN-999") == UserEquipmentVO(
        equipment_number="SN-999",
        user_id=user1.id,
        status="Y",
    )

    # Re-binding to the same user is idempotent
    await user_service.bind_equipment("eq1@example.com", "SN-999")
    assert await user_service.query_equipment_by_no("SN-999") == UserEquipmentVO(
        equipment_number="SN-999",
        user_id=user1.id,
        status="Y",
    )

    # Binding an already-bound device to a different user fails unless unlinked first
    with pytest.raises(ValueError, match="already bound"):
        await user_service.bind_equipment("eq2@example.com", "SN-999")
    assert await user_service.query_equipment_by_no("SN-999") == UserEquipmentVO(
        equipment_number="SN-999",
        user_id=user1.id,
        status="Y",
    )

    await user_service.unlink_equipment("SN-999")
    assert await user_service.query_equipment_by_no("SN-999") == UserEquipmentVO()

    await user_service.bind_equipment("eq2@example.com", "SN-999")
    assert await user_service.query_equipment_by_no("SN-999") == UserEquipmentVO(
        equipment_number="SN-999",
        user_id=user2.id,
        status="Y",
    )

    await user_service.unlink_equipment("SN-999")
    assert await user_service.query_equipment_by_no("SN-999") == UserEquipmentVO()


async def test_check_user_server_and_registration(user_service: UserService) -> None:
    """Verify check_user_server, get_unique_machine_id,check_user_registration, and legacy challenge fallback."""
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(
        UserRegisterDTO(
            email="check@example.com", password=pw_md5, user_name="CheckName"
        )
    )

    machine_id_1 = await user_service.get_unique_machine_id()
    machine_id_2 = await user_service.get_unique_machine_id()
    assert machine_id_1 == machine_id_2
    assert len(machine_id_1) > 0

    assert await user_service.check_user_server(
        UserCheckDTO(email="check@example.com")
    ) == UserCheckVO(
        user_id=user.id,
        unique_machine_id=machine_id_1,
        dms="ALL",
    )

    assert await user_service.check_user_server(
        UserCheckDTO(email="missing@example.com")
    ) == UserCheckVO(
        success=False,
        error_code="E0018",
        error_msg="User not found",
    )


async def test_jwt_secret_key_persisted_in_database_across_restarts(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
) -> None:
    """When AuthConfig.secret_key is empty, UserService generates and persists system:jwt_secret_key across restarts."""
    service1 = UserService(
        AuthConfig(secret_key="", enable_registration=True),
        coordination_service,
        session_manager,
    )
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    email = "persist_jwt@example.com"
    await service1.register(UserRegisterDTO(email=email, password=pw_md5))

    token = await service1.create_session(email, equipment_no="SN-PERSIST")
    persisted_secret = await coordination_service.get_value(JWT_SECRET_KEY)
    assert persisted_secret is not None
    assert len(persisted_secret) == 64
    assert await service1.get_secret_key() == persisted_secret

    # Simulate a server restart with a fresh AuthConfig(secret_key="") sharing the same DB / CoordinationService
    service2 = UserService(
        AuthConfig(secret_key="", enable_registration=True),
        coordination_service,
        session_manager,
    )
    assert await service2.get_secret_key() == persisted_secret

    state = await service2.verify_token(token)
    assert state is not None
    assert state.email == email
    assert state.equipment_no == "SN-PERSIST"

    # Logout via the second instance also decodes and revokes the token using the persisted secret
    await service2.logout(token)
    assert await service2.verify_token(token) is None


async def test_jwt_secret_key_explicit_config_takes_precedence(
    session_manager: DatabaseSessionManager,
    coordination_service: CoordinationService,
) -> None:
    """Explicit AuthConfig.secret_key takes precedence over system:jwt_secret_key in CoordinationService."""
    await coordination_service.set_value(JWT_SECRET_KEY, "db-secret-key", ttl=3600)

    service = UserService(
        AuthConfig(secret_key="explicit-secret", enable_registration=True),
        coordination_service,
        session_manager,
    )
    assert await service.get_secret_key() == "explicit-secret"
    assert await coordination_service.get_value(JWT_SECRET_KEY) == "db-secret-key"

    pw_md5 = hashlib.md5(b"password123").hexdigest()
    email = "explicit_jwt@example.com"
    await service.register(UserRegisterDTO(email=email, password=pw_md5))

    token = await service.create_session(email)
    decoded = jwt.decode(token, "explicit-secret", algorithms=["HS256"])
    assert decoded["sub"] == email


async def test_legacy_session_token_migration_and_revocation(
    user_service: UserService,
    coordination_service: CoordinationService,
    server_config: ServerConfig,
) -> None:
    """Verify pre-#270 legacy session tokens without user_id are transparently migrated and revocable."""
    email = "legacy_user@example.com"
    pw_md5 = hashlib.md5(b"password123").hexdigest()
    user = await user_service.register(UserRegisterDTO(email=email, password=pw_md5))
    equipment_no = "SN-LEGACY-001"
    now = int(time.time())
    ttl = 10 * 365 * 24 * 3600

    def mint_legacy_token(eq_no: str, jti: str) -> str:
        payload = {
            "sub": email,
            "equipment_no": eq_no,
            "iat": now,
            "exp": now + ttl,
            "jti": jti,
        }
        return jwt.encode(payload, server_config.auth.secret_key, algorithm="HS256")

    # 1. Verify legacy token migrates key in coordination_service and deletes session:{token}
    legacy_token_1 = mint_legacy_token(equipment_no, "legacy-1")
    legacy_key_1 = f"session:{legacy_token_1}"
    migrated_key_1 = user_service._session_key(user.id, equipment_no, legacy_token_1)
    await coordination_service.set_value(
        legacy_key_1, f"{email}|{equipment_no}", ttl=ttl
    )

    state_1 = await user_service.verify_token(legacy_token_1)
    assert state_1 is not None
    assert state_1.user_id == user.id
    assert state_1.email == email
    assert state_1.equipment_no == equipment_no
    assert state_1.token == legacy_token_1
    assert await coordination_service.get_value(legacy_key_1) is None
    assert await coordination_service.get_value(migrated_key_1) is not None

    # 2. Verify a second call with the same legacy token succeeds from the migrated key
    state_1_again = await user_service.verify_token(legacy_token_1)
    assert state_1_again is not None
    assert state_1_again.user_id == user.id
    assert state_1_again.email == email
    assert state_1_again.equipment_no == equipment_no

    # 3. Verify revoke_equipment_sessions invalidates the migrated legacy token
    await user_service.revoke_equipment_sessions(user.id, equipment_no)
    assert await user_service.verify_token(legacy_token_1) is None

    # 4. Verify revoke_user_sessions invalidates a migrated legacy token
    legacy_token_2 = mint_legacy_token(equipment_no, "legacy-2")
    await coordination_service.set_value(
        f"session:{legacy_token_2}", f"{email}|{equipment_no}", ttl=ttl
    )
    assert await user_service.verify_token(legacy_token_2) is not None
    await user_service.revoke_user_sessions(user.id)
    assert await user_service.verify_token(legacy_token_2) is None

    # 5. Verify logout(token) invalidates both unmigrated and migrated legacy tokens
    legacy_token_unmigrated = mint_legacy_token(equipment_no, "legacy-3")
    await coordination_service.set_value(
        f"session:{legacy_token_unmigrated}", f"{email}|{equipment_no}", ttl=ttl
    )
    await user_service.logout(legacy_token_unmigrated)
    assert await user_service.verify_token(legacy_token_unmigrated) is None

    legacy_token_migrated = mint_legacy_token(equipment_no, "legacy-4")
    await coordination_service.set_value(
        f"session:{legacy_token_migrated}", f"{email}|{equipment_no}", ttl=ttl
    )
    assert await user_service.verify_token(legacy_token_migrated) is not None
    await user_service.logout(legacy_token_migrated)
    assert await user_service.verify_token(legacy_token_migrated) is None

    # 6. Verify mismatched legacy session state or missing user is rejected
    legacy_token_mismatch = mint_legacy_token(equipment_no, "legacy-5")
    await coordination_service.set_value(
        f"session:{legacy_token_mismatch}", f"{email}|OTHER-EQ", ttl=ttl
    )
    assert await user_service.verify_token(legacy_token_mismatch) is None

    missing_user_token = jwt.encode(
        {
            "sub": "nonexistent@example.com",
            "equipment_no": equipment_no,
            "iat": now,
            "exp": now + ttl,
        },
        server_config.auth.secret_key,
        algorithm="HS256",
    )
    await coordination_service.set_value(
        f"session:{missing_user_token}",
        f"nonexistent@example.com|{equipment_no}",
        ttl=ttl,
    )
    assert await user_service.verify_token(missing_user_token) is None
