"""AES-256-GCM для ключей провайдеров.

Шифротекст, IV (12 байт) и тег (16 байт) лежат в БД, мастер-ключ — только в env.
AAD = "<user_id>:<provider_id>": шифротекст нельзя «переставить» другому пользователю/провайдеру.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

IV_LEN = 12
TAG_LEN = 16


class CryptoConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Encrypted:
    ciphertext: bytes
    iv: bytes
    tag: bytes
    key_version: int


class KeyCipher:
    def __init__(self, keys: dict[int, bytes], current_version: int):
        for v, k in keys.items():
            if len(k) != 32:
                raise CryptoConfigError(f"Мастер-ключ v{v} должен быть 32 байта (base64 от 32 байт)")
        if current_version not in keys:
            raise CryptoConfigError(f"Нет мастер-ключа версии {current_version}")
        self._keys = keys
        self.current_version = current_version

    @classmethod
    def from_settings(cls, b64_key: str, version: int) -> "KeyCipher":
        if not b64_key:
            raise CryptoConfigError("CREDENTIALS_ENCRYPTION_KEY не задан")
        try:
            key = base64.b64decode(b64_key, validate=True)
        except ValueError as e:
            raise CryptoConfigError("CREDENTIALS_ENCRYPTION_KEY не base64") from e
        return cls({version: key}, version)

    @staticmethod
    def _aad(user_id: str, provider_id: str) -> bytes:
        return f"{user_id}:{provider_id}".encode()

    def encrypt(self, plaintext: str, user_id: str, provider_id: str) -> Encrypted:
        iv = os.urandom(IV_LEN)
        out = AESGCM(self._keys[self.current_version]).encrypt(iv, plaintext.encode(), self._aad(user_id, provider_id))
        return Encrypted(ciphertext=out[:-TAG_LEN], iv=iv, tag=out[-TAG_LEN:], key_version=self.current_version)

    def decrypt(self, enc: Encrypted, user_id: str, provider_id: str) -> str:
        key = self._keys.get(enc.key_version)
        if key is None:
            raise CryptoConfigError(f"Нет мастер-ключа версии {enc.key_version}")
        return AESGCM(key).decrypt(enc.iv, enc.ciphertext + enc.tag, self._aad(user_id, provider_id)).decode()


def key_hint(api_key: str) -> str:
    """Последние 4 символа для UI."""
    k = api_key.strip()
    return k[-4:] if len(k) >= 8 else "…"


def redact(text: str | None, *secrets: str | None) -> str | None:
    """Вырезает ключи из сообщений провайдеров (некоторые, напр. Supadata, эхом возвращают ключ в ошибке)."""
    if not text:
        return text
    for secret in secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, f"••••{secret[-4:]}")
    return text
