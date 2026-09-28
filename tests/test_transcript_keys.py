import json
import os

import httpx
from fastapi.testclient import TestClient

from app.ai.catalog import ModelCatalog
from app.ai.credentials import CredentialStore
from app.ai.registry import ProviderRegistry
from app.ai.settings_service import AiSettingsService
from app.api.deps import AiServices
from app.main import app
from app.security.crypto import KeyCipher
from app.transcripts.registry import TranscriptProviderRegistry
from app.transcripts.service import TranscriptService

from .conftest import fixture_text, make_settings, mock_client
from .test_ai_api import FakeRest, FakeVerifier

USER_KEY = "tapi-user-key-9999"
DOC = json.loads(fixture_text("transcriptapi_docs_example.json"))


def setup(server_key="", info_status=200):
    seen = []

    def h(req: httpx.Request):
        seen.append((req.url.host, req.url.path, req.headers.get("authorization")))
        if req.url.host == "youtube-transcript.ai":
            return httpx.Response(429, text="slow down")
        if req.url.path.endswith("/info"):
            if info_status != 200:
                return httpx.Response(info_status, json={"detail": "Invalid API key"})
            return httpx.Response(200, json={"video_id": "dQw4w9WgXcQ", "available_languages": []})
        return httpx.Response(200, json=DOC)

    c = TestClient(app)
    c.__enter__()
    db = FakeRest()
    reg = TranscriptProviderRegistry(make_settings(transcriptapi_api_key=server_key), mock_client(h))
    app.state.transcript_registry = reg
    app.state.transcript_service = TranscriptService(reg)
    app.state.ai = AiServices(ProviderRegistry(), CredentialStore(db, KeyCipher({1: os.urandom(32)}, 1)),
                              AiSettingsService(db), ModelCatalog())
    app.state.jwt_verifier = FakeVerifier()
    return c, db, seen


AUTH = {"Authorization": "Bearer good-token"}


def test_user_key_flow_and_precedence():
    c, db, seen = setup(server_key="server-key-0000")
    # без входа: transcriptapi настроен ключом сервера
    anon = {p["id"]: p for p in c.get("/transcripts/providers").json()}
    assert anon["transcriptapi"]["configured"] and anon["transcriptapi"]["key_source"] == "server"
    assert anon["transcriptapi"]["keys_url"]

    r = c.put("/transcripts/providers/transcriptapi/credentials", json={"api_key": USER_KEY}, headers=AUTH)
    assert r.status_code == 200 and r.json()["ok"] and r.json()["credential"]["key_hint"] == "9999"
    assert seen[-1] == ("transcriptapi.com", "/api/v2/youtube/info", f"Bearer {USER_KEY}")
    assert USER_KEY not in json.dumps(db.tables["provider_credentials"])

    mine = {p["id"]: p for p in c.get("/transcripts/providers", headers=AUTH).json()}
    assert mine["transcriptapi"]["key_source"] == "user" and mine["transcriptapi"]["credential"]["status"] == "valid"
    assert USER_KEY not in c.get("/transcripts/providers", headers=AUTH).text

    # youtube-transcript.ai упёрся в лимит → фолбэк на transcriptapi с КЛЮЧОМ ПОЛЬЗОВАТЕЛЯ
    t = c.post("/transcripts", json={"video_id": "dQw4w9WgXcQ"}, headers=AUTH)
    assert t.status_code == 200 and t.json()["provider_id"] == "transcriptapi"
    assert seen[-1][2] == f"Bearer {USER_KEY}"

    assert c.delete("/transcripts/providers/transcriptapi/credentials", headers=AUTH).status_code == 204
    assert {p["id"]: p for p in c.get("/transcripts/providers", headers=AUTH).json()}["transcriptapi"]["key_source"] == "server"


def test_no_keys_anywhere_and_invalid_key():
    c, _, _ = setup(server_key="", info_status=401)
    anon = {p["id"]: p for p in c.get("/transcripts/providers").json()}
    assert anon["transcriptapi"]["configured"] is False and anon["transcriptapi"]["key_source"] is None
    r = c.put("/transcripts/providers/transcriptapi/credentials", json={"api_key": "bad-key-00000"}, headers=AUTH)
    body = r.json()
    assert body["ok"] is False and body["error"]["code"] == "unauthorized" and body["credential"]["status"] == "invalid"


def test_key_endpoints_require_login_and_known_provider():
    c, _, _ = setup()
    assert c.put("/transcripts/providers/transcriptapi/credentials", json={"api_key": USER_KEY}).status_code == 401
    assert c.put("/transcripts/providers/youtube_transcript_ai/credentials", json={"api_key": USER_KEY},
                 headers=AUTH).status_code == 404
    assert c.get("/transcripts/providers", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_key_echoed_by_provider_is_redacted():
    """Supadata возвращает ключ в тексте ошибки — в БД/ответе его быть не должно."""
    c, db, _ = setup()
    secret = "sd-real-key-with-typo-1234"

    def h(req):
        return httpx.Response(401, json={"error": "unauthorized", "message": "Unauthorized",
                                         "details": f"Invalid API Key: {req.headers.get('x-api-key')}"})

    app.state.transcript_registry.client = mock_client(h)
    app.state.transcript_registry._instances.clear()
    r = c.put("/transcripts/providers/supadata/credentials", json={"api_key": secret}, headers=AUTH)
    assert r.status_code == 200 and secret not in r.text and "••••1234" in r.text
    assert secret not in json.dumps(db.tables["provider_credentials"])
