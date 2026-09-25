"""Какой провайдер/модель назначены на задачу (ai_task_settings)."""

from __future__ import annotations

from app.ai.models import TASKS, TaskSetting
from app.db.rest import SupabaseRest

TABLE = "ai_task_settings"


class AiSettingsService:
    def __init__(self, db: SupabaseRest):
        self.db = db

    async def get_all(self, user_id: str) -> list[TaskSetting]:
        rows = await self.db.select(TABLE, user_id=user_id)
        return [TaskSetting(task=r["task"], provider_id=r["provider_id"], model_id=r["model_id"], params=r["params"] or {})
                for r in rows if r["task"] in TASKS]

    async def get(self, user_id: str, task: str) -> TaskSetting | None:
        rows = await self.db.select(TABLE, user_id=user_id, task=task)
        if not rows:
            return None
        r = rows[0]
        return TaskSetting(task=r["task"], provider_id=r["provider_id"], model_id=r["model_id"], params=r["params"] or {})

    async def put(self, user_id: str, setting: TaskSetting) -> TaskSetting:
        await self.db.upsert(TABLE, {"user_id": user_id, **setting.model_dump()}, on_conflict="user_id,task")
        return setting

    async def delete(self, user_id: str, task: str) -> None:
        await self.db.delete(TABLE, user_id=user_id, task=task)
