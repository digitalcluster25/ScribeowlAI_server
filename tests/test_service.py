import httpx
import pytest

from app.transcripts.errors import TranscriptError
from app.transcripts.registry import TranscriptProviderRegistry
from app.transcripts.service import TranscriptService

from .conftest import fixture_text, make_settings, mock_client

TAPI = {"video_id": "dQw4w9WgXcQ", "language": "en", "transcript": [{"text": "hi", "start": 0, "duration": 1}]}


def build(handler, **settings):
    calls = []

    def wrapped(req):
        calls.append(req.url.host)
        return handler(req)

    reg = TranscriptProviderRegistry(make_settings(**settings), mock_client(wrapped))
    return TranscriptService(reg), calls, reg


def test_registry_order_and_configured():
    _, _, reg = build(lambda r: None, transcript_providers_order="transcriptapi,youtube_transcript_ai")
    assert [p.id for p in reg.list()][:2] == ["transcriptapi", "youtube_transcript_ai"]
    assert [p.configured for p in reg.list()][:2] == [False, True]
    assert [p.id for p in reg.ordered()] == ["youtube_transcript_ai"]  # без ключа пропущен
    _, _, reg2 = build(lambda r: None, transcriptapi_api_key="k")
    assert [p.id for p in reg2.ordered()] == ["youtube_transcript_ai", "transcriptapi"]


async def test_fallback_on_rate_limit():
    def handler(req):
        if req.url.host == "youtube-transcript.ai":
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json=TAPI)

    svc, calls, _ = build(handler, transcriptapi_api_key="k")
    t = await svc.get("dQw4w9WgXcQ")
    assert t.provider_id == "transcriptapi"
    assert calls == ["youtube-transcript.ai", "transcriptapi.com"]


async def test_no_fallback_on_not_found():
    svc, calls, _ = build(lambda r: httpx.Response(404, text=fixture_text("yta_not_found.txt")),
                          transcriptapi_api_key="k")
    with pytest.raises(TranscriptError) as e:
        await svc.get("AAAAAAAAAAA")
    assert e.value.code == "not_found" and calls == ["youtube-transcript.ai"]


async def test_all_fail_raises_last():
    svc, _, _ = build(lambda r: httpx.Response(429, text="x"), transcriptapi_api_key="k")
    with pytest.raises(TranscriptError) as e:
        await svc.get("dQw4w9WgXcQ")
    assert e.value.code == "rate_limited" and e.value.provider_id == "transcriptapi"


async def test_specific_provider_and_cache():
    svc, calls, _ = build(lambda r: httpx.Response(200, text=fixture_text("yta_dQw4w9WgXcQ.txt")))
    a = await svc.get("dQw4w9WgXcQ", None, "youtube_transcript_ai")
    b = await svc.get("dQw4w9WgXcQ", None, "youtube_transcript_ai")
    assert a is b and len(calls) == 1
    with pytest.raises(TranscriptError) as e:
        await svc.get("dQw4w9WgXcQ", None, "transcriptapi")
    assert e.value.code == "unauthorized"
    with pytest.raises(TranscriptError):
        await svc.get("dQw4w9WgXcQ", None, "nope")


async def test_cache_ttl_expires():
    now = [0.0]
    svc, calls, _ = build(lambda r: httpx.Response(200, text=fixture_text("yta_dQw4w9WgXcQ.txt")))
    svc.clock = lambda: now[0]
    await svc.get("dQw4w9WgXcQ")
    now[0] = 24 * 3600 + 1
    await svc.get("dQw4w9WgXcQ")
    assert len(calls) == 2
