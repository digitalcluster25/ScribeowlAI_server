import json

import httpx
import pytest

from app.transcripts.errors import TranscriptError
from app.transcripts.providers.transcriptapi import TranscriptApiProvider, map_response

from .conftest import fixture_text, make_settings, mock_client


def test_map_docs_example():
    data = json.loads(fixture_text("transcriptapi_docs_example.json"))
    t = map_response(data, "dQw4w9WgXcQ", "transcriptapi")
    assert t.language == "en" and t.duration == 213
    assert t.title == "Rick Astley - Never Gonna Give You Up"
    assert [(s.start, round(s.end, 2), s.text, s.approximate) for s in t.segments] == [
        (0.0, 4.12, "Never gonna give you up", False),
        (4.12, 7.97, "Never gonna let you down", False),
    ]


def _provider(handler, key="k-123"):
    return TranscriptApiProvider(make_settings(transcriptapi_api_key=key), mock_client(handler))


async def test_request_shape():
    seen = {}

    def handler(req: httpx.Request):
        seen["req"] = req
        return httpx.Response(200, json=json.loads(fixture_text("transcriptapi_docs_example.json")))

    await _provider(handler).fetch("dQw4w9WgXcQ", "de,en")
    req = seen["req"]
    assert req.url.path == "/api/v2/youtube/transcript"
    assert req.headers["authorization"] == "Bearer k-123"
    q = dict(req.url.params)
    assert q["video_url"] == "dQw4w9WgXcQ" and q["format"] == "json" and q["language"] == "de,en"


@pytest.mark.parametrize("status,body,code", [
    (401, {"detail": "Invalid API key"}, "unauthorized"),
    (402, {"detail": {"message": "You have an active plan, but you've run out of credits.",
                      "reason": "insufficient_credits", "action_label": "Top up credits",
                      "action_url": "https://transcriptapi.com/top-up"}}, "quota_exceeded"),
    (404, {"detail": "No transcript available for video ABC123XYZ"}, "no_captions"),
    (404, {"detail": "Video not found or unavailable"}, "not_found"),
    (408, {"detail": "Request failed, please retry"}, "network"),
    (429, {"detail": "Rate limit exceeded"}, "rate_limited"),
    (503, {"detail": "Service not initialized"}, "network"),
])
async def test_errors(status, body, code):
    with pytest.raises(TranscriptError) as e:
        await _provider(lambda r: httpx.Response(status, json=body)).fetch("dQw4w9WgXcQ", None)
    assert e.value.code == code and e.value.provider_id == "transcriptapi"


async def test_no_key_is_unauthorized_and_not_configured():
    p = _provider(lambda r: httpx.Response(500), key="")
    assert p.configured is False
    with pytest.raises(TranscriptError) as e:
        await p.fetch("dQw4w9WgXcQ", None)
    assert e.value.code == "unauthorized"
