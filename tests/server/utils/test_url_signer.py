"""Unit tests for UrlSigner utility."""

import time

import pytest
from freezegun import freeze_time

from supernote.server.utils.url_signer import UrlSigner

SECRET_KEY = "test-secret-key"


@pytest.fixture
def signer() -> UrlSigner:
    return UrlSigner(SECRET_KEY)


def test_sign_and_verify(signer: UrlSigner) -> None:
    """Test standard sign and verify flow."""
    path = "/api/test/path"
    
    with freeze_time("2023-01-01 12:00:00"):
        signature, timestamp, nonce = signer.sign(path)
        
        assert signature
        assert timestamp > 0
        assert nonce
        
        # Verify should return True
        assert signer.verify(path, signature, timestamp, nonce) is True


def test_verify_invalid_signature(signer: UrlSigner) -> None:
    """Test verification with tampered signature."""
    path = "/api/test/path"
    with freeze_time("2023-01-01 12:00:00"):
        signature, timestamp, nonce = signer.sign(path)
    
    # Tamper with signature
    # Deterministically change the last character
    last_char = signature[-1]
    new_char = "0" if last_char != "0" else "1"
    bad_signature = signature[:-1] + new_char
    
    assert signer.verify(path, bad_signature, timestamp, nonce) is False


def test_verify_invalid_path(signer: UrlSigner) -> None:
    """Test verification with tampered path."""
    path = "/api/test/path"
    with freeze_time("2023-01-01 12:00:00"):
        signature, timestamp, nonce = signer.sign(path)

    # Tamper with path
    bad_path = "/api/test/other"

    assert signer.verify(bad_path, signature, timestamp, nonce) is False


def test_verify_invalid_timestamp(signer: UrlSigner) -> None:
    """Test verification with tampered timestamp."""
    path = "/api/test/path"
    with freeze_time("2023-01-01 12:00:00"):
        signature, timestamp, nonce = signer.sign(path)

    # Tamper with timestamp
    bad_timestamp = timestamp + 1

    assert signer.verify(path, signature, bad_timestamp, nonce) is False



def test_verify_expired_timestamp(signer: UrlSigner) -> None:
    """Test verification with expired timestamp."""
    path = "/api/test/path"
    
    # Sign at 12:00
    with freeze_time("2023-01-01 12:00:00"):
        signature, timestamp, nonce = signer.sign(path)
    
    # Verify at 12:20 (20 mins later)
    # Expiry is default 15 mins
    with freeze_time("2023-01-01 12:20:00"):
        assert signer.verify(path, signature, timestamp, nonce) is False


def test_verify_future_timestamp(signer: UrlSigner) -> None:
    """Test verification with future timestamp (clock skew)."""
    path = "/api/test/path"
    
    # We want to simulate a request coming from the future relative to the server
    # Or simply: current server time is T, signature says T + 60s
    
    # 1. Generate signature "in the future"
    with freeze_time("2023-01-01 12:01:00"):
        future_signature, future_timestamp, nonce = signer.sign(path)

    # 2. Verify at "current" time (1 minute earlier)
    with freeze_time("2023-01-01 12:00:00"):
        # Should fail because timestamp is > 5s in future
        assert signer.verify(path, future_signature, future_timestamp, nonce) is False
