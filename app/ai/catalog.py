"""Каталог моделей по API провайдера, кэш в памяти (TTL) на (пользователь, провайдер, ключ)."""

from __future__ import annotations

import time

from app.ai.base import BaseProvider
from app.ai.models import ModelInfo

TTL = 10 * 60


class ModelCatalog:
    def __init__(self, ttl: float = TTL, clock=time.monotonic):
        self.ttl = ttl
        self.clock = clock
        self._cache: dict[tuple[str, str, str], tuple[float, list[ModelInfo]]] = {}

    async def list(self, user_id: str, provider: BaseProvider, refresh: bool = False) -> list[ModelInfo]:
        key = (user_id, provider.id, provider.api_key[-6:])
        now = self.clock()
        if not refresh and (hit := self._cache.get(key)) and now - hit[0] < self.ttl:
            return hit[1]
        models = await provider.list_models()
        self._cache[key] = (now, models)
        return models

    def invalidate(self, user_id: str, provider_id: str) -> None:
        for k in [k for k in self._cache if k[0] == user_id and k[1] == provider_id]:
            del self._cache[k]
