"""Общая нормализация сегментов: концы сегментов, деление абзацев на фразы."""

from __future__ import annotations

import re

from app.transcripts.models import TranscriptSegment

_SENTENCE = re.compile(r"(?<=[.!?…])\s+")
# Авто-субтитры часто без пунктуации — режем длинные куски по словам, чтобы подсветка была полезной
MAX_WORDS = 16


def fill_ends(segments: list[TranscriptSegment], duration: float | None) -> list[TranscriptSegment]:
    """Конец сегмента = начало следующего; у последнего — duration (если больше start)."""
    out = sorted(segments, key=lambda s: s.start)
    for cur, nxt in zip(out, out[1:]):
        cur.end = max(cur.start, nxt.start)
    if out:
        last = out[-1]
        if duration and duration > last.start:
            last.end = duration
        elif last.end <= last.start:
            last.end = last.start + max(1.0, 0.35 * len(last.text.split()))
    return out


def split_sentences(text: str, max_words: int = MAX_WORDS) -> list[str]:
    parts: list[str] = []
    for sentence in _SENTENCE.split(" ".join(text.split())):
        words = sentence.split()
        if not words:
            continue
        # равные куски не длиннее max_words
        n = -(-len(words) // max_words)
        size = -(-len(words) // n)
        parts.extend(" ".join(words[i : i + size]) for i in range(0, len(words), size))
    return parts


def split_paragraph(start: float, end: float, text: str) -> list[TranscriptSegment]:
    """Делит абзац на фразы, время распределяет пропорционально длине (approximate=True)."""
    parts = split_sentences(text)
    if not parts:
        return []
    total = sum(len(p) for p in parts)
    span = max(0.0, end - start)
    out, t = [], start
    for p in parts:
        dt = span * len(p) / total if total else 0.0
        out.append(TranscriptSegment(start=round(t, 3), end=round(t + dt, 3), text=p, approximate=True))
        t += dt
    return out


def parse_clock(value: str) -> float:
    """'m:ss' / 'h:mm:ss' → секунды."""
    total = 0.0
    for part in value.strip().split(":"):
        total = total * 60 + float(part)
    return total
