from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import ClassVar

import httpx

from app.ai.errors import ProviderError, code_for_status
from app.ai.models import ChatMessage, ModelInfo, ProviderDescriptor

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=5.0)


class BaseProvider(ABC):
    descriptor: ClassVar[ProviderDescriptor]
    default_base_url: ClassVar[str]

    def __init__(self, api_key: str, client: httpx.AsyncClient, base_url: str | None = None):
        self.api_key = api_key
        self.client = client
        self.base_url = (base_url or self.default_base_url).rstrip("/")

    @property
    def id(self) -> str:
        return self.descriptor.id

    # --- контракт ---
    @abstractmethod
    def auth_headers(self) -> dict[str, str]: ...

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]: ...

    @abstractmethod
    def chat_stream(
        self, *, model: str, system: str, messages: list[ChatMessage], max_tokens: int, temperature: float | None
    ) -> AsyncIterator[str]:
        """Асинхронный поток текстовых дельт ответа."""

    async def test_connection(self) -> int:
        """Проверка ключа: сколько моделей доступно (бесплатный запрос)."""
        return len(await self.list_models())

    # --- общее ---
    def error(self, code, message: str, status: int | None = None) -> ProviderError:
        return ProviderError(code, message, self.id, status)

    def _error_from_response(self, status: int, body: bytes | str) -> ProviderError:
        text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
        message = text[:300]
        try:
            data = json.loads(text)
            err = data.get("error", data) if isinstance(data, dict) else data
            if isinstance(err, dict):
                message = err.get("message") or err.get("detail") or message
            elif isinstance(err, str):
                message = err
        except ValueError:
            pass
        return self.error(code_for_status(status), f"{self.descriptor.name}: {message}", status)

    async def get_json(self, path_or_url: str, params: dict | None = None) -> dict:
        url = path_or_url if path_or_url.startswith("http") else self.base_url + path_or_url
        try:
            r = await self.client.get(url, params=params, headers=self.auth_headers())
        except httpx.TimeoutException as e:
            raise self.error("network", f"{self.descriptor.name}: таймаут") from e
        except httpx.HTTPError as e:
            raise self.error("network", f"{self.descriptor.name}: сеть недоступна ({e.__class__.__name__})") from e
        if r.status_code >= 400:
            raise self._error_from_response(r.status_code, r.content)
        try:
            return r.json()
        except ValueError as e:
            raise self.error("provider_error", f"{self.descriptor.name}: ответ не JSON") from e

    async def sse_events(self, url: str, body: dict, extra_headers: dict | None = None) -> AsyncIterator[tuple[str | None, str]]:
        """POST со стримингом SSE → пары (event, data). Ошибка HTTP до начала потока — ProviderError."""
        headers = {**self.auth_headers(), "content-type": "application/json", "accept": "text/event-stream",
                   **(extra_headers or {})}
        try:
            async with self.client.stream("POST", url, json=body, headers=headers) as r:
                if r.status_code >= 400:
                    raise self._error_from_response(r.status_code, await r.aread())
                event: str | None = None
                data_lines: list[str] = []
                async for line in r.aiter_lines():
                    if line == "":
                        if data_lines:
                            yield event, "\n".join(data_lines)
                        event, data_lines = None, []
                    elif line.startswith(":"):
                        continue  # комментарий / keep-alive (OpenRouter шлёт ": OPENROUTER PROCESSING")
                    elif line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                if data_lines:
                    yield event, "\n".join(data_lines)
        except httpx.TimeoutException as e:
            raise self.error("network", f"{self.descriptor.name}: таймаут") from e
        except httpx.HTTPError as e:
            raise self.error("network", f"{self.descriptor.name}: обрыв соединения ({e.__class__.__name__})") from e
