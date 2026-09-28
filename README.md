# ScribeowlAI — server

FastAPI-сервер плеера для изучения языков: транскрипты YouTube от внешних провайдеров,
AI-провайдеры (чат, саммари, перевод) с ключами пользователей, Supabase Auth.

## Запуск
```bash
brew install uv gitleaks
cp .env.example .env            # заполнить (см. комментарии в файле)
uv sync
uv run pytest -q
uv run uvicorn app.main:app --reload --port 8000
```
Документация API: http://127.0.0.1:8000/docs

## Stage на VPS

PR в `stage` запускает тесты и сборку Docker-образа. После слияния в `stage`
GitHub Actions доставляет образ и миграции на VPS, где они применяются перед запуском API на
`https://scribe-api.spaces.community` (`/health`). Фронтенд находится отдельно
на `https://scribe.spaces.community`.

Настройки окружения хранятся в **GitHub Secrets** (переменные те же, что в локальном `.env`, с префиксом `STAGE_`).
При каждом деплое workflow собирает из них `/opt/scribeowl-api/server.env` и `db.env` на VPS (права `0600`);
руками на сервере ничего не храним. Новому разработчику ключи stage не нужны — локально у него свой `.env`.

| Переменная сервера | GitHub Secret | Обязательна |
|---|---|---|
| `APP_ENV` | `STAGE_APP_ENV` | да (`stage`) |
| `CORS_ORIGINS` | `STAGE_CORS_ORIGINS` | да |
| `SUPABASE_URL` | `STAGE_SUPABASE_URL` | да |
| `SUPABASE_JWKS_URL` | `STAGE_SUPABASE_JWKS_URL` | да (внутренний `http://api-gw:8000/...`) |
| `SUPABASE_ANON_KEY` | `STAGE_SUPABASE_ANON_KEY` | да (publishable key) |
| `SUPABASE_SERVICE_ROLE_KEY` | `STAGE_SUPABASE_SERVICE_ROLE_KEY` | да |
| `CREDENTIALS_ENCRYPTION_KEY` | `STAGE_CREDENTIALS_ENCRYPTION_KEY` | да — не менять, иначе ключи пользователей не расшифруются |
| `STAGE_SUPABASE_DB_URL` (db.env, миграции) | `STAGE_SUPABASE_DB_URL` | да |
| `TRANSCRIPTAPI_API_KEY`, `SUPADATA_API_KEY`, `CHOCODATA_API_KEY`, `EASYTRANSCRIBER_API_KEY` | `STAGE_…` | нет |

Также нужны `STAGE_DEPLOY_SSH_KEY` и `STAGE_DEPLOY_KNOWN_HOSTS` (доступ к VPS). Если обязательный секрет не задан,
деплой останавливается с их списком. Self-hosted Supabase работает в Docker-сети `supabase_default`; база доступна только с VPS.

Защита от коммита секретов (один раз на машине): `git config core.hooksPath .githooks`

## Устройство
- `app/transcripts/` — провайдеры транскриптов (youtube-transcript.ai, TranscriptAPI, Supadata, ChocoData,
  EasyTranscriber), реестр, фолбэк, in-memory кэш 24 ч. Формат ответа: сегменты `{start, end, text, approximate}`.
- `app/ai/` — AI-провайдеры (OpenRouter, OpenAI, Anthropic, Gemini, Groq), каталог моделей, промпты, перевод пачками.
- `app/security/` — проверка JWT Supabase (JWKS), AES-256-GCM для ключей провайдеров (AAD = user:provider),
  вырезание ключей из сообщений провайдеров.
- `app/db/` — Supabase PostgREST с secret key (таблицы закрыты RLS для клиентов).
- `app/api/` — HTTP API: `/transcripts`, `/providers`, `/settings/ai`, `/ai/stream` (SSE), `/ai/translate`.

- `supabase/` — схема БД и миграции (Supabase CLI), локальный стек на портах 553xx.

## База данных (Supabase)
```bash
brew install supabase/tap/supabase   # нужен Docker Desktop
supabase start                        # из этой папки; API http://127.0.0.1:55321, Studio :55323
supabase status -o env                # URL и ключи для .env
supabase migration new <name>         # новая миграция; старые не редактировать
supabase migration up --local         # применить новые миграции без потери данных
supabase db diff --local              # сверить миграции со схемой (теневая БД)
```
Таблицы закрыты для клиентов (RLS без политик, гранты anon/authenticated отозваны) —
работает только сервер с secret key.
