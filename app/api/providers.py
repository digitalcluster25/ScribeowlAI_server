from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from app.ai.errors import ProviderError
from app.ai.models import CredentialStatus, ModelInfo, ProviderView
from app.api.deps import AiServices, ai
from app.security.auth import CurrentUser, current_user
from app.security.crypto import redact

router = APIRouter(prefix="/providers", tags=["ai-providers"])


class CredentialsIn(BaseModel):
    api_key: str = Field(min_length=8, max_length=500)


class TestResult(BaseModel):
    ok: bool
    models_count: int | None = None
    credential: CredentialStatus
    error: dict | None = None


@router.get("", response_model=list[ProviderView])
async def list_providers(user: CurrentUser = Depends(current_user), s: AiServices = Depends(ai)):
    creds, _ = s.require_storage()
    saved = await creds.list(user.id)
    return [ProviderView(**d.model_dump(), credential=saved.get(d.id) or CredentialStatus(provider_id=d.id, configured=False))
            for d in s.registry.descriptors()]


async def _test(user: CurrentUser, s: AiServices, provider_id: str) -> TestResult:
    creds, _ = s.require_storage()
    provider = await s.provider_for(user.id, provider_id)
    try:
        count = await provider.test_connection()
        await creds.set_status(user.id, provider_id, "valid")
        ok, err = True, None
    except ProviderError as e:
        e.message = redact(e.message, provider.api_key)
        count, ok, err = None, False, e.to_dict()
        # неверный ключ — invalid; сеть/лимит — статус не трогаем, но ошибку показываем
        if e.code in ("unauthorized", "quota_exceeded"):
            await creds.set_status(user.id, provider_id, "invalid", e.message)
    s.catalog.invalidate(user.id, provider_id)
    return TestResult(ok=ok, models_count=count, credential=(await creds.list(user.id))[provider_id], error=err)


@router.put("/{provider_id}/credentials", response_model=TestResult)
async def save_credentials(provider_id: str, body: CredentialsIn, user: CurrentUser = Depends(current_user),
                           s: AiServices = Depends(ai)):
    if not s.registry.has(provider_id):
        raise ProviderError("not_found", f"Неизвестный провайдер: {provider_id}", provider_id)
    creds, _ = s.require_storage()
    await creds.save(user.id, provider_id, body.api_key)
    return await _test(user, s, provider_id)  # сразу проверяем ключ


@router.delete("/{provider_id}/credentials", status_code=204)
async def delete_credentials(provider_id: str, user: CurrentUser = Depends(current_user), s: AiServices = Depends(ai)):
    creds, _ = s.require_storage()
    await creds.delete(user.id, provider_id)
    s.catalog.invalidate(user.id, provider_id)
    return Response(status_code=204)


@router.post("/{provider_id}/test", response_model=TestResult)
async def test_credentials(provider_id: str, user: CurrentUser = Depends(current_user), s: AiServices = Depends(ai)):
    return await _test(user, s, provider_id)


@router.get("/{provider_id}/models", response_model=list[ModelInfo])
async def list_models(provider_id: str, refresh: bool = False, user: CurrentUser = Depends(current_user),
                      s: AiServices = Depends(ai)):
    provider = await s.provider_for(user.id, provider_id)
    return await s.catalog.list(user.id, provider, refresh=refresh)
