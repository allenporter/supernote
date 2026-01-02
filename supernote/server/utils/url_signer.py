"""URL Signing Utility.

This module provides the UrlSigner class for generating and verifying HMAC-SHA256 signatures for URLs.
"""

import datetime
import hashlib
import hmac
import logging
import time
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)

__all__ = [
    "UrlSigner",
]

DEFAULT_MAX_AGE = datetime.timedelta(minutes=15)


@dataclass
class Message:
    path: str
    timestamp: int
    nonce: str

    def __post_init__(self) -> None:
        if "|" in self.path:
            raise ValueError("Path cannot contain pipe character")

    def encode(self) -> str:
        """Encode the message into a string."""
        return f"{self.path}|{self.timestamp}|{self.nonce}"

    def sign(self, secret_key: bytes) -> str:
        """Generate signature for the message."""
        return hmac.new(
            secret_key, self.encode().encode("utf-8"), hashlib.sha256
        ).hexdigest()


class UrlSigner:
    """Helper for signing and verifying URLs."""

    def __init__(self, secret_key: str) -> None:
        """Initialize with a secret key.

        Args:
            secret_key: The secret key used for HMAC generation.
        """
        if not secret_key:
            raise ValueError("Secret key cannot be empty")
        self.secret_key = secret_key.encode("utf-8")

    def sign(self, path: str) -> tuple[str, int, str]:
        """Generate signature, timestamp, and nonce for a path.

        Args:
            path: The resource path/string to sign.

        Returns:
            A tuple of (signature, timestamp, nonce).
        """
        timestamp = int(time.time() * 1000)
        nonce = uuid.uuid4().hex

        message = Message(path, timestamp, nonce)
        signature = message.sign(self.secret_key)

        return signature, timestamp, nonce

    def verify(
        self,
        path: str,
        signature: str,
        timestamp: int,
        nonce: str,
        max_age: datetime.timedelta = DEFAULT_MAX_AGE,
    ) -> bool:
        """Verify the signature for a path.

        Args:
            path: The resource path that was signed.
            signature: The signature provided by the client.
            timestamp: The timestamp provided by the client (ms).
            nonce: The nonce provided by the client.
            max_age: Maximum allowed age of the signature.

        Returns:
            True if valid, False otherwise.
        """
        if not signature or not timestamp or not nonce:
            return False

        # Check timestamp freshness (optional but recommended)
        current_time = int(time.time() * 1000)
        age = current_time - timestamp

        # Determine if we want to enforce expiry.
        # For now, we'll log warning but mainly focus on signature validity.
        # But for security, we should enforce it.
        max_age_ms = max_age.total_seconds() * 1000
        if age > max_age_ms or age < -5000:  # Allow 5s clock skew into future
            logger.info(f"Signature expired or invalid timestamp: Age {age}ms")
            # NOTE: Strictly enforcing expiry might break tests if they mock time poorly,
            # but let's enforce it for "robustness".
            return False

        message = Message(path, timestamp, nonce)
        expected_signature = message.sign(self.secret_key)

        return hmac.compare_digest(expected_signature, signature)
