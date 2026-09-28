from __future__ import annotations

from typing import Literal

ErrorCode = Literal["rate_limited", "quota_exceeded", "unauthorized", "not_found", "no_captions", "network", "parse"]

# При этих ошибках сервис пробует следующего провайдера
FALLBACK_CODES: frozenset[str] = frozenset({"rate_limited", "quota_exceeded", "network", "unauthorized", "parse"})
# «нет субтитров» — идём дальше только к провайдерам, которые умеют распознавать речь сами
FALLBACK_TO_GENERATORS: frozenset[str] = frozenset({"no_captions"})


class TranscriptError(Exception):
    def __init__(self, code: ErrorCode, message: str, provider_id: str | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.provider_id = provider_id
        self.status = status  # HTTP-статус ответа провайдера, если был

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "provider_id": self.provider_id}
