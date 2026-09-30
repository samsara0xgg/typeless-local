# Yana trial and stats Worker

A Cloudflare Worker with a D1 database. It refines on the owner's OpenAI key for
Macs on the free trial, stores the app's anonymous daily counts, and serves an
owner-only stats page. See `src/index.js`.

## Deploy

From this folder:

```sh
npx wrangler login
npx wrangler d1 create yana            # put the printed database_id in wrangler.toml
npx wrangler d1 execute yana --remote --file=schema.sql
npx wrangler secret put OPENAI_API_KEY # the trial key; paste it at the prompt
npx wrangler secret put ADMIN_TOKEN    # any long random string
npx wrangler deploy                    # prints https://yana.<subdomain>.workers.dev
```

Then set the `free-trial` preset's `base_url` in `assets/config.yaml` to that
URL plus `/v1`, and build the app.

Give the OpenAI key a monthly budget in the OpenAI dashboard as well; the
Worker's own caps are `DEVICE_BUDGET_USD` and `MONTHLY_BUDGET_USD` in
`wrangler.toml`.

## Stats

`https://yana.<subdomain>.workers.dev/admin?token=<ADMIN_TOKEN>` shows installs,
daily and weekly active Macs, dictations per active Mac per day, 7-day retention
by first week, versions in use and trial spend.

## Local test

`npx wrangler dev` runs it against a local D1 (apply `schema.sql` with `--local`
first); set `UPSTREAM` to a stub server to avoid spending on OpenAI.
