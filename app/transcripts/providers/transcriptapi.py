"""transcriptapi.com — платный, ключ в Authorization: Bearer.

Сверено с https://transcriptapi.com/openapi.json (GET /api/v2/youtube/transcript):
  query: video_url (URL или 11-символьный id), language (список через запятую), format=json,
         include_timestamp (по умолчанию true), send_metadata.
  200: {video_id, language, transcript: [{text, start, duration}], metadata?: {title,...}, length_seconds?}
  401 — ключ, 402 — кредиты/план, 404 — нет видео/транскрипта, 408/503 — временно, 422 — плохой id, 429 — лимит.
"""

from __future__ import annotations

from app.transcripts.base import TranscriptProvider
from app.transcripts.errors import TranscriptError
from app.transcripts.models import Transcript, TranscriptSegment
from app.transcripts.normalize import fill_ends

URL = "https://transcriptapi.com/api/v2/youtube/transcript"
INFO_URL = "https://transcriptapi.com/api/v2/youtube/info"  # бесплатный (кредиты не тратит)


class TranscriptApiProvider(TranscriptProvider):
    id = "transcriptapi"
    name = "TranscriptAPI"
    docs_url = "https://transcriptapi.com/docs"
    keys_url = "https://transcriptapi.com/dashboard"
    pricing = "100 кредитов бесплатно без карты; $5/мес = 1000 транскриптов."
    requires_api_key = True
    api_key_setting = "transcriptapi_api_key"

    async def test_key(self, api_key: str) -> None:
        r = await self.request("GET", INFO_URL, params={"video_url": "dQw4w9WgXcQ"},
                               headers={"Authorization": f"Bearer {api_key}"})
        if r.status_code >= 400:
            raise self._error(r)

    async def fetch(self, video_id: str, language: str | None, api_key: str | None = None) -> Transcript:
        key = api_key or self.api_key
        if not key:
            raise self.error("unauthorized", f"{self.name}: ключ не добавлен (профиль → Транскрипты)")
        params = {"video_url": video_id, "format": "json", "include_timestamp": "true", "send_metadata": "true"}
        if language:
            params["language"] = language
        r = await self.request("GET", URL, params=params, headers={"Authorization": f"Bearer {key}"})
        if r.status_code >= 400:
            raise self._error(r)
        try:
            return map_response(r.json(), video_id, self.id)
        except (ValueError, KeyError, TypeError) as e:
            raise self.error("parse", f"{self.name}: неожиданный ответ ({e})", r.status_code) from e

    def _error(self, r) -> TranscriptError:
        try:
            body = r.json()
        except ValueError:
            body = {}
        detail = body.get("detail") if isinstance(body, dict) else None
        msg = detail.get("message") if isinstance(detail, dict) else detail
        err = self.http_error(r, f"{self.name}: {msg or f'HTTP {r.status_code}'}")
        if r.status_code == 404 and "no transcript" in str(msg).lower():
            err.code = "no_captions"
        return err


def map_response(data: dict, video_id: str, provider_id: str) -> Transcript:
    items = data["transcript"]
    if not isinstance(items, list):
        raise TypeError("transcript не список (нужен format=json)")
    duration = data.get("length_seconds")
    segments = [
        TranscriptSegment(
            start=float(it["start"]),
            end=float(it["start"]) + float(it.get("duration") or 0),
            text=" ".join(str(it["text"]).split()),
            approximate=False,
        )
        for it in items
        if str(it.get("text", "")).strip() and it.get("start") is not None
    ]
    segments.sort(key=lambda s: s.start)
    # концы от провайдера точные; достраиваем только пустые (duration=0)
    if any(s.end <= s.start for s in segments):
        ends = [s.end for s in segments]
        filled = fill_ends([s.model_copy() for s in segments], duration)
        for s, e, f in zip(segments, ends, filled):
            s.end = e if e > s.start else f.end
    meta = data.get("metadata") or {}
    lang = data.get("language") or "und"
    return Transcript(
        video_id=data.get("video_id") or video_id, language=lang, title=meta.get("title"),
        duration=float(duration) if duration else None, available_languages=[lang],
        provider_id=provider_id, segments=segments,
    )
