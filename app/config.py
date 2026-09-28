from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:5174,http://localhost:5174"
    # Supabase: SUPABASE_URL = API_URL, ANON_KEY = publishable/anon, SERVICE_ROLE_KEY = secret/service_role (только сервер)
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    # Транскрипт-провайдеры (ключи только на сервере)
    transcriptapi_api_key: str = ""
    # запасные ключи сервера для транскрипт-провайдеров (у пользователя может быть свой в профиле)
    supadata_api_key: str = ""
    easytranscriber_api_key: str = ""
    chocodata_api_key: str = ""
    transcript_providers_order: str = "youtube_transcript_ai,transcriptapi,supadata,chocodata,easytranscriber"
    # Ключи AI-провайдеров пользователей: AES-256-GCM, мастер-ключ только в env сервера
    credentials_encryption_key: str = ""
    credentials_key_version: int = 1

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
