#!/usr/bin/env bash
set -euo pipefail

base=/opt/scribeowl-api
test -s "$base/server.env"
test -s "$base/db.env"
grep -q '^SUPABASE_URL=.' "$base/server.env"
grep -q '^SUPABASE_SERVICE_ROLE_KEY=.' "$base/server.env"

docker load -i "$base/scribeowl-api-stage.tar.gz"
docker run --rm --network host \
  --env-file "$base/db.env" \
  -v "$base/supabase:/work/supabase" -w /work \
  node:24-bookworm-slim \
  sh -c 'test -n "$STAGE_SUPABASE_DB_URL" && npx --yes supabase@2.118.0 db push --db-url "$STAGE_SUPABASE_DB_URL" --yes'
docker compose -p scribeowl-api -f "$base/compose.stage.yml" up -d --force-recreate
rm "$base/scribeowl-api-stage.tar.gz" "$base/supabase-migrations.tar.gz"
