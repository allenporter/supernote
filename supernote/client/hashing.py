"""Module for hashing utilities."""

import hashlib
import logging

logger = logging.getLogger(__name__)


def _sha256_string(s: str) -> str:
    """Return SHA256 hex digest of a string."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _md5_string(s: str) -> str:
    """Return MD5 hex digest of a string."""
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def hash_with_salt(content: str, salt: str) -> str:
    """Hash content with salt using SHA256."""
    return _sha256_string(f"{content}{salt}")


def hash_password(password_text: str, rc: str) -> str:
    """Encode password using MD5 and SHA256."""
    md5 = _md5_string(password_text)
    return hash_with_salt(md5, rc)


def get_token_salt(token: str) -> str:
    """Extract real key (salt) from token.

    This is the dynamic key selection mechanism used during the SMS authentication
    flow. It takes the last character of the token and interprets it as an integer
    index n. It then splits the token string by hyphens - and returns the n-th
    component from the split parts.
    """
    if not token:
        raise ValueError("Token cannot be empty")
    last_char = token[-1]
    try:
        index = int(last_char)
    except ValueError:
        raise ValueError(f"Last character of token must be an integer: {token}")
    parts = token.split("-")
    if 0 <= index < len(parts):
        return parts[index]
    raise ValueError(
        f"Invalid token format (index out of bounds, index={index}, token={token})"
    )
