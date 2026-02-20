"""Unit tests for short-code generation utilities."""

from app.config import get_settings
from app.service import ALPHABET, generate_short_code

settings = get_settings()


def test_generate_short_code_default_length() -> None:
    code = generate_short_code()
    assert len(code) == settings.SHORT_CODE_LENGTH


def test_generate_short_code_custom_length() -> None:
    code = generate_short_code(length=10)
    assert len(code) == 10


def test_generate_short_code_only_alphanumeric() -> None:
    for _ in range(100):
        code = generate_short_code()
        assert all(c in ALPHABET for c in code)


def test_generate_short_code_uniqueness() -> None:
    codes = {generate_short_code() for _ in range(1000)}
    # With 62^7 possibilities, 1000 codes should all be unique
    assert len(codes) == 1000
