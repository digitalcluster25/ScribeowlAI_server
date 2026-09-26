import json

import httpx

from app.ai.translate import build_translate_input, parse_translation

from .test_ai_api import SECRET, client, openrouter_handler


def test_parse_translation_robust():
    text = "Вот перевод:\n0|привет\n1 | мир\n2:шутка\n7|лишняя\n1|дубль\n\n3|"
    assert parse_translation(text, {0, 1, 2, 3}) == {0: "привет", 1: "мир", 2: "шутка"}


def test_input_format_collapses_whitespace():
    msgs = build_translate_input([(5, "hello\n   world"), (6, "ok")])
    assert msgs[0].content == "5|hello world\n6|ok"


def test_translate_endpoint():
    seen = {}

    def h(req):
        if req.url.path.endswith("/chat/completions"):
            body = json.loads(req.content)
            if body["messages"][0]["content"] == "Reply with: OK":
                return openrouter_handler(req)
            seen["system"] = body["messages"][0]["content"]
            seen["user"] = body["messages"][1]["content"]
            chunks = ["10|привет\n", "11|как дела"]
            out = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n\n" for c in chunks)
            return httpx.Response(200, content=(out + "data: [DONE]\n\n").encode())
        return openrouter_handler(req)

    c, _ = client(h)
    c.put("/providers/openrouter/credentials", json={"api_key": SECRET})
    r = c.post("/ai/translate", json={"target_language": "Русский", "segments": [{"i": 10, "text": "hi"}]})
    assert r.status_code == 409 and r.json()["code"] == "not_configured"
    assert c.put("/settings/ai/translate", json={"provider_id": "openrouter", "model_id": "a/b"}).status_code == 200
    r = c.post("/ai/translate", json={"target_language": "Русский", "title": "T",
                                      "segments": [{"i": 10, "text": "hi"}, {"i": 11, "text": "how are you"},
                                                   {"i": 12, "text": "bye"}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == [{"i": 10, "text": "привет"}, {"i": 11, "text": "как дела"}]
    assert body["missing"] == [12]
    assert "Русский" in seen["system"] and seen["user"] == "10|hi\n11|how are you\n12|bye"
    assert c.post("/ai/translate", json={"target_language": "ru", "segments": []}).status_code == 422
