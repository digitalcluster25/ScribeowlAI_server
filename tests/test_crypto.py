import os

import pytest
from cryptography.exceptions import InvalidTag

from app.security.crypto import CryptoConfigError, KeyCipher, key_hint


def test_roundtrip_and_fresh_iv():
    c = KeyCipher({1: os.urandom(32)}, 1)
    a = c.encrypt("sk-secret-value-123", "u1", "openai")
    b = c.encrypt("sk-secret-value-123", "u1", "openai")
    assert a.iv != b.iv and a.ciphertext != b.ciphertext and len(a.iv) == 12 and len(a.tag) == 16
    assert b"sk-secret" not in a.ciphertext
    assert c.decrypt(a, "u1", "openai") == "sk-secret-value-123"


def test_aad_binds_user_and_provider():
    c = KeyCipher({1: os.urandom(32)}, 1)
    e = c.encrypt("sk-secret-value-123", "u1", "openai")
    with pytest.raises(InvalidTag):
        c.decrypt(e, "u2", "openai")
    with pytest.raises(InvalidTag):
        c.decrypt(e, "u1", "groq")


def test_wrong_master_key_and_rotation():
    k1, k2 = os.urandom(32), os.urandom(32)
    e = KeyCipher({1: k1}, 1).encrypt("sk-secret-value-123", "u", "openai")
    with pytest.raises(InvalidTag):
        KeyCipher({1: k2}, 1).decrypt(e, "u", "openai")
    rotated = KeyCipher({1: k1, 2: k2}, 2)  # старые записи читаются старым ключом
    assert rotated.decrypt(e, "u", "openai") == "sk-secret-value-123"
    assert rotated.encrypt("x" * 10, "u", "openai").key_version == 2


def test_config_errors_and_hint():
    with pytest.raises(CryptoConfigError):
        KeyCipher.from_settings("", 1)
    with pytest.raises(CryptoConfigError):
        KeyCipher.from_settings("c2hvcnQ=", 1)  # 5 байт
    assert key_hint("sk-abcdefgh1234") == "1234"
