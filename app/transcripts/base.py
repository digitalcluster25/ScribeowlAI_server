from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

import httpx

from app.config import Settings
from app.transcripts.errors import TranscriptError
from app.transcripts.models import Transcript, TranscriptProviderInfo

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=5.0)


class TranscriptProvider(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    docs_url: ClassVar[str]
    keys_url: ClassVar[str | None] = None
    requires_api_key: ClassVar[bool] = False
    # умеет сделать транскрипт без субтитров (распознавание речи на стороне провайдера)
    can_generate: ClassVar[bool] = False
    timed: ClassVar[bool] = True
    pricing: ClassVar[str | None] = None
    # имя поля в Settings с ключом (если requires_api_key)
    api_key_setting: ClassVar[str | None] = None

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    @property
    def api_key(self) -> str:
        """Ключ из env сервера (запасной)."""
        return getattr(self.settings, self.api_key_setting, "") if self.api_key_setting and self.settings else ""

    @property
    def configured(self) -> bool:
        return not self.requires_api_key or bool(self.api_key)

    def configured_for(self, user_key: str | None) -> bool:
        return not self.requires_api_key or bool(user_key or self.api_key)

    def info(self, user_key: str | None = None, credential: dict | None = None) -> TranscriptProviderInfo:
        source = None
        if self.requires_api_key:
            source = "user" if user_key else ("server" if self.api_key else None)
        return TranscriptProviderInfo(
            id=self.id, name=self.name, requires_api_key=self.requires_api_key,
            configured=self.configured_for(user_key), docs_url=self.docs_url, keys_url=self.keys_url,
            key_source=source, credential=credential, can_generate=self.can_generate, timed=self.timed,
            pricing=self.pricing,
        )

    @abstractmethod
    async def fetch(self, video_id: str, language: str | None, api_key: str | None = None) -> Transcript:
        """api_key — ключ пользователя; если нет — ключ сервера."""

    async def test_key(self, api_key: str) -> None:
        """Проверка ключа пользователя (бесплатным запросом). По умолчанию ключ не нужен."""
        return None

    # --- общее ---
    def error(self, code, message: str, status: int | None = None) -> TranscriptError:
        return TranscriptError(code, message, self.id, status)

    async def request(self, method: str, url: str, **kw) -> httpx.Response:
        try:
            return await self.client.request(method, url, **kw)
        except httpx.TimeoutException as e:
            raise self.error("network", f"{self.name}: таймаут ({e.__class__.__name__})") from e
        except httpx.HTTPError as e:
            raise self.error("network", f"{self.name}: сеть недоступна ({e.__class__.__name__})") from e

    def http_error(self, response: httpx.Response, message: str | None = None) -> TranscriptError:
        s = response.status_code
        code = (
            "unauthorized" if s in (401, 403)
            else "quota_exceeded" if s == 402
            else "not_found" if s in (404, 410, 422)
            else "rate_limited" if s == 429
            else "network"  # 408, 5xx и прочее — временная ошибка
        )
        return self.error(code, message or f"{self.name}: HTTP {s}", s)
