"""ChocoData и EasyTranscriber: форматы по их официальной документации (README/OpenAPI), 2026-09-25."""

import json

import httpx
import pytest

from app.transcripts.errors import TranscriptError
from app.transcripts.providers.chocodata import ChocoDataProvider
from app.transcripts.providers.easytranscriber import EasyTranscriberProvider

from .conftest import mock_client

# пример из README ChocoData (сегменты сокращены)
CHOCO = {"video_id": "x7X9w_GIm1s", "transcript_available": True, "language": "en",
         "language_name": "English (auto-generated)", "is_generated": True, "source": "asr",
         "time_unit": "seconds", "available_languages": ["en"],
         "segments": [{"text": "python a highlevel interpreted", "start": 0.16, "duration": 4.08},
                      {"text": "language", "start": 4.24, "duration": 1.5}]}
# пример из доки EasyTranscriber
EASY = {"video_id": "dQw4w9WgXcQ", "video_title": "Video Title", "transcript": "Full transcript text...",
        "method": "captions", "cached": False, "credits_used": 1}


async def test_choco_request_and_map():
    seen = {}

    def h(req):
        seen["req"] = req
        return httpx.Response(200, json=CHOCO)

    t = await ChocoDataProvider(None, mock_client(h)).fetch("x7X9w_GIm1s", "en", api_key="asa_live_123")
    q = dict(seen["req"].url.params)
    assert seen["req"].url.path == "/api/v1/youtube/transcript"
    assert q == {"api_key": "asa_live_123", "video_id": "x7X9w_GIm1s", "format": "segments", "units": "seconds", "lang": "en"}
    assert [(s.start, round(s.end, 2), s.approximate) for s in t.segments] == [(0.16, 4.24, False), (4.24, 5.74, False)]
    assert t.timed is True and t.language == "en"


async def test_choco_ms_units_and_unavailable():
    data = {**CHOCO, "time_unit": "ms", "segments": [{"text": "hi", "start": 1360, "duration": 1680}]}
    t = await ChocoDataProvider(None, mock_client(lambda r: httpx.Response(200, json=data))).fetch("x" * 11, None, "k" * 10)
    assert (t.segments[0].start, t.segments[0].end) == (1.36, 3.04)
    for reason, code in [("none_found", "no_captions"), ("transcripts_disabled", "no_captions"),
                         ("video_unavailable", "not_found")]:
        body = {"transcript_available": False, "reason": reason}
        with pytest.raises(TranscriptError) as e:
            await ChocoDataProvider(None, mock_client(lambda r, b=body: httpx.Response(200, json=b))).fetch("x" * 11, None, "k" * 10)
        assert e.value.code == code


@pytest.mark.parametrize("status,body,code", [
    (401, {"error": {"code": "INVALID_API_KEY", "message": "Api key not recognised."}}, "unauthorized"),
    (402, {"error": {"code": "INSUFFICIENT_CREDITS", "message": "no credits"}}, "quota_exceeded"),
    (429, {"error": {"code": "RATE_LIMITED", "message": "slow"}}, "rate_limited"),
    (502, {"error": "target_unreachable", "retryable": True}, "network"),
    (502, {"error": "extraction_failed"}, "not_found"),
])
async def test_choco_errors(status, body, code):
    with pytest.raises(TranscriptError) as e:
        await ChocoDataProvider(None, mock_client(lambda r: httpx.Response(status, json=body))).fetch("x" * 11, None, "k" * 10)
    assert e.value.code == code


async def test_choco_key_check():
    good = ChocoDataProvider(None, mock_client(lambda r: httpx.Response(400, json={"error": "invalid_params", "issues": []})))
    await good.test_key("asa_live_ok")
    bad = ChocoDataProvider(None, mock_client(lambda r: httpx.Response(401, json={"error": {"code": "INVALID_API_KEY"}})))
    with pytest.raises(TranscriptError) as e:
        await bad.test_key("asa_live_bad")
    assert e.value.code == "unauthorized"


async def test_easy_request_and_untimed():
    seen = {}

    def h(req):
        seen["req"] = req
        return httpx.Response(200, json=EASY)

    t = await EasyTranscriberProvider(None, mock_client(h)).fetch("dQw4w9WgXcQ", "de", api_key="et_key123456")
    r = seen["req"]
    assert r.method == "POST" and r.url.path == "/api/v1/transcribe"
    assert r.headers["authorization"] == "Bearer et_key123456"
    assert json.loads(r.content) == {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    assert t.timed is False and t.segments == [] and t.text == "Full transcript text..." and t.title == "Video Title"


@pytest.mark.parametrize("status,code,expected", [
    (401, "unauthorized", "unauthorized"), (402, "insufficient_credits", "quota_exceeded"),
    (429, "rate_limited", "rate_limited"), (500, "transcription_failed", "network"),
    (503, "quota_exceeded", "network"), (404, "not_found", "not_found"),
])
async def test_easy_errors(status, code, expected):
    body = {"error": {"code": code, "message": f"msg {code}"}}
    with pytest.raises(TranscriptError) as e:
        await EasyTranscriberProvider(None, mock_client(lambda r: httpx.Response(status, json=body))).fetch("x" * 11, None, "k" * 10)
    assert e.value.code == expected and f"msg {code}" in e.value.message


async def test_easy_key_check_free_credits_endpoint():
    seen = []

    def h(req):
        seen.append((req.method, req.url.path))
        return httpx.Response(200, json={"balance": 5})

    await EasyTranscriberProvider(None, mock_client(h)).test_key("et_key123456")
    assert seen == [("GET", "/api/v1/credits")]
