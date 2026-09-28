"""Ключи провайдеров пользователя: шифруем, храним в provider_credentials, наружу — только маска."""

from __future__ import annotations

from datetime import datetime, timezone

from app.ai.models import CredentialStatus
from app.db.rest import SupabaseRest, from_bytea, to_bytea
from app.security.crypto import Encrypted, KeyCipher, key_hint

TABLE = "provider_credentials"


class CredentialStore:
    def __init__(self, db: SupabaseRest, cipher: KeyCipher):
        self.db = db
        self.cipher = cipher

    @staticmethod
    def _status(row: dict) -> CredentialStatus:
        return CredentialStatus(
            provider_id=row["provider_id"], configured=True, key_hint=row["key_hint"], status=row["status"],
            last_checked_at=row.get("last_checked_at"), last_error=row.get("last_error"), base_url=row.get("base_url"),
        )

    async def list(self, user_id: str) -> dict[str, CredentialStatus]:
        return {r["provider_id"]: self._status(r) for r in await self.db.select(TABLE, user_id=user_id)}

    async def save(self, user_id: str, provider_id: str, api_key: str, base_url: str | None = None) -> CredentialStatus:
        enc = self.cipher.encrypt(api_key.strip(), user_id, provider_id)
        row = await self.db.upsert(TABLE, {
            "user_id": user_id, "provider_id": provider_id,
            "encrypted_key": to_bytea(enc.ciphertext), "iv": to_bytea(enc.iv), "auth_tag": to_bytea(enc.tag),
            "key_version": enc.key_version, "key_hint": key_hint(api_key), "base_url": base_url,
            "status": "unverified", "last_checked_at": None, "last_error": None,
        }, on_conflict="user_id,provider_id")
        return self._status(row)

    async def get_key(self, user_id: str, provider_id: str) -> tuple[str, str | None] | None:
        rows = await self.db.select(TABLE, user_id=user_id, provider_id=provider_id)
        if not rows:
            return None
        r = rows[0]
        enc = Encrypted(from_bytea(r["encrypted_key"]), from_bytea(r["iv"]), from_bytea(r["auth_tag"]), r["key_version"])
        return self.cipher.decrypt(enc, user_id, provider_id), r.get("base_url")

    async def set_status(self, user_id: str, provider_id: str, status: str, error: str | None = None) -> None:
        await self.db.update(TABLE, {
            "status": status, "last_error": error, "last_checked_at": datetime.now(timezone.utc).isoformat(),
        }, user_id=user_id, provider_id=provider_id)

    async def delete(self, user_id: str, provider_id: str) -> None:
        await self.db.delete(TABLE, user_id=user_id, provider_id=provider_id)
