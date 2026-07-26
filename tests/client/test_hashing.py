"""Tests for supernote.client.hashing module."""

import hashlib

import pytest

from supernote.client.hashing import (
    _md5_string,
    _sha256_string,
    get_token_salt,
    hash_password,
    hash_with_salt,
)


def test_sha256_string() -> None:
    """Test _sha256_string utility."""
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert _sha256_string("hello world") == expected


def test_md5_string() -> None:
    """Test _md5_string utility."""
    expected = hashlib.md5(b"hello world").hexdigest()
    assert _md5_string("hello world") == expected


def test_hash_with_salt() -> None:
    """Test hash_with_salt utility."""
    expected = hashlib.sha256(b"contentsalt123").hexdigest()
    assert hash_with_salt("content", "salt123") == expected


def test_hash_password() -> None:
    """Test hash_password utility."""
    md5_pass = hashlib.md5(b"mypassword").hexdigest()
    expected = hashlib.sha256(f"{md5_pass}random123".encode("utf-8")).hexdigest()
    assert hash_password("mypassword", "random123") == expected


def test_get_token_salt_valid() -> None:
    """Test get_token_salt with valid tokens."""
    assert get_token_salt("part0-part1-part2-1") == "part1"
    assert get_token_salt("part0-part1-part2-0") == "part0"
    assert get_token_salt("part0-part1-part2-2") == "part2"


def test_get_token_salt_empty() -> None:
    """Test get_token_salt with empty string token."""
    with pytest.raises(ValueError, match="Token cannot be empty"):
        get_token_salt("")


def test_get_token_salt_invalid_last_char() -> None:
    """Test get_token_salt when last character is not an integer."""
    with pytest.raises(ValueError, match="Last character of token must be an integer"):
        get_token_salt("part0-part1-a")


def test_get_token_salt_out_of_bounds() -> None:
    """Test get_token_salt when index is out of bounds."""
    with pytest.raises(ValueError, match="index out of bounds"):
        get_token_salt("part0-part1-9")
