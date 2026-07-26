import hashlib

import pytest

from supernote.models.user import UserRegisterDTO
from supernote.server.services.user import UserService


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

    pw_md5 = hashlib.md5("password".encode()).hexdigest()
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

    pw_md5 = hashlib.md5("password".encode()).hexdigest()
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
