"""Какие модели Gemini API реально годятся для текста у НОВОГО пользователя.

Источник (сверено 2026-09-25):
  https://ai.google.dev/gemini-api/docs/models
  https://ai.google.dev/gemini-api/docs/deprecations
- Вся серия 2.5 ограничена: «limiting access to the 2.5 models to users who have actively used them in the past».
  В /models она при этом отдаётся → скрываем.
- «For any new projects, use our latest models: 3.5 Flash-Lite or 3.8 Flash» → recommended.
- 2.0 / 1.x, gemini-3.1-flash-lite-preview, gemini-3-pro-preview — выключены.
- gemini-3.1-flash-lite — deprecated (отключение 2027-05-07, замена gemini-3.5-flash-lite).
- Картинки/видео/музыка/TTS/live-аудио/транскрипция/эмбеддинги/роботы/агенты — не текстовый чат.
"""

from __future__ import annotations

import re

RECOMMENDED = {"gemini-3.8-flash", "gemini-3.5-flash-lite"}

DEPRECATED = {
    "gemini-3.1-flash-lite": "Устаревает: отключение 2027-05-07, замена — gemini-3.5-flash-lite",
}

# ограничены для новых пользователей или выключены
_UNAVAILABLE = re.compile(
    r"^(gemini-(1\.|2\.0|2\.5)|gemini-3\.1-flash-lite-preview$|gemini-3-pro-preview$|"
    r"gemini-pro|gemini-exp|learnlm|aqa$)"
)
# не текстовый чат
_NOT_TEXT = re.compile(
    r"image|tts|live|audio|transcribe|translate|embedding|robotics|computer-use|deep-research|"
    r"antigravity|omni|veo|lyria|imagen|nano-banana"
)


def classify(model_id: str) -> dict | None:
    """None — скрыть; иначе поля для ModelInfo (status/recommended/note)."""
    if _UNAVAILABLE.search(model_id) or _NOT_TEXT.search(model_id):
        return None
    if model_id in DEPRECATED:
        return {"status": "deprecated", "note": DEPRECATED[model_id]}
    if "preview" in model_id or model_id.endswith("-exp") or "-exp-" in model_id:
        return {"status": "preview", "note": "Preview: может измениться или быть отключена"}
    return {"status": "stable", "recommended": model_id in RECOMMENDED,
            "note": "Рекомендована Google для новых проектов" if model_id in RECOMMENDED else None}
