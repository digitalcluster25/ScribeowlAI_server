from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from app.ai.errors import TRANSIENT_CODES, ProviderError
from app.ai.models import ChatMessage, ProviderId, Task, TaskSetting
from app.api.deps import AiServices, ai
from app.security.auth import CurrentUser, current_user

router = APIRouter(prefix="/settings/ai", tags=["ai-settings"])


class TaskSettingIn(BaseModel):
    provider_id: ProviderId
    model_id: str = Field(min_length=1, max_length=200)
    params: dict = {}


@router.get("", response_model=list[TaskSetting])
async def get_settings(user: CurrentUser = Depends(current_user), s: AiServices = Depends(ai)):
    _, settings = s.require_storage()
    return await settings.get_all(user.id)


class SavedSetting(TaskSetting):
    warning: str | None = None


async def probe_model(provider, model_id: str) -> None:
    """Короткий пробный запрос: модель из /models может быть недоступна аккаунту (напр. Gemini 2.5 для новых)."""
    async for _ in provider.chat_stream(model=model_id, system="Reply with: OK",
                                        messages=[ChatMessage(role="user", content="ping")],
                                        max_tokens=16, temperature=None):
        break


@router.put("/{task}", response_model=SavedSetting)
async def put_setting(task: Task, body: TaskSettingIn, user: CurrentUser = Depends(current_user),
                      s: AiServices = Depends(ai)):
    creds, settings = s.require_storage()
    if body.provider_id not in await creds.list(user.id):
        raise ProviderError("not_configured", "Сначала добавьте ключ этого провайдера", body.provider_id)
    provider = await s.provider_for(user.id, body.provider_id)
    warning = None
    try:
        await probe_model(provider, body.model_id)
    except ProviderError as e:
        if e.code not in TRANSIENT_CODES:
            raise  # модель недоступна / неверный id / ключ — не сохраняем
        warning = f"Сохранено, но проверить модель не удалось — временный сбой провайдера: {e.message}"
    params = {k: v for k, v in body.params.items() if k in ("temperature",)}
    saved = await settings.put(user.id, TaskSetting(task=task, provider_id=body.provider_id,
                                                    model_id=body.model_id, params=params))
    return SavedSetting(**saved.model_dump(), warning=warning)


@router.delete("/{task}", status_code=204)
async def delete_setting(task: Task, user: CurrentUser = Depends(current_user), s: AiServices = Depends(ai)):
    _, settings = s.require_storage()
    await settings.delete(user.id, task)
    return Response(status_code=204)
