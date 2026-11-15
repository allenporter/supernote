import datetime

import freezegun
import pytest

from supernote.server.exceptions import InvalidSignature
from supernote.server.services.coordination import CoordinationService
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


async def test_verify_rejects_path_suffix_injection(signer: UrlSigner) -> None:
    """Verify appending a path suffix to a signed path is rejected."""
    signed_url = await signer.sign("/api/oss/download?path=12")
    suffix_url = signed_url.replace("/api/oss/download?", "/api/oss/download/extra?", 1)
    with pytest.raises(InvalidSignature, match="Signed path mismatch"):
        await signer.verify(suffix_url)


async def test_verify_rejects_query_value_prefix_extension(signer: UrlSigner) -> None:
    """Verify extending a signed query parameter value (e.g. path=12 -> path=123) is rejected."""
    signed_url = await signer.sign("/api/oss/download?path=12")
    prefix_query_url = signed_url.replace("path=12&", "path=123&", 1)
    with pytest.raises(InvalidSignature, match="Signed query parameter mismatch"):
        await signer.verify(prefix_query_url)


async def test_verify_rejects_duplicate_signed_query_param(signer: UrlSigner) -> None:
    """Verify duplicating a signed query parameter (HTTP parameter pollution) is rejected."""
    signed_url = await signer.sign("/api/oss/download?path=12")
    polluted_url = f"{signed_url}&path=999"
    with pytest.raises(InvalidSignature, match="Signed query parameter mismatch"):
        await signer.verify(polluted_url)


async def test_verify_allows_extra_device_query_params(signer: UrlSigner) -> None:
    """Verify extra unsigned query parameters (e.g. partNumber) are permitted when signed params match."""
    signed_url = await signer.sign("/api/oss/upload/part?path=12")
    extra_param_url = f"{signed_url}&partNumber=1&totalChunks=2"
    payload = await signer.verify(extra_param_url)
    assert payload["path"] == "/api/oss/upload/part?path=12"


async def test_verify_signed_query_keys_rejects_unsigned_param(
    signer: UrlSigner,
) -> None:
    """Verify signed_query_keys rejects injecting a query key omitted at sign time while allowing other keys."""
    signed_url = await signer.sign("/api/oss/pdf/42")
    with pytest.raises(InvalidSignature, match="Signed query parameter mismatch"):
        await signer.verify(f"{signed_url}&pages=0", signed_query_keys=("pages",))

    payload = await signer.verify(
        f"{signed_url}&inline=1", signed_query_keys=("pages",)
    )
    assert payload["path"] == "/api/oss/pdf/42"


async def test_verify_rejects_fragment_in_signed_url(signer: UrlSigner) -> None:
    """Verify verify() rejects '#' in URLs (e.g. decoded from %23 in request.path_qs) before urlparse truncates."""
    signed_url = await signer.sign("/api/oss/pdf/42?pages=0")
    with pytest.raises(InvalidSignature, match="fragments.*not supported"):
        await signer.verify(f"{signed_url}#extra")


async def test_verify_tampered_url_does_not_consume_nonce(
    coordination_service: CoordinationService,
) -> None:
    """Verify failed URL integrity checks do not burn the single-use nonce."""
    stateful_signer = UrlSigner(
        "test-secret-key-32-characters-long!!", coordination_service
    )
    signed_url = await stateful_signer.sign(
        "/api/oss/download?path=12", user="u@example.com"
    )
    tampered_url = signed_url.replace("path=12&", "path=123&", 1)

    with pytest.raises(InvalidSignature, match="Signed query parameter mismatch"):
        await stateful_signer.verify(tampered_url)

    payload = await stateful_signer.verify(signed_url)
    assert payload["path"] == "/api/oss/download?path=12"

    with pytest.raises(InvalidSignature, match="Token invalid or already used"):
        await stateful_signer.verify(signed_url)


async def test_sign_multi_use_skips_nonce_storage_and_allows_reuse(
    coordination_service: CoordinationService,
) -> None:
    """Verify single_use=False does not store a nonce in CoordinationService and allows repeated verification."""
    stateful_signer = UrlSigner(
        "test-secret-key-32-characters-long!!", coordination_service
    )
    signed_url = await stateful_signer.sign(
        "/api/oss/download?path=12", user="u@example.com", single_use=False
    )

    payload1 = await stateful_signer.verify(signed_url)
    nonce = payload1["nonce"]
    assert payload1["single_use"] is False
    assert await coordination_service.get_value(f"nonce:u@example.com:{nonce}") is None

    payload2 = await stateful_signer.verify(signed_url)
    assert payload2["path"] == "/api/oss/download?path=12"
