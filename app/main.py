import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ai.catalog import ModelCatalog
from app.ai.credentials import CredentialStore
from app.ai.errors import HTTP_STATUS, ProviderError
from app.ai.registry import ProviderRegistry
from app.ai.settings_service import AiSettingsService
from app.api import ai as ai_api
from app.api import ai_settings, providers, transcripts
from app.api.deps import AiServices
from app.config import get_settings
from app.db.rest import DbError, SupabaseRest
from app.security.auth import SupabaseJWTVerifier
from app.security.crypto import CryptoConfigError, KeyCipher
from app.transcripts.registry import TranscriptProviderRegistry
from app.transcripts.service import TranscriptService

settings = get_settings()
log = logging.getLogger("scribeowl")


def build_ai(db: SupabaseRest | None) -> AiServices:
    cipher = None
    try:
        cipher = KeyCipher.from_settings(settings.credentials_encryption_key, settings.credentials_key_version)
    except CryptoConfigError as e:
        log.warning("AI-ключи отключены: %s", e)
    creds = CredentialStore(db, cipher) if db and cipher else None
    return AiServices(ProviderRegistry(), creds, AiSettingsService(db) if db else None, ModelCatalog())


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry = TranscriptProviderRegistry(settings)
    app.state.transcript_registry = registry
    app.state.transcript_service = TranscriptService(registry)
    db = SupabaseRest(settings.supabase_url, settings.supabase_service_role_key) \
        if settings.supabase_url and settings.supabase_service_role_key else None
    app.state.ai = build_ai(db)
    app.state.jwt_verifier = SupabaseJWTVerifier(settings.supabase_url or "http://127.0.0.1:55321")
    yield
    await registry.aclose()
    await app.state.ai.registry.aclose()
    if db:
        await db.aclose()


app = FastAPI(title="ScribeowlAI API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ProviderError)
async def provider_error(_: Request, e: ProviderError):
    return JSONResponse(e.to_dict(), status_code=HTTP_STATUS.get(e.code, 502))


@app.exception_handler(DbError)
async def db_error(_: Request, e: DbError):
    log.error("DB error: %s", e)
    return JSONResponse({"code": "storage", "message": "База данных недоступна", "provider_id": None}, status_code=503)


@app.get("/health")
def health():
    return {"status": "ok", "env": settings.app_env}


app.include_router(transcripts.router)
app.include_router(providers.router)
app.include_router(ai_settings.router)
app.include_router(ai_api.router)
