"""EasyTranscriber — транскрипт одним текстом (без времени фраз и без выбора языка).

Сверено 2026-09-25 с https://www.easytranscriber.com/docs/api и /openapi-complete.json:
  POST https://www.easytranscriber.com/api/v1/transcribe  {"url": ...}, Authorization: Bearer et_...
  200: {video_id, video_title, transcript (строка), method, cached, credits_used}
  Ошибки: {error:{code,message}} — 401 unauthorized, 402 insufficient_credits, 429 rate_limited,
          400 invalid_request, 404 not_found, 500 transcription_failed, 502 youtube_api_error, 503 quota_exceeded.
  GET /api/v1/credits — бесплатная проверка ключа ({"balance": N}).
  method ∈ yt-dlp|innertube|deepgram|deepgram-diarized — похоже, распознаёт речь сам (в доке прямо не сказано).
Времени фраз нет → segments пустые, текст отдаём в Transcript.text; фронт раскладывает строки по длине видео (≈).
"""

from __future__ import annotations

from app.transcripts.base import TranscriptProvider
from app.transcripts.errors import TranscriptError
from app.transcripts.models import Transcript

BASE = "https://www.easytranscriber.com/api/v1"


class EasyTranscriberProvider(TranscriptProvider):
    id = "easytranscriber"
    name = "EasyTranscriber"
    docs_url = "https://www.easytranscriber.com/docs/api"
    keys_url = "https://www.easytranscriber.com/dashboard/api-keys"
    pricing = "5 кредитов при регистрации (+1/день); Plus $4.99/мес = 200. API, возможно, только на Pro ($9.99)."
    requires_api_key = True
    api_key_setting = "easytranscriber_api_key"
    can_generate = True  # UNVERIFIED: method=deepgram в схеме ответа
    timed = False

    def _headers(self, key: str) -> dict:
        return {"Authorization": f"Bearer {key}"}

    async def test_key(self, api_key: str) -> None:
        r = await self.request("GET", f"{BASE}/credits", headers=self._headers(api_key))
        if r.status_code >= 400:
            raise self._error(r)

    async def fetch(self, video_id: str, language: str | None, api_key: str | None = None) -> Transcript:
        key = api_key or self.api_key
        if not key:
            raise self.error("unauthorized", f"{self.name}: ключ не добавлен (профиль → Транскрипты)")
        r = await self.request("POST", f"{BASE}/transcribe", json={"url": f"https://www.youtube.com/watch?v={video_id}"},
                               headers=self._headers(key))
        if r.status_code >= 400:
            raise self._error(r)
        try:
            data = r.json()
            text = " ".join(str(data["transcript"]).split())
        except (ValueError, KeyError, TypeError) as e:
            raise self.error("parse", f"{self.name}: неожиданный ответ ({e})") from e
        if not text:
            raise self.error("no_captions", f"{self.name}: пустой транскрипт")
        return Transcript(video_id=data.get("video_id") or video_id, language="und", title=data.get("video_title"),
                          provider_id=self.id, segments=[], text=text, timed=False)

    def _error(self, r) -> TranscriptError:
        try:
            body = r.json()
        except ValueError:
            body = {}
        err = body.get("error") if isinstance(body, dict) else None
        code = err.get("code") if isinstance(err, dict) else None
        detail = (err.get("message") if isinstance(err, dict) else None) or code or f"HTTP {r.status_code}"
        msg = f"{self.name}: {detail}"
        if code == "insufficient_credits":
            return self.error("quota_exceeded", msg, r.status_code)
        if code in ("quota_exceeded", "youtube_api_error", "transcription_failed"):
            return self.error("network", msg, r.status_code)  # временно — пусть фолбэк/повтор
        return self.http_error(r, msg)
