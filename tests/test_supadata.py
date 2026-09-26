"""Supadata: формат по https://docs.supadata.ai (get-transcript, errors). Фикстура — по схеме из доки."""

import json

import httpx
import pytest

import app.transcripts.providers.supadata as sd
from app.transcripts.errors import TranscriptError
from app.transcripts.providers.supadata import SupadataProvider, map_response
from app.transcripts.registry import TranscriptProviderRegistry
from app.transcripts.service import TranscriptService

from .conftest import fixture_text, make_settings, mock_client

DOC = json.loads(fixture_text("supadata_docs_example.json"))


def err(status, code, details):
    return httpx.Response(status, json={"error": code, "message": code, "details": details,
                                        "documentationUrl": f"https://docs.supadata.ai/errors/{code}"})


def test_map_ms_to_seconds():
    t = map_response(DOC, "dQw4w9WgXcQ", "supadata")
    assert [(s.start, s.end, s.text, s.approximate) for s in t.segments] == [
        (18.0, 21.4, "Never gonna give you up", False), (21.4, 24.3, "Never gonna let you down", False)]
    assert t.language == "en" and t.available_languages == ["en", "de", "ja"]


async def test_request_shape_and_sync_200():
    seen = {}

    def h(req):
        seen["req"] = req
        return httpx.Response(200, json=DOC)

    await SupadataProvider(None, mock_client(h)).fetch("dQw4w9WgXcQ", "de", api_key="sd-key-123456")
    r = seen["req"]
    assert r.url.path == "/v1/transcript" and r.headers["x-api-key"] == "sd-key-123456"
    q = dict(r.url.params)
    assert q == {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "text": "false", "mode": "auto", "lang": "de"}


async def test_async_job_polling(monkeypatch):
    monkeypatch.setattr(sd, "POLL_INTERVAL", 0)
    polls = []

    def h(req):
        if req.url.path == "/v1/transcript":
            return httpx.Response(202, json={"jobId": "job-1"})
        polls.append(req.url.path)
        if len(polls) < 3:
            return httpx.Response(200, json={"status": "active"})
        return httpx.Response(200, json={"status": "completed", **DOC})

    t = await SupadataProvider(None, mock_client(h)).fetch("x" * 11, None, api_key="k" * 10)
    assert polls == ["/v1/transcript/job-1"] * 3 and len(t.segments) == 2


async def test_job_failed(monkeypatch):
    monkeypatch.setattr(sd, "POLL_INTERVAL", 0)

    def h(req):
        if req.url.path == "/v1/transcript":
            return httpx.Response(202, json={"jobId": "j"})
        return httpx.Response(200, json={"status": "failed", "error": {"message": "boom"}})

    with pytest.raises(TranscriptError) as e:
        await SupadataProvider(None, mock_client(h)).fetch("x" * 11, None, api_key="k" * 10)
    assert e.value.code == "no_captions" and "boom" in e.value.message


@pytest.mark.parametrize("resp,code", [
    (err(401, "unauthorized", "Invalid API key"), "unauthorized"),
    (err(206, "transcript-unavailable", "No transcript is available for this video"), "no_captions"),
    (err(429, "limit-exceeded", "Plan usage limit was exceeded."), "quota_exceeded"),
    (err(429, "limit-exceeded", "Request rate limit on current plan was exceeded."), "rate_limited"),
    (err(404, "not-found", "Video not found"), "not_found"),
    (err(402, "upgrade-required", "Feature not in plan"), "quota_exceeded"),
])
async def test_errors(resp, code):
    with pytest.raises(TranscriptError) as e:
        await SupadataProvider(None, mock_client(lambda r: resp)).fetch("x" * 11, None, api_key="k" * 10)
    assert e.value.code == code


async def test_key_check_uses_free_me_endpoint():
    seen = []

    def h(req):
        seen.append(req.url.path)
        return httpx.Response(200, json={"organizationId": "o", "plan": "Free", "maxCredits": 100, "usedCredits": 0})

    await SupadataProvider(None, mock_client(h)).test_key("sd-key-123456")
    assert seen == ["/v1/me"]


async def test_no_captions_falls_through_to_generator_only():
    calls = []

    def h(req):
        calls.append(req.url.host)
        if req.url.host == "youtube-transcript.ai":
            return httpx.Response(200, text=fixture_text("yta_no_captions.txt"))
        if req.url.host == "transcriptapi.com":
            return httpx.Response(404, json={"detail": "No transcript available"})
        return httpx.Response(200, json=DOC)

    reg = TranscriptProviderRegistry(
        make_settings(transcript_providers_order="youtube_transcript_ai,transcriptapi,supadata",
                      transcriptapi_api_key="t" * 10, supadata_api_key="s" * 10), mock_client(h))
    t = await TranscriptService(reg).get("KoJoLLxbYjk")
    # transcriptapi пропущен: он не умеет распознавать речь, а субтитров нет
    assert t.provider_id == "supadata" and calls == ["youtube-transcript.ai", "api.supadata.ai"]


async def test_no_captions_without_generator_raises():
    reg = TranscriptProviderRegistry(make_settings(transcript_providers_order="youtube_transcript_ai,transcriptapi",
                                                   transcriptapi_api_key="t" * 10),
                                     mock_client(lambda r: httpx.Response(200, text=fixture_text("yta_no_captions.txt"))))
    with pytest.raises(TranscriptError) as e:
        await TranscriptService(reg).get("KoJoLLxbYjk")
    assert e.value.code == "no_captions"
