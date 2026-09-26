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
from app.security.auth import CurrentUser
from app.security.crypto import KeyCipher

SECRET = "sk-or-v1-supersecret-abcd"


class FakeRest:
    """In-memory замена SupabaseRest (select/upsert/update/delete по eq-фильтрам)."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}

    def _rows(self, t):
        return self.tables.setdefault(t, [])

    async def select(self, table, **f):
        return [dict(r) for r in self._rows(table) if all(str(r.get(k)) == str(v) for k, v in f.items())]

    async def upsert(self, table, row, on_conflict):
        keys = on_conflict.split(",")
        rows = self._rows(table)
        for r in rows:
            if all(r.get(k) == row.get(k) for k in keys):
                r.update(row)
                return dict(r)
        rows.append({"params": {}, **row})
        return dict(rows[-1])

    async def update(self, table, values, **f):
        for r in self._rows(table):
            if all(str(r.get(k)) == str(v) for k, v in f.items()):
                r.update(values)

    async def delete(self, table, **f):
        self.tables[table] = [r for r in self._rows(table) if not all(str(r.get(k)) == str(v) for k, v in f.items())]


class FakeVerifier:
    def verify(self, token):
        if token != "good-token":
            from fastapi import HTTPException
            raise HTTPException(401, "bad token")
        return CurrentUser(id="user-1", email="dev@x")


def openrouter_handler(req: httpx.Request):
    assert req.headers["authorization"] == f"Bearer {SECRET}"
    if req.url.path.endswith("/key"):
        return httpx.Response(200, json={"data": {"label": "k"}})
    if req.url.path.endswith("/models"):
        return httpx.Response(200, json={"data": [{"id": "anthropic/claude-sonnet-5", "name": "Claude Sonnet 5",
                                                   "architecture": {"output_modalities": ["text"]}}]})
    if req.url.path.endswith("/chat/completions"):
        body = json.loads(req.content)
        sys_prompt = body["messages"][0]["content"]
        # пробный запрос при сохранении модели или настоящий чат с транскриптом
        assert sys_prompt == "Reply with: OK" or "<transcript>" in sys_prompt
        chunks = [{"choices": [{"delta": {"content": "Это "}}]}, {"choices": [{"delta": {"content": "шутка"}}]}]
        return httpx.Response(200, content="".join(f"data: {json.dumps(c)}\n\n" for c in chunks).encode() + b"data: [DONE]\n\n")
    return httpx.Response(404)


def client(handler=openrouter_handler):
    c = TestClient(app)
    c.__enter__()
    db = FakeRest()
    registry = ProviderRegistry(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    app.state.ai = AiServices(registry, CredentialStore(db, KeyCipher({1: os.urandom(32)}, 1)),
                              AiSettingsService(db), ModelCatalog())
    app.state.jwt_verifier = FakeVerifier()
    c.headers["Authorization"] = "Bearer good-token"
    return c, db


def test_requires_login():
    c, _ = client()
    assert c.get("/providers", headers={"Authorization": ""}).status_code == 401
    assert c.get("/providers", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_full_flow_key_never_leaks():
    c, db = client()
    listing = c.get("/providers").json()
    assert [p["id"] for p in listing] == ["openrouter", "openai", "anthropic", "google", "groq"]
    assert all(p["credential"]["configured"] is False for p in listing)

    r = c.put("/providers/openrouter/credentials", json={"api_key": SECRET})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["models_count"] == 1
    assert body["credential"] | {"last_checked_at": None} == {
        "provider_id": "openrouter", "configured": True, "key_hint": "abcd", "status": "valid",
        "last_checked_at": None, "last_error": None, "base_url": None}

    # в «БД» — только шифротекст, ключа в открытом виде нет нигде
    stored = db.tables["provider_credentials"][0]
    assert SECRET not in json.dumps(stored) and stored["encrypted_key"].startswith("\\x")
    assert SECRET not in c.get("/providers").text

    models = c.get("/providers/openrouter/models").json()
    assert models[0]["id"] == "anthropic/claude-sonnet-5"

    r = c.put("/settings/ai/chat", json={"provider_id": "openrouter", "model_id": "anthropic/claude-sonnet-5",
                                         "params": {"temperature": 0.2, "evil": 1}})
    assert r.status_code == 200 and r.json()["warning"] is None
    assert c.get("/settings/ai").json() == [{"task": "chat", "provider_id": "openrouter",
                                            "model_id": "anthropic/claude-sonnet-5", "params": {"temperature": 0.2}}]

    with c.stream("POST", "/ai/stream", json={"task": "chat", "title": "T", "transcript": "hello world",
                                              "messages": [{"role": "user", "content": "что смешного?"}]}) as s:
        assert s.headers["content-type"].startswith("text/event-stream")
        text = "".join(s.iter_text())
    assert "event: start" in text and "event: done" in text
    deltas = [json.loads(line[6:])["text"] for line in text.splitlines() if line.startswith("data: {\"text\"")]
    assert "".join(deltas) == "Это шутка"

    assert c.delete("/providers/openrouter/credentials").status_code == 204
    assert c.get("/providers").json()[0]["credential"]["configured"] is False


def test_errors():
    c, _ = client(lambda r: httpx.Response(401, json={"error": {"code": 401, "message": "No auth credentials found"}}))
    # ключ не принят провайдером → сохранён, но invalid
    body = c.put("/providers/openrouter/credentials", json={"api_key": SECRET}).json()
    assert body["ok"] is False and body["error"]["code"] == "unauthorized"
    assert body["credential"]["status"] == "invalid" and "No auth" in body["credential"]["last_error"]
    # настройка задачи без ключа провайдера
    r = c.put("/settings/ai/chat", json={"provider_id": "groq", "model_id": "x"})
    assert r.status_code == 409 and r.json()["code"] == "not_configured"
    # стрим без выбранной модели
    r = c.post("/ai/stream", json={"task": "summary", "transcript": "t"})
    assert r.status_code == 409 and r.json()["code"] == "not_configured"
    assert c.get("/providers/nope/models").status_code == 404
    assert c.put("/settings/ai/transcribe", json={"provider_id": "openrouter", "model_id": "x"}).status_code == 422


def test_setting_rejected_when_model_unavailable():
    def h(req):
        if req.url.path.endswith("/key") or req.url.path.endswith("/models"):
            return openrouter_handler(req)
        return httpx.Response(404, json={"error": {"code": 404, "message": "This model is no longer available to new users"}})

    c, db = client(h)
    c.put("/providers/openrouter/credentials", json={"api_key": SECRET})
    r = c.put("/settings/ai/chat", json={"provider_id": "openrouter", "model_id": "old/model"})
    assert r.status_code == 404 and "no longer available" in r.json()["message"]
    assert c.get("/settings/ai").json() == []


def test_setting_saved_with_warning_on_rate_limit():
    def h(req):
        if req.url.path.endswith("/key") or req.url.path.endswith("/models"):
            return openrouter_handler(req)
        return httpx.Response(429, json={"error": {"code": 429, "message": "slow down"}})

    c, _ = client(h)
    c.put("/providers/openrouter/credentials", json={"api_key": SECRET})
    r = c.put("/settings/ai/summary", json={"provider_id": "openrouter", "model_id": "a/b"})
    assert r.status_code == 200 and "slow down" in r.json()["warning"]


def test_setting_saved_with_warning_when_provider_overloaded():
    def h(req):
        if req.url.path.endswith("/key") or req.url.path.endswith("/models"):
            return openrouter_handler(req)
        return httpx.Response(503, json={"error": {"code": 503, "message": "This model is currently experiencing high demand."}})

    c, _ = client(h)
    c.put("/providers/openrouter/credentials", json={"api_key": SECRET})
    r = c.put("/settings/ai/chat", json={"provider_id": "openrouter", "model_id": "a/b"})
    assert r.status_code == 200 and "high demand" in r.json()["warning"]
    assert c.get("/settings/ai").json()[0]["model_id"] == "a/b"
