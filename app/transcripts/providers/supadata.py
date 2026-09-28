"""Supadata — транскрипт YouTube, при отсутствии субтитров генерирует его сам (mode=auto).

Сверено с https://docs.supadata.ai (get-transcript, errors, account/me), 2026-09-25:
  GET https://api.supadata.ai/v1/transcript?url=...&lang=..&text=false&mode=auto, заголовок x-api-key.
  200: {content: [{text, offset(ms), duration(ms), lang}], lang, availableLangs}
  202: {jobId} → GET /v1/transcript/{jobId} раз в секунду: status queued|active|completed|failed
  Ошибки: {error, message, details}; 400 invalid-request, 401 unauthorized, 402 upgrade-required,
  403 forbidden, 404 not-found, 429 limit-exceeded (details различает rate vs квоту),
  206 transcript-unavailable, 500 internal-error.
  Стоимость: 1 кредит за готовые субтитры, 2 кредита/мин за генерацию. GET /v1/me — без кредитов.
"""

from __future__ import annotations

import asyncio

from app.transcripts.base import TranscriptProvider
from app.transcripts.errors import TranscriptError
from app.transcripts.models import Transcript, TranscriptSegment
from app.transcripts.normalize import fill_ends

BASE = "https://api.supadata.ai/v1"
POLL_INTERVAL = 1.0
POLL_TIMEOUT = 240.0  # генерация длинного видео может идти минуты


class SupadataProvider(TranscriptProvider):
    id = "supadata"
    name = "Supadata"
    docs_url = "https://docs.supadata.ai/get-transcript"
    keys_url = "https://dash.supadata.ai"
    pricing = "100 кредитов/мес бесплатно без карты (не переносятся); субтитры — 1 кредит, распознавание — 2 кредита/мин."
    requires_api_key = True
    api_key_setting = "supadata_api_key"
    can_generate = True  # умеет распознавать речь, если субтитров нет

    def _headers(self, key: str) -> dict:
        return {"x-api-key": key}

    async def test_key(self, api_key: str) -> None:
        r = await self.request("GET", f"{BASE}/me", headers=self._headers(api_key))
        if r.status_code >= 400:
            raise self._error(r)

    async def fetch(self, video_id: str, language: str | None, api_key: str | None = None) -> Transcript:
        key = api_key or self.api_key
        if not key:
            raise self.error("unauthorized", f"{self.name}: ключ не добавлен (профиль → Транскрипты)")
        params = {"url": f"https://www.youtube.com/watch?v={video_id}", "text": "false", "mode": "auto"}
        if language:
            params["lang"] = language
        r = await self.request("GET", f"{BASE}/transcript", params=params, headers=self._headers(key))
        if r.status_code == 202:
            data = await self._poll(r.json().get("jobId"), key)
        elif r.status_code == 200:
            data = r.json()
        else:
            raise self._error(r)
        try:
            return map_response(data, video_id, self.id)
        except (KeyError, TypeError, ValueError) as e:
            raise self.error("parse", f"{self.name}: неожиданный ответ ({e})") from e

    async def _poll(self, job_id: str | None, key: str) -> dict:
        if not job_id:
            raise self.error("parse", f"{self.name}: 202 без jobId")
        waited = 0.0
        while waited < POLL_TIMEOUT:
            await asyncio.sleep(POLL_INTERVAL)
            waited += POLL_INTERVAL
            r = await self.request("GET", f"{BASE}/transcript/{job_id}", headers=self._headers(key))
            if r.status_code >= 400:
                raise self._error(r)
            data = r.json()
            status = data.get("status")
            if status == "completed":
                return data
            if status == "failed":
                err = data.get("error") or {}
                msg = err.get("message") if isinstance(err, dict) else err
                raise self.error("no_captions", f"{self.name}: не удалось получить транскрипт ({msg or 'failed'})")
        raise self.error("network", f"{self.name}: транскрипт не готов за {int(POLL_TIMEOUT)} с")

    def _error(self, r) -> TranscriptError:
        try:
            body = r.json()
        except ValueError:
            body = {}
        code_name = body.get("error") if isinstance(body, dict) else None
        details = (body.get("details") or body.get("message")) if isinstance(body, dict) else None
        msg = f"{self.name}: {details or code_name or f'HTTP {r.status_code}'}"
        if r.status_code == 206 or code_name == "transcript-unavailable":
            return self.error("no_captions", msg, r.status_code)
        if code_name == "limit-exceeded" and "usage limit" in str(details).lower():
            return self.error("quota_exceeded", msg, r.status_code)
        return self.http_error(r, msg)


def map_response(data: dict, video_id: str, provider_id: str) -> Transcript:
    items = data["content"]
    if not isinstance(items, list):
        raise TypeError("content не список (нужен text=false)")
    segments = [
        TranscriptSegment(
            start=float(it["offset"]) / 1000,
            end=(float(it["offset"]) + float(it.get("duration") or 0)) / 1000,
            text=" ".join(str(it["text"]).split()),
            approximate=False,
        )
        for it in items
        if str(it.get("text", "")).strip() and it.get("offset") is not None
    ]
    segments.sort(key=lambda s: s.start)
    if any(s.end <= s.start for s in segments):
        filled = fill_ends([s.model_copy() for s in segments], None)
        for s, f in zip(segments, filled):
            if s.end <= s.start:
                s.end = f.end
    lang = data.get("lang") or "und"
    langs = [lang] + [x for x in (data.get("availableLangs") or []) if x != lang]
    return Transcript(video_id=video_id, language=lang, title=None, duration=None,
                      available_languages=langs, provider_id=provider_id, segments=segments)
