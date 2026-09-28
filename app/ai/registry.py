from __future__ import annotations

import httpx

from app.ai.base import DEFAULT_TIMEOUT, BaseProvider
from app.ai.models import ProviderDescriptor
from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.openai_compat import GroqProvider, OpenAIProvider, OpenRouterProvider

PROVIDER_CLASSES: tuple[type[BaseProvider], ...] = (
    OpenRouterProvider, OpenAIProvider, AnthropicProvider, GeminiProvider, GroqProvider,
)


class ProviderRegistry:
    """Фабрика AI-провайдеров: provider_id → экземпляр с ключом пользователя."""

    def __init__(self, client: httpx.AsyncClient | None = None, classes=PROVIDER_CLASSES):
        self.client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        self._classes = {c.descriptor.id: c for c in classes}

    def descriptors(self) -> list[ProviderDescriptor]:
        return [c.descriptor for c in self._classes.values()]

    def has(self, provider_id: str) -> bool:
        return provider_id in self._classes

    def create(self, provider_id: str, api_key: str, base_url: str | None = None) -> BaseProvider:
        return self._classes[provider_id](api_key, self.client, base_url)

    async def aclose(self) -> None:
        await self.client.aclose()
