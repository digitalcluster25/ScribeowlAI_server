"""Чат и саммари по транскрипту со стримингом (SSE), перевод фраз пачками."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.ai.errors import ProviderError
from app.ai.models import ChatMessage
from app.ai.prompts import build_system
from app.ai.translate import (
    MAX_CHARS, MAX_SEGMENTS, build_translate_input, build_translate_prompt, max_tokens_for, parse_translation,
)
from app.api.deps import AiServices, ai
from app.security.auth import CurrentUser, current_user
from app.security.crypto import redact

router = APIRouter(prefix="/ai", tags=["ai"])

MAX_TOKENS = {"chat": 1200, "summary": 1500}


class StreamIn(BaseModel):
    task: Literal["chat", "summary"]
    title: str | None = Field(default=None, max_length=500)
    transcript: str = Field(min_length=1, max_length=400_000)
    messages: list[ChatMessage] = Field(default_factory=list, max_length=40)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/stream")
async def stream(body: StreamIn, user: CurrentUser = Depends(current_user), s: AiServices = Depends(ai)):
    _, settings = s.require_storage()
    setting = await settings.get(user.id, body.task)
    if not setting:
        raise ProviderError("not_configured", f"Не выбран провайдер и модель для задачи «{body.task}» в профиле")
    provider = await s.provider_for(user.id, setting.provider_id)
    messages = body.messages or [ChatMessage(role="user", content="Сделай саммари этого видео.")]
    if body.task == "chat" and messages[-1].role != "user":
        raise ProviderError("bad_request", "Последнее сообщение должно быть вопросом пользователя")

    async def events():
        yield sse("start", {"provider_id": setting.provider_id, "model_id": setting.model_id})
        try:
            async for text in provider.chat_stream(
                model=setting.model_id, system=build_system(body.task, body.title, body.transcript),
                messages=messages, max_tokens=MAX_TOKENS[body.task], temperature=setting.params.get("temperature"),
            ):
                yield sse("delta", {"text": text})
            yield sse("done", {})
        except ProviderError as e:
            e.message = redact(e.message, provider.api_key)
            yield sse("error", e.to_dict())

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class SegmentIn(BaseModel):
    i: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=2000)


class TranslateIn(BaseModel):
    target_language: str = Field(min_length=2, max_length=40)
    title: str | None = Field(default=None, max_length=500)
    segments: list[SegmentIn] = Field(min_length=1, max_length=MAX_SEGMENTS)


class TranslatedItem(BaseModel):
    i: int
    text: str


class TranslateOut(BaseModel):
    items: list[TranslatedItem]
    missing: list[int]
    provider_id: str
    model_id: str


@router.post("/translate", response_model=TranslateOut)
async def translate(body: TranslateIn, user: CurrentUser = Depends(current_user), s: AiServices = Depends(ai)):
    """Одна пачка фраз (≤120 шт., ≤12k символов). Фронт шлёт пачки по очереди и показывает прогресс."""
    if sum(len(x.text) for x in body.segments) > MAX_CHARS:
        raise ProviderError("bad_request", f"Слишком большая пачка (> {MAX_CHARS} символов)")
    _, settings = s.require_storage()
    setting = await settings.get(user.id, "translate")
    if not setting:
        raise ProviderError("not_configured", "Не выбран провайдер и модель для задачи «Перевод» в профиле")
    provider = await s.provider_for(user.id, setting.provider_id)
    segs = [(x.i, x.text) for x in body.segments]
    parts: list[str] = []
    try:
        async for chunk in provider.chat_stream(
            model=setting.model_id, system=build_translate_prompt(body.target_language, body.title),
            messages=build_translate_input(segs), max_tokens=max_tokens_for(segs),
            temperature=setting.params.get("temperature"),
        ):
            parts.append(chunk)
    except ProviderError as e:
        e.message = redact(e.message, provider.api_key)
        raise
    wanted = {i for i, _ in segs}
    got = parse_translation("".join(parts), wanted)
    return TranslateOut(items=[TranslatedItem(i=i, text=t) for i, t in sorted(got.items())],
                        missing=sorted(wanted - got.keys()), provider_id=setting.provider_id, model_id=setting.model_id)
