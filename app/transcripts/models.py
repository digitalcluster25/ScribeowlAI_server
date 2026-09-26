from __future__ import annotations

from pydantic import BaseModel


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    # True — время начала/конца оценено (провайдер отдал только метку абзаца)
    approximate: bool = False


class Transcript(BaseModel):
    video_id: str
    language: str
    title: str | None = None
    duration: float | None = None
    available_languages: list[str] = []
    provider_id: str
    segments: list[TranscriptSegment]
    # False — провайдер не дал времени фраз (только текст); фронт раскладывает строки по длине видео (≈)
    timed: bool = True
    # полный текст, если сегментов нет (timed=False)
    text: str | None = None


class TranscriptProviderInfo(BaseModel):
    id: str
    name: str
    requires_api_key: bool
    configured: bool
    docs_url: str
    keys_url: str | None = None
    # откуда ключ: "user" — из профиля пользователя, "server" — из env сервера
    key_source: str | None = None
    # статус ключа пользователя (маска/проверка), если он добавлен
    credential: dict | None = None
    can_generate: bool = False  # распознаёт речь, если у видео нет субтитров
    timed: bool = True  # отдаёт время фраз
    pricing: str | None = None  # условия с сайта провайдера (дата сверки — в коде провайдера)
