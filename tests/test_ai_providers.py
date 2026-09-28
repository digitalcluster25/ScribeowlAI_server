import json

import httpx
import pytest

from app.ai.errors import ProviderError
from app.ai.models import ChatMessage
from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.openai_compat import GroqProvider, OpenAIProvider, OpenRouterProvider

MSGS = [ChatMessage(role="user", content="hi")]


def sse(*chunks: str, events: list[str] | None = None) -> bytes:
    out = []
    for i, c in enumerate(chunks):
        ev = f"event: {events[i]}\n" if events else ""
        out.append(f"{ev}data: {c}\n\n")
    return "".join(out).encode()


def make(cls, handler):
    return cls("key-1234567890", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def collect(p, **kw):
    return [t async for t in p.chat_stream(model=kw.get("model", "m"), system="sys", messages=kw.get("messages", MSGS),
                                            max_tokens=100, temperature=None)]


# ---------- OpenAI-compatible ----------
async def test_openai_models_filter_and_auth():
    seen = {}

    def h(req):
        seen["auth"] = req.headers["authorization"]
        return httpx.Response(200, json={"object": "list", "data": [
            {"id": "gpt-6-sol"}, {"id": "text-embedding-3-large"}, {"id": "whisper-1"}, {"id": "o5-mini"},
            {"id": "gpt-6-realtime"}, {"id": "dall-e-3"}, {"id": "gpt-image-2"}]})

    ids = [m.id for m in await make(OpenAIProvider, h).list_models()]
    assert ids == ["gpt-6-sol", "o5-mini"] and seen["auth"] == "Bearer key-1234567890"


async def test_openai_stream_body_and_deltas():
    seen = {}

    def h(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=sse(
            json.dumps({"choices": [{"delta": {"role": "assistant"}}]}),
            json.dumps({"choices": [{"delta": {"content": "Hel"}}]}),
            json.dumps({"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}]}),
            json.dumps({"choices": [], "usage": {"total_tokens": 3}}),
            "[DONE]"))

    assert await collect(make(OpenAIProvider, h)) == ["Hel", "lo"]
    b = seen["body"]
    assert b["stream"] is True and b["max_completion_tokens"] == 100 and "max_tokens" not in b
    assert b["messages"][0] == {"role": "system", "content": "sys"} and "temperature" not in b


async def test_openrouter_uses_max_tokens_headers_and_midstream_error():
    seen = {}

    def h(req):
        seen["h"] = req.headers
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=b": OPENROUTER PROCESSING\n\n" + sse(
            json.dumps({"choices": [{"delta": {"content": "A"}}]}),
            json.dumps({"error": {"code": 502, "message": "upstream died"}, "choices": [{"finish_reason": "error"}]})))

    p = make(OpenRouterProvider, h)
    out = []
    with pytest.raises(ProviderError) as e:
        async for t in p.chat_stream(model="x/y", system="s", messages=MSGS, max_tokens=50, temperature=0.3):
            out.append(t)
    assert out == ["A"] and e.value.code == "overloaded" and "upstream died" in e.value.message
    assert seen["body"]["max_tokens"] == 50 and seen["body"]["temperature"] == 0.3
    assert seen["h"]["x-openrouter-title"] == "Scribeowl"


async def test_openrouter_models_text_only():
    def h(req):
        return httpx.Response(200, json={"data": [
            {"id": "a/text", "name": "Text", "context_length": 1000, "architecture": {"output_modalities": ["text"]}},
            {"id": "a/img", "name": "Img", "architecture": {"output_modalities": ["image"]}}]})

    ms = await make(OpenRouterProvider, h).list_models()
    assert [(m.id, m.display_name, m.context_window) for m in ms] == [("a/text", "Text", 1000)]


async def test_groq_filters_inactive_and_audio():
    def h(req):
        return httpx.Response(200, json={"data": [
            {"id": "llama-3.3-70b-versatile", "context_window": 131072, "active": True},
            {"id": "whisper-large-v3", "active": True}, {"id": "old", "active": False},
            {"id": "meta-llama/llama-guard-4", "active": True}]})

    assert [m.id for m in await make(GroqProvider, h).list_models()] == ["llama-3.3-70b-versatile"]


@pytest.mark.parametrize("status,code", [(401, "unauthorized"), (402, "quota_exceeded"), (429, "rate_limited"),
                                         (404, "not_found"), (400, "bad_request"), (503, "overloaded"),
                                         (529, "overloaded"), (418, "provider_error")])
async def test_http_error_mapping(status, code):
    p = make(OpenAIProvider, lambda r: httpx.Response(status, json={"error": {"message": "nope"}}))
    with pytest.raises(ProviderError) as e:
        await p.list_models()
    assert e.value.code == code and "nope" in e.value.message
    with pytest.raises(ProviderError) as e2:
        await collect(p)
    assert e2.value.code == code


async def test_network_error():
    def h(req):
        raise httpx.ConnectError("down", request=req)

    with pytest.raises(ProviderError) as e:
        await make(GroqProvider, h).list_models()
    assert e.value.code == "network"


# ---------- Anthropic ----------
async def test_anthropic_models_pagination_and_headers():
    calls = []

    def h(req):
        calls.append(dict(req.url.params))
        assert req.headers["x-api-key"] == "key-1234567890" and req.headers["anthropic-version"] == "2023-06-01"
        if "after_id" not in req.url.params:
            return httpx.Response(200, json={"data": [{"id": "claude-sonnet-5", "display_name": "Claude Sonnet 5",
                                                       "max_input_tokens": 1000000}], "has_more": True, "last_id": "claude-sonnet-5"})
        return httpx.Response(200, json={"data": [{"id": "claude-haiku-4-5", "display_name": "Claude Haiku 4.5"}],
                                         "has_more": False, "last_id": "claude-haiku-4-5"})

    ms = await make(AnthropicProvider, h).list_models()
    assert [m.id for m in ms] == ["claude-sonnet-5", "claude-haiku-4-5"] and ms[0].context_window == 1000000
    assert calls[1]["after_id"] == "claude-sonnet-5"


async def test_anthropic_stream():
    seen = {}

    def h(req):
        seen["body"] = json.loads(req.content)
        ev = ["message_start", "ping", "content_block_start", "content_block_delta", "content_block_delta",
              "content_block_delta", "content_block_stop", "message_delta", "message_stop"]
        data = [{"type": "message_start"}, {"type": "ping"}, {"type": "content_block_start"},
                {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "hmm"}},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "При"}},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "вет"}},
                {"type": "content_block_stop"}, {"type": "message_delta"}, {"type": "message_stop"}]
        return httpx.Response(200, content=sse(*[json.dumps(d) for d in data], events=ev))

    assert await collect(make(AnthropicProvider, h)) == ["При", "вет"]
    b = seen["body"]
    assert b["system"] == "sys" and b["max_tokens"] == 100 and b["messages"] == [{"role": "user", "content": "hi"}]


