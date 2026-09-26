from __future__ import annotations

import httpx

from app.config import Settings
from app.transcripts.base import DEFAULT_TIMEOUT, TranscriptProvider
from app.transcripts.models import TranscriptProviderInfo
from app.transcripts.providers.chocodata import ChocoDataProvider
from app.transcripts.providers.easytranscriber import EasyTranscriberProvider
from app.transcripts.providers.supadata import SupadataProvider
from app.transcripts.providers.transcriptapi import TranscriptApiProvider
from app.transcripts.providers.youtube_transcript_ai import YoutubeTranscriptAiProvider

DEFAULT_PROVIDERS: tuple[type[TranscriptProvider], ...] = (
    YoutubeTranscriptAiProvider, TranscriptApiProvider, SupadataProvider, ChocoDataProvider, EasyTranscriberProvider,
)


class TranscriptProviderRegistry:
    """Фабрика провайдеров по id + порядок фолбэка из TRANSCRIPT_PROVIDERS_ORDER."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None,
                 classes: tuple[type[TranscriptProvider], ...] = DEFAULT_PROVIDERS):
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        self._classes: dict[str, type[TranscriptProvider]] = {}
        self._instances: dict[str, TranscriptProvider] = {}
        for cls in classes:
            self.register(cls)

    def register(self, cls: type[TranscriptProvider]) -> None:
        self._classes[cls.id] = cls
        self._instances.pop(cls.id, None)

    def get(self, provider_id: str) -> TranscriptProvider:
        if provider_id not in self._classes:
            raise KeyError(provider_id)
        if provider_id not in self._instances:
            self._instances[provider_id] = self._classes[provider_id](self.settings, self.client)
        return self._instances[provider_id]

    def ids(self) -> list[str]:
        return list(self._classes)

    def list(self, user_keys: dict[str, str] | None = None,
             credentials: dict[str, dict] | None = None) -> list[TranscriptProviderInfo]:
        keys, creds = user_keys or {}, credentials or {}
        return [self.get(i).info(keys.get(i), creds.get(i)) for i in self._order_ids(include_all=True)]

    def ordered(self, user_keys: dict[str, str] | None = None) -> list[TranscriptProvider]:
        """Настроенные провайдеры в порядке фолбэка (без ключа — ни у пользователя, ни на сервере — пропускаются)."""
        keys = user_keys or {}
        return [p for p in (self.get(i) for i in self._order_ids()) if p.configured_for(keys.get(p.id))]

    def _order_ids(self, include_all: bool = False) -> list[str]:
        order = [x.strip() for x in self.settings.transcript_providers_order.split(",") if x.strip()]
        ids = [i for i in order if i in self._classes]
        if include_all:
            ids += [i for i in self._classes if i not in ids]
        return ids

    async def aclose(self) -> None:
        await self.client.aclose()
