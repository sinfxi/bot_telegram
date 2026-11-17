# FXI Telegram Edge — isolated staging environment

This branch now has a deployed **staging-only** Worker and a separate EU D1 database. This is not a production cutover.

## Deployment status
- Worker: `fxi-telegram-edge-staging`
- Public staging origin: `https://fxi-telegram-edge-staging.99lq9ohj-kfshcd.workers.dev`
- Usage model: `standard` (Workers Free-compatible; no paid plan enabled).
- D1 binding: `DB` → `fxi_bot_stage` only.
- Deployment created on 2026-11-17 from the Wrangler dry-run compiled bundle. The uploaded script exports a `fetch` handler.
- The `workers.dev` subdomain is enabled for this staging Worker only.
- Cloudflare API read-back confirms the deployed script, standard usage model, D1 binding, deployment version, and subdomain setting.
- Runtime HTTP probes of `/health` and `/ready` could not be completed from the current integration environment. Open those URLs directly to confirm live responses before using the endpoint for any Telegram traffic.

## Safety boundary
- Worker target: `fxi-telegram-edge-staging`, separate from all existing Workers.
- D1 target: `fxi_bot_stage`, a new EU-jurisdiction database.
- `wrangler.toml` points only to this staging database. Never replace it with the production D1 ID.
- No production Worker, production D1, Render service, Telegram webhook, or user data was changed.
- No Telegram webhook was registered or redirected.
- No production credentials or secrets were copied. The staging Worker currently has **no secrets configured**, so webhook requests remain unauthorized until a staging-only `TELEGRAM_WEBHOOK_SECRET` is set securely.

## Staging D1 verification
Migration `0001 / fxi_core_d1_schema` was applied to the new staging D1. A read-only verification confirmed:
- `schema_migrations`, `fxi_bot_state`, `fxi_chat_messages`, `fxi_community_messages`, and `telegram_updates` exist.
- Migration version `0001` is recorded.
- `PRAGMA foreign_key_check` returned no violations.
- The database contains schema only; no production user data was copied.

## Current Worker behavior
- `GET /health`: checks D1 connectivity.
- `GET /ready`: verifies migration 0001 and the expected tables.
- `POST /telegram/webhook`: validates Telegram's secret header, reads the request body with a streaming 1 MB byte cap, validates the JSON object and update ID, and stores updates durably.
- Duplicate updates remain idempotent. A duplicate whose prior status is `failed` is reset to `received`, increments its retry counter, and clears the previous error.
- This is still **durable ingestion only**. It does not execute production aiogram handlers, moderation, AI replies, admin panels, broadcasts, or scheduled jobs. A background consumer and dead-letter/retry policy are still required.

## Tests and build
- GitHub Actions run #13 passed the Python safety/retry tests and Wrangler dry-run compile.
- GitHub Actions run #15 passed the same checks and uploaded the compiled staging bundle as a short-lived artifact.
- The Worker was uploaded from the compiled bundle, not raw TypeScript.
- The current workflow keeps a one-day artifact for controlled staging uploads.

Run from this directory:
```sh
python -m unittest discover -s tests -v
npm install
npx wrangler deploy --dry-run --outdir=dist
```

## Remaining before Telegram staging tests
1. Open `/health` and `/ready` and confirm both return `200` with D1 connected and schema `0001`.
2. Add a staging-only `TELEGRAM_WEBHOOK_SECRET` through Cloudflare's Worker Secrets UI. Do not paste it into chat or reuse production credentials.
3. Use a dedicated test bot to verify authorized webhook ingestion, duplicate handling, invalid payload rejection, and payload-size limits.
4. Implement and test a background consumer, handler bridge, retry/backoff, and dead-letter behavior.
5. Migrate and validate the admin panel and its authorization model.
6. Keep Render, production D1, and the production Telegram webhook unchanged until a full rollback-tested cutover is separately approved.

## Free-plan guardrails
The Worker uses the standard usage model and D1 only. No Workers Paid, Containers, paid add-ons, Cron keep-alive, or production traffic is configured. Monitor Workers request/CPU and D1 row-read/write limits before onboarding real traffic.
