#!/bin/sh
# One-time setup of the trial and stats Worker; run from anywhere.
set -e
cd "$(dirname "$0")"
npx wrangler d1 execute yana --remote --file=schema.sql -y
npx wrangler deploy
echo "Paste the OpenAI key for the free trial (stored as a Worker secret, never in the app):"
npx wrangler secret put OPENAI_API_KEY
# A random token for /admin, kept in worker/.admin-token (not committed).
[ -f .admin-token ] || python3 -c "import secrets; print(secrets.token_urlsafe(32))" > .admin-token
chmod 600 .admin-token
tr -d '\n' < .admin-token | npx wrangler secret put ADMIN_TOKEN
echo "Stats page: <the workers.dev URL above>/admin?token=$(cat .admin-token)"
