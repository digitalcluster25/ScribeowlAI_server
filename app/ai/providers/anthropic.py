"""Anthropic Messages API (сверено с докой 2026-09).

Стрим: события content_block_delta (delta.type == "text_delta" → delta.text), конец — message_stop,
ошибка посреди стрима — event: error. ping и thinking-дельты игнорируем.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from app.ai.base import BaseProvider
from app.ai.errors import ProviderError
from app.ai.models import ChatMessage, ModelInfo, ProviderDescriptor

VERSION = "2023-06-01"
ERROR_CODES = {
    "authentication_error": "unauthorized", "permission_error": "unauthorized", "billing_error": "quota_exceeded",
    "rate_limit_error": "rate_limited", "not_found_error": "not_found", "invalid_request_error": "bad_request",
    "overloaded_error": "overloaded", "api_error": "overloaded",
}


class AnthropicProvider(BaseProvider):
    default_base_url = "https://api.anthropic.com/v1"
    descriptor = ProviderDescriptor(
        id="anthropic", name="Anthropic", capabilities=["translate", "chat", "summary"],
        docs_url="https://docs.anthropic.com/en/api/messages",
        keys_url="https://console.anthropic.com/settings/keys",
        default_models=["claude-haiku-4-5", "claude-sonnet-5"],
    )

    def auth_headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key, "anthropic-version": VERSION}

    async def list_models(self) -> list[ModelInfo]:
        out: list[ModelInfo] = []
        params: dict = {"limit": 1000}
        for _ in range(20):  # защита от бесконечной пагинации
            data = await self.get_json("/models", params)
            out += [ModelInfo(id=m["id"], provider_id="anthropic", display_name=m.get("display_name") or m["id"],
                              context_window=m.get("max_input_tokens")) for m in data.get("data", [])]
            if not data.get("has_more") or not data.get("last_id"):
                break
            params = {"limit": 1000, "after_id": data["last_id"]}
        return out

    async def test_connection(self) -> int:
        await self.get_json("/models", {"limit": 1})
        return len(await self.list_models())

    async def chat_stream(self, *, model, system, messages: list[ChatMessage], max_tokens, temperature) -> AsyncIterator[str]:
        if not messages or messages[-1].role != "user":
            raise self.error("bad_request", "Anthropic: последнее сообщение должно быть от пользователя")
        body: dict = {"model": model, "max_tokens": max_tokens, "system": system,
                      "messages": [m.model_dump() for m in messages], "stream": True}
        if temperature is not None:
            body["temperature"] = temperature
        async for event, data in self.sse_events(self.base_url + "/messages", body):
            try:
                payload = json.loads(data)
            except ValueError:
                continue
            kind = event or payload.get("type")
            if kind == "content_block_delta":
                delta = payload.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield delta["text"]
            elif kind == "message_stop":
                return
            elif kind == "error":
                err = payload.get("error") or {}
                raise ProviderError(ERROR_CODES.get(err.get("type"), "provider_error"),
                                    f"Anthropic: {err.get('message') or err.get('type')}", self.id)
