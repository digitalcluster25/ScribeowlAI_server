from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from app.ai.errors import ProviderError
from app.ai.models import CredentialStatus
from app.security.auth import CurrentUser, current_user, optional_user
from app.security.crypto import redact
from app.transcripts.errors import TranscriptError
from app.transcripts.models import Transcript, TranscriptProviderInfo
from app.utils.youtube_id import extract_video_id

router = APIRouter(prefix="/transcripts", tags=["transcripts"])

STATUS = {
    "not_found": 404, "no_captions": 404, "rate_limited": 429, "quota_exceeded": 402,
    "unauthorized": 502,  # ключ провайдера — проблема настройки, не входа в наш API
    "network": 504, "parse": 502,
}


class TranscriptRequest(BaseModel):
    url: str | None = None
    video_id: str | None = None
    language: str | None = None
    provider_id: str | None = None

    @model_validator(mode="after")
    def need_source(self):
        if not (self.url or self.video_id):
            raise ValueError("Нужен url или video_id")
        return self


class KeyIn(BaseModel):
    api_key: str = Field(min_length=8, max_length=500)


class KeyTestResult(BaseModel):
    ok: bool
    credential: CredentialStatus | None
    error: dict | None = None


def error_response(e: TranscriptError) -> JSONResponse:
    return JSONResponse(e.to_dict(), status_code=STATUS.get(e.code, 502))


def _store(request: Request):
    store = request.app.state.ai.credentials
    if store is None:
        raise ProviderError("not_configured", "Хранилище ключей не настроено на сервере")
    return store


def _key_providers(request: Request) -> list[str]:
    reg = request.app.state.transcript_registry
    return [i for i in reg.ids() if reg.get(i).requires_api_key]


async def _user_keys(request: Request, user: CurrentUser | None) -> dict[str, str]:
    """Расшифрованные ключи транскрипт-провайдеров пользователя (только на время запроса)."""
    store = request.app.state.ai.credentials
    if not user or store is None:
        return {}
    keys = {}
    for pid in _key_providers(request):
        found = await store.get_key(user.id, pid)
        if found:
            keys[pid] = found[0]
    return keys


@router.get("/providers", response_model=list[TranscriptProviderInfo])
async def providers(request: Request, user: CurrentUser | None = Depends(optional_user)):
    reg = request.app.state.transcript_registry
    store = request.app.state.ai.credentials
    creds: dict[str, dict] = {}
    if user and store is not None:
        saved = await store.list(user.id)
        creds = {pid: saved[pid].model_dump(mode="json") for pid in _key_providers(request) if pid in saved}
    # для статуса «настроен» ключ расшифровывать не нужно — достаточно факта наличия
    return reg.list({pid: "set" for pid in creds}, creds)


@router.post("", response_model=Transcript)
async def get_transcript(body: TranscriptRequest, request: Request, user: CurrentUser | None = Depends(optional_user)):
    video_id = extract_video_id(body.video_id or body.url or "")
    if not video_id:
        return JSONResponse(
            {"code": "not_found", "message": "Не удалось распознать ссылку YouTube", "provider_id": None},
            status_code=422,
        )
    keys = await _user_keys(request, user)
    try:
        return await request.app.state.transcript_service.get(
            video_id, body.language or None, body.provider_id or None, keys)
    except TranscriptError as e:
        reg = request.app.state.transcript_registry
        e.message = redact(e.message, *keys.values(), *(reg.get(i).api_key for i in reg.ids()))
        return error_response(e)


def _require_key_provider(request: Request, provider_id: str):
    if provider_id not in _key_providers(request):
        raise ProviderError("not_found", f"Транскрипт-провайдер без ключа или неизвестный: {provider_id}", provider_id)
    return request.app.state.transcript_registry.get(provider_id)


async def _test(request: Request, user: CurrentUser, provider_id: str) -> KeyTestResult:
    provider = _require_key_provider(request, provider_id)
    store = _store(request)
    found = await store.get_key(user.id, provider_id)
    if not found:
        raise ProviderError("not_configured", "Ключ не добавлен", provider_id)
    try:
        await provider.test_key(found[0])
        await store.set_status(user.id, provider_id, "valid")
        ok, err = True, None
    except TranscriptError as e:
        e.message = redact(e.message, found[0])
        ok, err = False, e.to_dict()
        if e.code in ("unauthorized", "quota_exceeded"):
            await store.set_status(user.id, provider_id, "invalid", e.message)
    return KeyTestResult(ok=ok, credential=(await store.list(user.id)).get(provider_id), error=err)


@router.put("/providers/{provider_id}/credentials", response_model=KeyTestResult)
async def save_key(provider_id: str, body: KeyIn, request: Request, user: CurrentUser = Depends(current_user)):
    _require_key_provider(request, provider_id)
    await _store(request).save(user.id, provider_id, body.api_key)
    return await _test(request, user, provider_id)  # сразу проверяем бесплатным запросом


@router.post("/providers/{provider_id}/test", response_model=KeyTestResult)
async def test_key(provider_id: str, request: Request, user: CurrentUser = Depends(current_user)):
    return await _test(request, user, provider_id)


@router.delete("/providers/{provider_id}/credentials", status_code=204)
async def delete_key(provider_id: str, request: Request, user: CurrentUser = Depends(current_user)):
    _require_key_provider(request, provider_id)
    await _store(request).delete(user.id, provider_id)
    return Response(status_code=204)
