import datetime

import freezegun
import pytest

from supernote.server.exceptions import InvalidSignature
from supernote.server.utils.url_signer import UrlSigner


@pytest.fixture
def signer() -> UrlSigner:
    """Create a UrlSigner instance for testing."""
    return UrlSigner("test-secret-key-32-characters-long!!")


async def test_sign_and_verify(signer: UrlSigner) -> None:
    """Test that signing and verification work."""
    path = "/test/path"
    signed_url = await signer.sign(path)

    # Verify using full URL
    payload = await signer.verify(signed_url)
    assert payload["path"] == path


async def test_verify_preserves_query(signer: UrlSigner) -> None:
    """Test that query parameters are preserved."""
    path = "/api/resource?foo=bar"
    signed_url = await signer.sign(path)
    payload = await signer.verify(signed_url)
    assert payload["path"] == path


async def test_verify_failure_tampered_url(signer: UrlSigner) -> None:
    """Test that verification fails for tampered URLs."""
    path = "/original"
    signed_url = await signer.sign(path)

    # Tamper with the path part of the URL (e.g. user changes /original to /hacked)
    tampered_url = signed_url.replace("/original", "/hacked")

    with pytest.raises(InvalidSignature, match="Signed path mismatch"):
        await signer.verify(tampered_url)


async def test_verify_failure_invalid_signature_string(signer: UrlSigner) -> None:
    """Test that verification fails for invalid signature strings."""
    with pytest.raises(InvalidSignature, match="Invalid signature"):
        await signer.verify("/path?signature=invalid-token")


async def test_verify_failure_expired(signer: UrlSigner) -> None:
    """Test that verification fails for expired URLs."""
    initial_time = datetime.datetime(2023, 1, 1, 12, 0, 0)
    with freezegun.freeze_time(initial_time) as frozen_time:
        path = "/expired"
        signed_url = await signer.sign(path, expiration=datetime.timedelta(minutes=7))

        # Advance time past expiry
        frozen_time.tick(delta=datetime.timedelta(minutes=8))

        with pytest.raises(InvalidSignature, match="Signature expired"):
            await signer.verify(signed_url)


async def test_sign_with_user(signer: UrlSigner) -> None:
    """Test signing with user identity."""
    path = "/user/resource"
    user = "test@example.com"
    signed_url = await signer.sign(path, user=user)

    payload = await signer.verify(signed_url)
    assert payload["path"] == path
    assert payload["user"] == user

    # Ensure payload doesn't have user if not provided
    signed_url_no_user = await signer.sign(path)
    payload_no_user = await signer.verify(signed_url_no_user)
    assert "user" not in payload_no_user


async def test_sign_preserves_query_check(signer: UrlSigner) -> None:
    """Test that signing respects existing query params."""
    path = "/api/resource?foo=bar"
    signed_url = await signer.sign(path)

    assert "foo=bar" in signed_url
    assert "signature=" in signed_url
    assert await signer.verify(signed_url)


async def test_sign_rejects_fragment(signer: UrlSigner) -> None:
    """Test that signing rejects fragments."""
    with pytest.raises(ValueError, match="fragments.*not supported"):
        await signer.sign("/api/resource#section1")
