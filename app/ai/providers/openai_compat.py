"""OpenAI-совместимый Chat Completions: OpenAI, OpenRouter, Groq.

Стрим: data-only SSE, дельта в choices[0].delta.content, конец — `data: [DONE]`;
ошибка посреди стрима — объект `error` в data (сверено с докой 2026-09).
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import ClassVar

from app.ai.base import BaseProvider
from app.ai.errors import code_for_status
from app.ai.models import ChatMessage, ModelInfo, ProviderDescriptor


class OpenAICompatibleProvider(BaseProvider):
    # OpenAI и Groq: max_tokens устарел → max_completion_tokens; OpenRouter принимает max_tokens
    max_tokens_param: ClassVar[str] = "max_completion_tokens"

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def keep_model(self, m: dict) -> bool:
        return True

    def to_model(self, m: dict) -> ModelInfo:
        return ModelInfo(id=m["id"], provider_id=self.id, display_name=m.get("name") or m["id"],
                         context_window=m.get("context_window") or m.get("context_length"))

    async def list_models(self) -> list[ModelInfo]:
        data = await self.get_json("/models")
        models = [self.to_model(m) for m in data.get("data", []) if self.keep_model(m)]
        return sorted(models, key=lambda m: m.id)

    async def chat_stream(self, *, model, system, messages: list[ChatMessage], max_tokens, temperature) -> AsyncIterator[str]:
        body: dict = {
            "model": model,
            "messages": [{"role": "system", "content": system}] + [m.model_dump() for m in messages],
            self.max_tokens_param: max_tokens,
            "stream": True,
        }
        if temperature is not None:
            body["temperature"] = temperature
        async for _event, data in self.sse_events(self.base_url + "/chat/completions", body):
            if data.strip() == "[DONE]":
                return
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            if err := chunk.get("error"):
                status = err.get("code") if isinstance(err.get("code"), int) else None
                raise self.error(code_for_status(status) if status else "provider_error",
                                 f"{self.descriptor.name}: {err.get('message') or err}", status)
            choices = chunk.get("choices") or []
            if choices and (text := (choices[0].get("delta") or {}).get("content")):
                yield text


_OPENAI_SKIP = re.compile(
    r"embedding|whisper|tts|dall-e|image|realtime|audio|transcribe|moderation|davinci|babbage|search|computer-use"
)


class OpenAIProvider(OpenAICompatibleProvider):
    default_base_url = "https://api.openai.com/v1"
    descriptor = ProviderDescriptor(
        id="openai", name="OpenAI", capabilities=["translate", "chat", "summary"],
        docs_url="https://platform.openai.com/docs/api-reference/chat",
        keys_url="https://platform.openai.com/api-keys",
        default_models=["gpt-6-luna", "gpt-6-sol"],
    )

    def keep_model(self, m: dict) -> bool:
        mid = m["id"]
        return mid.startswith(("gpt-", "o", "chatgpt-")) and not _OPENAI_SKIP.search(mid)


class OpenRouterProvider(OpenAICompatibleProvider):
    default_base_url = "https://openrouter.ai/api/v1"
    max_tokens_param = "max_tokens"
    descriptor = ProviderDescriptor(
        id="openrouter", name="OpenRouter", capabilities=["translate", "chat", "summary"],
        docs_url="https://openrouter.ai/docs/api-reference/overview",
        keys_url="https://openrouter.ai/settings/keys",
        default_models=["anthropic/claude-sonnet-5", "google/gemini-3.8-flash"],
    )

    def auth_headers(self) -> dict[str, str]:
        return {**super().auth_headers(), "HTTP-Referer": "http://127.0.0.1:5174", "X-OpenRouter-Title": "Scribeowl"}

    def keep_model(self, m: dict) -> bool:
        return "text" in ((m.get("architecture") or {}).get("output_modalities") or ["text"])

    async def test_connection(self) -> int:
        # GET /key — дешёвая проверка ключа (и остатка кредитов); число моделей — отдельно
        await self.get_json("/key")
        return len(await self.list_models())


_GROQ_SKIP = re.compile(r"whisper|tts|playai|guard")


class GroqProvider(OpenAICompatibleProvider):
    default_base_url = "https://api.groq.com/openai/v1"
    descriptor = ProviderDescriptor(
        id="groq", name="Groq", capabilities=["translate", "chat", "summary"],
        docs_url="https://console.groq.com/docs/api-reference",
        keys_url="https://console.groq.com/keys",
        default_models=["llama-3.3-70b-versatile", "openai/gpt-oss-120b"],
    )

    def keep_model(self, m: dict) -> bool:
        return m.get("active", True) and not _GROQ_SKIP.search(m["id"])
