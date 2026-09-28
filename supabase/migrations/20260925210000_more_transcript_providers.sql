-- Новые транскрипт-провайдеры с ключом пользователя: supadata, easytranscriber, chocodata.
alter table public.provider_credentials drop constraint provider_credentials_provider_id_check;
alter table public.provider_credentials add constraint provider_credentials_provider_id_check
  check (provider_id in ('openai','openrouter','google','anthropic','groq','deepgram',
                         'transcriptapi','supadata','easytranscriber','chocodata'));
