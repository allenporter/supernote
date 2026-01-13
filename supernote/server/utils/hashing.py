"""Module for hashing utilities."""

import hashlib


def sha256_string(s: str) -> str:
    """Return SHA256 hex digest of a string."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def hash_with_salt(content: str, salt: str) -> str:
    """Hash content with salt using SHA256."""
    return sha256_string(f"{content}{salt}")


def get_md5_hash(s: str) -> str:
    """Return MD5 hex digest of a string."""
    return hashlib.md5(s.encode("utf-8")).hexdigest()
