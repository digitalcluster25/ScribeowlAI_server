"""ChocoData — транскрипт по субтитрам (без распознавания речи).

Сверено 2026-09-25 с https://github.com/ChocoData-com/youtube-scraper (README), https://chocodata.com/openapi.json,
https://chocodata.com/scraper-api/youtube-transcript:
  GET https://api.chocodata.com/api/v1/youtube/transcript?api_key=...&video_id=..&lang=..&format=segments&units=seconds
  200: {transcript_available, language, available_languages, segments: [{text, start, duration}], time_unit, ...}
       transcript_available=false + reason (transcripts_disabled|none_found|members_only|age_restricted|video_unavailable)
  Ошибки: 401 {error:{code:INVALID_API_KEY}}, 402 INSUFFICIENT_CREDITS, 429 RATE_LIMITED,
          400 {error:"invalid_params"}, 502 {error:"target_unreachable"|"extraction_failed"}.
  Ключ только в query (api_key) — это запрос сервер→сервер, в логи наш httpx URL не пишет.
  Биллинг только за 2xx. Бесплатной проверки ключа нет — см. test_key.
"""

from __future__ import annotations

from app.transcripts.base import TranscriptProvider
from app.transcripts.errors import TranscriptError
from app.transcripts.models import Transcript, TranscriptSegment
from app.transcripts.normalize import fill_ends

URL = "https://api.chocodata.com/api/v1/youtube/transcript"
UNAVAILABLE = {"video_unavailable": "not_found"}


class ChocoDataProvider(TranscriptProvider):
    id = "chocodata"
    name = "ChocoData"
    docs_url = "https://chocodata.com/scraper-api/youtube-transcript"
    keys_url = "https://app.chocodata.com"
    pricing = "1000 запросов бесплатно без карты (разово); далее $0.90 за 1000. Без распознавания речи."
    requires_api_key = True
    api_key_setting = "chocodata_api_key"
    can_generate = False

    async def test_key(self, api_key: str) -> None:
        # Бесплатного эндпоинта нет; неуспешные запросы не тарифицируются. Запрос без video_id:
        # плохой ключ → 401, хороший → 400 invalid_params (порядок проверок у ChocoData не задокументирован).
        r = await self.request("GET", URL, params={"api_key": api_key})
        if r.status_code in (400, 422):
            return
        if r.status_code >= 400:
            raise self._error(r)

    async def fetch(self, video_id: str, language: str | None, api_key: str | None = None) -> Transcript:
        key = api_key or self.api_key
        if not key:
            raise self.error("unauthorized", f"{self.name}: ключ не добавлен (профиль → Транскрипты)")
        params = {"api_key": key, "video_id": video_id, "format": "segments", "units": "seconds"}
        if language:
            params["lang"] = language
        r = await self.request("GET", URL, params=params)
        if r.status_code >= 400:
            raise self._error(r)
        try:
            data = r.json()
        except ValueError as e:
            raise self.error("parse", f"{self.name}: ответ не JSON") from e
        if data.get("transcript_available") is False:
            reason = data.get("reason") or "none_found"
            raise self.error(UNAVAILABLE.get(reason, "no_captions"), f"{self.name}: транскрипта нет ({reason})")
        try:
            return map_response(data, video_id, self.id)
        except (KeyError, TypeError, ValueError) as e:
            raise self.error("parse", f"{self.name}: неожиданный ответ ({e})") from e

    def _error(self, r) -> TranscriptError:
        try:
            body = r.json()
        except ValueError:
            body = {}
        err = body.get("error") if isinstance(body, dict) else None
        code = (err.get("code") if isinstance(err, dict) else err) or ""
        msg = (err.get("message") if isinstance(err, dict) else None) or code or f"HTTP {r.status_code}"
        text = f"{self.name}: {msg}"
        if code == "INSUFFICIENT_CREDITS":
            return self.error("quota_exceeded", text, r.status_code)
        if code == "extraction_failed":
            return self.error("not_found", text, r.status_code)
        return self.http_error(r, text)


def map_response(data: dict, video_id: str, provider_id: str) -> Transcript:
    scale = 1000.0 if data.get("time_unit") == "ms" else 1.0
    segments = [
        TranscriptSegment(
            start=float(s["start"]) / scale,
            end=(float(s["start"]) + float(s.get("duration") or 0)) / scale,
            text=" ".join(str(s["text"]).split()),
            approximate=False,
        )
        for s in data["segments"]
        if str(s.get("text", "")).strip() and s.get("start") is not None
    ]
    segments.sort(key=lambda s: s.start)
    if any(s.end <= s.start for s in segments):
        filled = fill_ends([s.model_copy() for s in segments], None)
        for s, f in zip(segments, filled):
            if s.end <= s.start:
                s.end = f.end
    lang = data.get("language") or "und"
    langs = [lang] + [x for x in (data.get("available_languages") or []) if x != lang]
    return Transcript(video_id=video_id, language=lang, available_languages=langs,
                      provider_id=provider_id, segments=segments)
