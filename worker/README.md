# Yana trial and stats Worker

A Cloudflare Worker with a D1 database. It refines on the owner's OpenAI key for
Macs on the free trial, stores the app's anonymous daily counts, and serves an
owner-only stats page. See `src/index.js`.

## Deploy

From this folder:

```sh
npx wrangler login
npx wrangler d1 create yana            # already done; the id is in wrangler.toml
npx wrangler d1 execute yana --remote --file=schema.sql
npx wrangler secret put OPENAI_API_KEY # the trial key; paste it at the prompt
npx wrangler secret put ADMIN_TOKEN    # any long random string
npx wrangler deploy                    # prints https://yana.<subdomain>.workers.dev
```

Then set the `free-trial` preset's `base_url` in `assets/config.yaml` to that
URL plus `/v1`, and build the app.

Give the OpenAI key a monthly budget in the OpenAI dashboard as well; the
Worker's own caps are `DEVICE_BUDGET_USD`, `IP_DAILY_BUDGET_USD` and
`MONTHLY_BUDGET_USD` in `wrangler.toml`. Each request reserves its worst-case
cost against all three before it goes upstream and settles at the real cost.
Only the app's own refine request is accepted (its system prompt, one user
message, a capped output); bodies over 64 KB are refused. After changing
`schema.sql`, run `./deploy.sh` (or the `d1 execute` line) again: it only adds
tables.

## Stats

`https://yana.<subdomain>.workers.dev/admin?token=<ADMIN_TOKEN>` (once; a cookie
keeps it out of the address bar after that) shows installs,
daily and weekly active Macs, dictations per active Mac per day, 7-day retention
by first week, versions in use and trial spend.

## Local test

`node --test worker/test/*.test.mjs` (Node 24) runs the trial and admin logic
against an in-memory SQLite in place of D1, with OpenAI stubbed.

`npx wrangler dev` runs it against a local D1 (apply `schema.sql` with `--local`
first); set `UPSTREAM` to a stub server to avoid spending on OpenAI.
