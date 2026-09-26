import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.transcripts.registry import TranscriptProviderRegistry
from app.transcripts.service import TranscriptService

from .conftest import fixture_text, make_settings, mock_client


def client_with(handler):
    c = TestClient(app)
    c.__enter__()
    reg = TranscriptProviderRegistry(make_settings(), mock_client(handler))
    app.state.transcript_registry = reg
    app.state.transcript_service = TranscriptService(reg)
    return c


def test_providers_list():
    c = client_with(lambda r: None)
    body = c.get("/transcripts/providers").json()
    assert [p["id"] for p in body][:2] == ["youtube_transcript_ai", "transcriptapi"]
    assert "api_key" not in str(body).lower().replace("requires_api_key", "")


def test_post_ok_and_errors():
    c = client_with(lambda r: httpx.Response(200, text=fixture_text("yta_dQw4w9WgXcQ.txt")))
    r = c.post("/transcripts", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    assert r.status_code == 200 and r.json()["provider_id"] == "youtube_transcript_ai"
    assert c.post("/transcripts", json={"url": "https://vimeo.com/1"}).status_code == 422
    assert c.post("/transcripts", json={}).status_code == 422

    c = client_with(lambda r: httpx.Response(429, text="x"))
    r = c.post("/transcripts", json={"video_id": "dQw4w9WgXcQ"})
    assert r.status_code == 429 and r.json() == {
        "code": "rate_limited", "message": "youtube-transcript.ai: HTTP 429", "provider_id": "youtube_transcript_ai"}
