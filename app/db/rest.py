"""Доступ к Supabase Postgres через PostgREST с secret key (обходит RLS).

Только сервер: клиентам (anon/authenticated) таблицы закрыты миграцией.
bytea в PostgREST — строки вида "\\x<hex>".
"""

from __future__ import annotations

from typing import Any

import httpx


class DbError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"DB {status}: {message}")
        self.status = status


def to_bytea(b: bytes) -> str:
    return "\\x" + b.hex()


def from_bytea(v: str) -> bytes:
    if not v.startswith("\\x"):
        raise ValueError("ожидался bytea в hex-формате \\x...")
    return bytes.fromhex(v[2:])


class SupabaseRest:
    def __init__(self, url: str, secret_key: str, client: httpx.AsyncClient | None = None):
        self.base = url.rstrip("/") + "/rest/v1"
        self.headers = {"apikey": secret_key, "Authorization": f"Bearer {secret_key}"}
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0))

    async def _req(self, method: str, table: str, *, params=None, json=None, prefer: str | None = None) -> Any:
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        r = await self.client.request(method, f"{self.base}/{table}", params=params, json=json, headers=headers)
        if r.status_code >= 400:
            raise DbError(r.status_code, r.text[:300])
        return r.json() if r.content else None

    async def select(self, table: str, **filters: str) -> list[dict]:
        params = {"select": "*", **{k: f"eq.{v}" for k, v in filters.items()}}
        return await self._req("GET", table, params=params)

    async def upsert(self, table: str, row: dict, on_conflict: str) -> dict:
        rows = await self._req(
            "POST", table, params={"on_conflict": on_conflict}, json=row,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return rows[0]

    async def update(self, table: str, values: dict, **filters: str) -> None:
        await self._req("PATCH", table, params={k: f"eq.{v}" for k, v in filters.items()}, json=values,
                        prefer="return=minimal")

    async def delete(self, table: str, **filters: str) -> None:
        await self._req("DELETE", table, params={k: f"eq.{v}" for k, v in filters.items()}, prefer="return=minimal")

    async def aclose(self) -> None:
        await self.client.aclose()
