"""Google Gemini API (generativelanguage v1beta, ключ в x-goog-api-key). Сверено с докой 2026-09.

Стрим: models/{model}:streamGenerateContent?alt=sse, каждый data — GenerateContentResponse,
текст в candidates[0].content.parts[].text (parts с thought=true пропускаем), [DONE] нет — конец по закрытию.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from app.ai.base import BaseProvider
from app.ai.errors import code_for_status
from app.ai.models import ChatMessage, ModelInfo, ProviderDescriptor
from app.ai.providers.gemini_catalog import classify


class GeminiProvider(BaseProvider):
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"
    descriptor = ProviderDescriptor(
        id="google", name="Google Gemini", capabilities=["translate", "chat", "summary"],
        docs_url="https://ai.google.dev/api/generate-content",
        keys_url="https://aistudio.google.com/apikey",
        default_models=["gemini-3.8-flash", "gemini-3.5-flash-lite"],
    )

    def auth_headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key}

    def _error_from_response(self, status, body):
        err = super()._error_from_response(status, body)
        text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
        if status == 400 and "API_KEY_INVALID" in text:  # неверный ключ у Gemini бывает 400
            err.code = "unauthorized"
        return err

    async def list_models(self) -> list[ModelInfo]:
        out: list[ModelInfo] = []
        params: dict = {"pageSize": 1000}
        for _ in range(20):
            data = await self.get_json("/models", params)
            for m in data.get("models", []):
                if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                    continue
                mid = m["name"].removeprefix("models/")
                extra = classify(mid)
                if extra is None:  # 2.5 ограничена, выключенные, картинки/TTS/live и т.п.
                    continue
                out.append(ModelInfo(id=mid, provider_id="google", display_name=m.get("displayName") or mid,
                                     context_window=m.get("inputTokenLimit"), **extra))
            if not data.get("nextPageToken"):
                break
            params = {"pageSize": 1000, "pageToken": data["nextPageToken"]}
        rank = {"stable": 0, "preview": 1, "deprecated": 2}
        return sorted(out, key=lambda m: (not m.recommended, rank[m.status], m.id))

    async def test_connection(self) -> int:
        await self.get_json("/models", {"pageSize": 1})
        return len(await self.list_models())

    async def chat_stream(self, *, model, system, messages: list[ChatMessage], max_tokens, temperature) -> AsyncIterator[str]:
        config: dict = {"maxOutputTokens": max_tokens}
        if temperature is not None:
            config["temperature"] = temperature
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
                         for m in messages],
            "generationConfig": config,
        }
        url = f"{self.base_url}/models/{model.removeprefix('models/')}:streamGenerateContent?alt=sse"
        async for _event, data in self.sse_events(url, body):
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            if err := chunk.get("error"):
                status = err.get("code") if isinstance(err.get("code"), int) else None
                raise self.error(code_for_status(status) if status else "provider_error",
                                 f"Gemini: {err.get('message') or err}", status)
            if reason := (chunk.get("promptFeedback") or {}).get("blockReason"):
                raise self.error("bad_request", f"Gemini заблокировал запрос: {reason}")
            for cand in (chunk.get("candidates") or [])[:1]:
                for part in (cand.get("content") or {}).get("parts") or []:
                    if part.get("text") and not part.get("thought"):
                        yield part["text"]
