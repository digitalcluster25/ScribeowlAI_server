-- Ключи транскрипт-провайдеров пользователя (transcriptapi) хранятся там же, где ключи AI-провайдеров:
-- provider_credentials, шифрование AES-256-GCM на сервере. Расширяем допустимые provider_id.
alter table public.provider_credentials drop constraint provider_credentials_provider_id_check;
alter table public.provider_credentials add constraint provider_credentials_provider_id_check
  check (provider_id in ('openai','openrouter','google','anthropic','groq','deepgram','transcriptapi'));
