import hashlib

import jwt

from supernote.models.auth import Equipment
from supernote.models.user import UserRegisterDTO
from supernote.server.services.user import UserService
from supernote.server.utils.hashing import hash_with_salt


async def test_token_expiration_by_equipment(user_service: UserService) -> None:
    """Verify that token expiration depends on equipment type."""
    email = "exp_test@example.com"
    pw_md5 = hashlib.md5("password123".encode()).hexdigest()
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
