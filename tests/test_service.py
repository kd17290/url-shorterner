"""Unit tests for URL shortening service utilities."""

from app.url_service import BASE62_ALPHABET


def test_base62_alphabet() -> None:
    """Test that BASE62_ALPHABET contains expected characters."""
    expected = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    assert BASE62_ALPHABET == expected
    assert len(BASE62_ALPHABET) == 62
