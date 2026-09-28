"""Извлечение 11-символьного video_id из любых форм ссылки YouTube (без сети)."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_HOSTS = ("youtube.com", "youtube-nocookie.com", "youtu.be")


def extract_video_id(value: str) -> str | None:
    value = (value or "").strip()
    if _ID.match(value):
        return value
    if "://" not in value:
        value = "https://" + value
    try:
        u = urlparse(value)
    except ValueError:
        return None
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.").removeprefix("music.")
    if not any(host == h or host.endswith("." + h) for h in _HOSTS):
        return None
    parts = [p for p in u.path.split("/") if p]
    candidate = None
    if host.endswith("youtu.be"):
        candidate = parts[0] if parts else None
    elif parts and parts[0] in ("shorts", "embed", "live", "v", "e"):
        candidate = parts[1] if len(parts) > 1 else None
    else:
        candidate = (parse_qs(u.query).get("v") or [None])[0]
    return candidate if candidate and _ID.match(candidate) else None