async def test_anthropic_midstream_error_and_last_user_rule():
    def h(req):
        return httpx.Response(200, content=sse(
            json.dumps({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}), events=["error"]))

    with pytest.raises(ProviderError) as e:
        await collect(make(AnthropicProvider, h))
    assert "Overloaded" in e.value.message
    with pytest.raises(ProviderError) as e2:
        await collect(make(AnthropicProvider, h), messages=[ChatMessage(role="assistant", content="x")])
    assert e2.value.code == "bad_request"


# ---------- Gemini ----------
async def test_gemini_models_filter_and_pages():
    def h(req):
        assert req.headers["x-goog-api-key"] == "key-1234567890"
        if "pageToken" not in req.url.params:
            return httpx.Response(200, json={"models": [
                {"name": "models/gemini-3.8-flash", "displayName": "Gemini 3.8 Flash", "inputTokenLimit": 1048576,
                 "supportedGenerationMethods": ["generateContent", "countTokens"]},
                {"name": "models/text-embedding-005", "supportedGenerationMethods": ["embedContent"]}],
                "nextPageToken": "p2"})
        return httpx.Response(200, json={"models": [
            {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]}]})

    ms = await make(GeminiProvider, h).list_models()
    assert [m.id for m in ms] == ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
    assert all(m.recommended for m in ms)


def test_gemini_catalog_per_docs():
    from app.ai.providers.gemini_catalog import classify
    hidden = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-1.5-pro",
              "gemini-3.1-flash-image", "gemini-3.1-flash-lite-image", "gemini-3-pro-image", "gemini-3.8-flash-tts",
              "gemini-3.8-live", "gemini-3.5-transcribe", "gemini-3.5-live-translate-preview", "gemini-embedding-001",
              "gemini-robotics-er-2-preview", "gemini-2.5-computer-use-preview-10-2025", "deep-research-preview-04-2026",
              "gemini-3.1-flash-lite-preview", "gemini-3-pro-preview", "gemini-omni-1.1-flash"]
    assert [m for m in hidden if classify(m) is not None] == []
    assert classify("gemini-3.8-flash")["recommended"] is True
    assert classify("gemini-3.7-flash")["status"] == "stable"
    assert classify("gemini-3.1-pro-preview")["status"] == "preview"
    assert classify("gemini-3.1-flash-lite")["status"] == "deprecated"


async def test_gemini_stream_body_url_and_thought_skip():
    seen = {}

    def h(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=sse(
            json.dumps({"candidates": [{"content": {"role": "model", "parts": [{"text": "думаю", "thought": True}]}}]}),
            json.dumps({"candidates": [{"content": {"role": "model", "parts": [{"text": "Ответ"}]}}]}),
            json.dumps({"candidates": [{"content": {"parts": [{"text": "!"}]}, "finishReason": "STOP"}]})))

    msgs = [ChatMessage(role="user", content="q1"), ChatMessage(role="assistant", content="a1"),
            ChatMessage(role="user", content="q2")]
    out = await collect(make(GeminiProvider, h), model="gemini-3.8-flash", messages=msgs)
    assert out == ["Ответ", "!"]
    assert seen["url"].endswith("/models/gemini-3.8-flash:streamGenerateContent?alt=sse")
    b = seen["body"]
    assert b["systemInstruction"] == {"parts": [{"text": "sys"}]}
    assert [c["role"] for c in b["contents"]] == ["user", "model", "user"]
    assert b["generationConfig"] == {"maxOutputTokens": 100}


async def test_gemini_invalid_key_400_and_block():
    p = make(GeminiProvider, lambda r: httpx.Response(400, json={"error": {"code": 400, "message": "API key not valid",
                                                                            "status": "INVALID_ARGUMENT",
                                                                            "details": [{"reason": "API_KEY_INVALID"}]}}))
    with pytest.raises(ProviderError) as e:
        await p.list_models()
    assert e.value.code == "unauthorized"
    blocked = make(GeminiProvider, lambda r: httpx.Response(200, content=sse(json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}))))
    with pytest.raises(ProviderError) as e2:
        await collect(blocked)
    assert "SAFETY" in e2.value.message
