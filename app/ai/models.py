from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ProviderId = Literal["openai", "openrouter", "anthropic", "google", "groq"]
Task = Literal["translate", "chat", "summary"]
TASKS: tuple[Task, ...] = ("translate", "chat", "summary")


class ProviderDescriptor(BaseModel):
    id: ProviderId
    name: str
    capabilities: list[Task]
    docs_url: str
    keys_url: str
    default_models: list[str] = []


class ModelInfo(BaseModel):
    id: str
    provider_id: ProviderId
    display_name: str
    context_window: int | None = None
    status: Literal["stable", "preview", "deprecated"] = "stable"
    recommended: bool = False
    note: str | None = None


class CredentialStatus(BaseModel):
    provider_id: str  # AI-провайдер или транскрипт-провайдер (transcriptapi)
    configured: bool
    key_hint: str | None = None
    status: Literal["unverified", "valid", "invalid"] | None = None
    last_checked_at: datetime | None = None
    last_error: str | None = None
    base_url: str | None = None


class ProviderView(ProviderDescriptor):
    credential: CredentialStatus


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class TaskSetting(BaseModel):
    task: Task
    provider_id: ProviderId
    model_id: str = Field(min_length=1, max_length=200)
    params: dict = {}
