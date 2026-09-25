from __future__ import annotations

from fastapi import Request

from app.ai.catalog import ModelCatalog
from app.ai.credentials import CredentialStore
from app.ai.errors import ProviderError
from app.ai.registry import ProviderRegistry
from app.ai.settings_service import AiSettingsService


class AiServices:
    def __init__(self, registry: ProviderRegistry, credentials: CredentialStore | None,
                 settings: AiSettingsService | None, catalog: ModelCatalog):
        self.registry = registry
        self.credentials = credentials
        self.settings = settings
        self.catalog = catalog

    def require_storage(self) -> tuple[CredentialStore, AiSettingsService]:
        if not self.credentials or not self.settings:
            raise ProviderError("not_configured",
                                "Хранилище ключей не настроено на сервере (SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY/CREDENTIALS_ENCRYPTION_KEY)")
        return self.credentials, self.settings

    async def provider_for(self, user_id: str, provider_id: str):
        if not self.registry.has(provider_id):
            raise ProviderError("not_found", f"Неизвестный провайдер: {provider_id}", provider_id)
        creds, _ = self.require_storage()
        found = await creds.get_key(user_id, provider_id)
        if not found:
            raise ProviderError("not_configured", "Ключ провайдера не добавлен в профиле", provider_id)
        key, base_url = found
        return self.registry.create(provider_id, key, base_url)


def ai(request: Request) -> AiServices:
    return request.app.state.ai
