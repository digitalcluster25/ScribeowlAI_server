from __future__ import annotations

import time

from app.transcripts.errors import FALLBACK_CODES, FALLBACK_TO_GENERATORS, TranscriptError
from app.transcripts.models import Transcript
from app.transcripts.registry import TranscriptProviderRegistry

CACHE_TTL = 24 * 3600


class TranscriptService:
    """Транскрипт от конкретного провайдера или по порядку с фолбэком. Кэш в памяти (БД — позже)."""

    def __init__(self, registry: TranscriptProviderRegistry, ttl: float = CACHE_TTL, clock=time.monotonic):
        self.registry = registry
        self.ttl = ttl
        self.clock = clock
        self._cache: dict[tuple[str, str | None, str], tuple[float, Transcript]] = {}

    async def get(self, video_id: str, language: str | None = None, provider_id: str | None = None,
                  user_keys: dict[str, str] | None = None) -> Transcript:
        keys = user_keys or {}
        if provider_id:
            try:
                provider = self.registry.get(provider_id)
            except KeyError:
                raise TranscriptError("not_found", f"Неизвестный провайдер: {provider_id}", provider_id) from None
            return await self._fetch(provider, video_id, language, keys.get(provider_id))

        providers = self.registry.ordered(keys)
        if not providers:
            raise TranscriptError("unauthorized", "Нет настроенных провайдеров транскриптов")
        last: TranscriptError | None = None
        need_generator = False
        for provider in providers:
            if need_generator and not provider.can_generate:
                continue  # субтитров нет — такой провайдер вернёт то же самое
            try:
                return await self._fetch(provider, video_id, language, keys.get(provider.id))
            except TranscriptError as e:
                last = e
                if e.code in FALLBACK_TO_GENERATORS:
                    need_generator = True
                    continue
                if e.code not in FALLBACK_CODES:
                    raise
        assert last is not None
        raise last

    async def _fetch(self, provider, video_id: str, language: str | None, user_key: str | None = None) -> Transcript:
        key = (video_id, language, provider.id)
        now = self.clock()
        if (hit := self._cache.get(key)) and now - hit[0] < self.ttl:
            return hit[1]
        if not provider.configured_for(user_key):
            raise TranscriptError("unauthorized", f"{provider.name}: ключ не добавлен (профиль → Транскрипты)", provider.id)
        transcript = await provider.fetch(video_id, language, user_key)
        self._cache[key] = (now, transcript)
        return transcript
