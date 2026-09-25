-- ScribeowlAI: начальная схема.
-- Правило доступа: клиенты (anon/authenticated) к таблицам НЕ ходят.
-- Всё идёт через наш API (FastAPI) с secret key, который обходит RLS.
-- RLS включён везде, политик нет => для клиентов доступ закрыт.

-- ---------- общее ----------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------- ключи AI-провайдеров ----------
-- Ключ шифруется в приложении AES-256-GCM (мастер-ключ в env сервера).
create table public.provider_credentials (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references auth.users (id) on delete cascade,
  provider_id      text not null check (provider_id in ('openai','openrouter','google','anthropic','groq','deepgram')),
  encrypted_key    bytea not null,          -- шифротекст
  iv               bytea not null,          -- 12 байт, уникален на запись
  auth_tag         bytea not null,          -- 16 байт GCM tag
  key_version      smallint not null default 1, -- версия мастер-ключа (для ротации)
  key_hint         text not null,           -- последние 4 символа, для UI
  base_url         text,
  extra            jsonb not null default '{}'::jsonb,
  status           text not null default 'unverified' check (status in ('unverified','valid','invalid')),
  last_checked_at  timestamptz,
  last_error       text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (user_id, provider_id)
);

-- ---------- выбор провайдера/модели по задачам ----------
create table public.ai_task_settings (
  user_id      uuid not null references auth.users (id) on delete cascade,
  task         text not null check (task in ('transcribe','translate','chat','summary')),
  provider_id  text not null check (provider_id in ('openai','openrouter','google','anthropic','groq','deepgram')),
  model_id     text not null,
  params       jsonb not null default '{}'::jsonb, -- temperature и т.п.
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  primary key (user_id, task)
);

-- ---------- видео (общий кэш, не привязан к пользователю) ----------
create table public.videos (
  id             uuid primary key default gen_random_uuid(),
  youtube_id     text not null unique,
  title          text,
  channel        text,
  duration_sec   integer,
  language       text,            -- язык видео по данным YouTube
  thumbnail_url  text,
  metadata       jsonb not null default '{}'::jsonb,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- ---------- транскрипты (общий кэш) ----------
-- segments: [{start, end, text, speaker?, words?: [{start, text}]}]
create table public.transcripts (
  id           uuid primary key default gen_random_uuid(),
  video_id     uuid not null references public.videos (id) on delete cascade,
  language     text not null,
  source       text not null check (source in ('youtube_manual','youtube_auto','stt')),
  provider_id  text,              -- для stt
  model_id     text,              -- для stt
  status       text not null default 'pending' check (status in ('pending','processing','ready','failed')),
  error        text,
  segments     jsonb not null default '[]'::jsonb,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  unique (video_id, language, source)
);

-- ---------- переводы (общий кэш) ----------
-- segments: [{i, text}] — i = индекс сегмента исходного транскрипта
create table public.translations (
  id               uuid primary key default gen_random_uuid(),
  transcript_id    uuid not null references public.transcripts (id) on delete cascade,
  target_language  text not null,
  provider_id      text not null,
  model_id         text not null,
  status           text not null default 'pending' check (status in ('pending','processing','ready','failed')),
  error            text,
  segments         jsonb not null default '[]'::jsonb,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (transcript_id, target_language, provider_id, model_id)
);

-- ---------- плейлист пользователя ----------
create table public.user_videos (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references auth.users (id) on delete cascade,
  video_id           uuid not null references public.videos (id) on delete cascade,
  position           integer not null default 0,
  last_position_sec  numeric(10,2) not null default 0,  -- где остановился
  added_at           timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (user_id, video_id)
);
create index user_videos_user_position_idx on public.user_videos (user_id, position);

-- ---------- чат по видео ----------
create table public.chat_messages (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users (id) on delete cascade,
  video_id     uuid not null references public.videos (id) on delete cascade,
  role         text not null check (role in ('user','assistant','system')),
  content      text not null,
  provider_id  text,
  model_id     text,
  created_at   timestamptz not null default now()
);
create index chat_messages_user_video_idx on public.chat_messages (user_id, video_id, created_at);

-- ---------- триггеры updated_at ----------
create trigger provider_credentials_updated_at before update on public.provider_credentials for each row execute function public.set_updated_at();
create trigger ai_task_settings_updated_at     before update on public.ai_task_settings     for each row execute function public.set_updated_at();
create trigger videos_updated_at               before update on public.videos               for each row execute function public.set_updated_at();
create trigger transcripts_updated_at          before update on public.transcripts          for each row execute function public.set_updated_at();
create trigger translations_updated_at         before update on public.translations         for each row execute function public.set_updated_at();
create trigger user_videos_updated_at          before update on public.user_videos          for each row execute function public.set_updated_at();

-- ---------- доступ: только сервер ----------
alter table public.provider_credentials enable row level security;
alter table public.ai_task_settings     enable row level security;
alter table public.videos               enable row level security;
alter table public.transcripts          enable row level security;
alter table public.translations         enable row level security;
alter table public.user_videos          enable row level security;
alter table public.chat_messages        enable row level security;

revoke all on public.provider_credentials, public.ai_task_settings, public.videos,
              public.transcripts, public.translations, public.user_videos, public.chat_messages
  from anon, authenticated;
