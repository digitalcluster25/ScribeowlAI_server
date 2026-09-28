from __future__ import annotations

from typing import Literal

AiErrorCode = Literal[
    "not_configured", "unauthorized", "rate_limited", "quota_exceeded",
    "not_found", "bad_request", "network", "overloaded", "provider_error",
]

# временные сбои: повтор позже может помочь (не значит, что модель/ключ плохие)
TRANSIENT_CODES = frozenset({"rate_limited", "network", "overloaded"})

HTTP_STATUS: dict[str, int] = {
    "not_configured": 409, "unauthorized": 422, "rate_limited": 429, "quota_exceeded": 402,
    "not_found": 404, "bad_request": 400, "network": 504, "overloaded": 503, "provider_error": 502,
}


class ProviderError(Exception):
    """Единая ошибка AI-провайдера. unauthorized = ключ провайдера неверный (не наш вход)."""

    def __init__(self, code: AiErrorCode, message: str, provider_id: str | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.provider_id = provider_id
        self.status = status

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "provider_id": self.provider_id}


def code_for_status(status: int) -> AiErrorCode:
    if status in (401, 403):
        return "unauthorized"
    if status == 402:
        return "quota_exceeded"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if status in (400, 413, 422):
        return "bad_request"
    if status == 408:
        return "network"
    if status in (500, 502, 503, 504, 529):
        return "overloaded"  # у Google 503 UNAVAILABLE «high demand», у Anthropic 529 overloaded
    return "provider_error"
