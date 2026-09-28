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
GitHub Actions применяет миграции Supabase и разворачивает API на
`https://scribe-api.spaces.community` (`/health`). Фронтенд находится отдельно
на `https://scribe.spaces.community`.

Перед первым деплоем нужны:

- GitHub Secrets `STAGE_DEPLOY_SSH_KEY`, `STAGE_DEPLOY_KNOWN_HOSTS` и
  `STAGE_SUPABASE_DB_URL` (строка подключения к базе Supabase с паролем).
- На VPS файл `/opt/scribeowl-api/server.env` с правами `0600`: `APP_ENV=stage`,
  `CORS_ORIGINS=https://scribe.spaces.community`, `SUPABASE_URL`,
  `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` и
  `CREDENTIALS_ENCRYPTION_KEY`. Значения ключей не коммитить.
- При публикации обновлённого клиента собрать его с
  `VITE_API_URL=https://scribe-api.spaces.community` и публичными значениями
  Supabase того же проекта.

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
