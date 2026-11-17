# FXI Telegram Edge — isolated staging environment

This branch is a **staging-only preparation**. The D1 staging database exists and migration 0001 has been applied and verified. The staging Worker has **not** been deployed.

## Safety boundary
- Worker target: `fxi-telegram-edge-staging`, separate from all existing Workers.
- D1 target: `fxi_bot_stage`, a new EU-jurisdiction database.
- `wrangler.toml` points only to this staging database. Never replace it with the production D1 ID.
- No production Worker, production D1, Render service, Telegram webhook, or user data was changed.
- The Worker upload API rejected a direct TypeScript source upload because TypeScript must first be compiled. The GitHub workflow now runs Wrangler's dry-run compiler; this is not a deployment.

## Staging D1 verification
Migration `0001 / fxi_core_d1_schema` was applied to the new staging D1. A read-only verification confirmed:
- `schema_migrations`, `fxi_bot_state`, `fxi_chat_messages`, `fxi_community_messages`, and `telegram_updates` exist.
- Migration version `0001` is recorded.
- `PRAGMA foreign_key_check` returned no violations.
- The database contains schema only; no production user data was copied.

## Current Worker behavior
- `GET /health`: checks D1 connectivity.
- `GET /ready`: verifies migration 0001 and expected tables.
- `POST /telegram/webhook`: validates Telegram's secret header, enforces a 1 MB payload cap, and stores updates durably.
- Duplicate updates remain idempotent. A duplicate whose prior status is `failed` is reset to `received`, increments its retry counter, and clears the previous error.
- This is still **durable ingestion only**. It does not execute production aiogram handlers, moderation, AI replies, admin panels, broadcasts, or scheduled jobs. A background consumer and dead-letter/retry policy are still required.

## Tests
Run from this directory:
```sh
python -m unittest discover -s tests -v
npm install
npx wrangler deploy --dry-run --outdir=dist
``
The GitHub workflow runs these checks. The Wrangler dry-run compiles and validates the Worker but does not publish it.

## Remaining before staging deployment
1. Confirm the GitHub Actions test and Wrangler dry-run jobs pass.
2. Add staging-only `TELEGRAM_WEBHOOK_SECRET` and any other required test credentials using Cloudflare Secrets; never reuse production credentials.
3. Deploy only `fxi-telegram-edge-staging` with the staging D1 binding.
4. Verify `/health` and `/ready`, then send a controlled test update using a dedicated test bot.
5. Implement and test the actual update consumer/handler bridge before any production webhook change.
6. Keep Render, production D1, and the production Telegram webhook unchanged until a full rollback-tested cutover is approved.

## Free-plan guardrails
The Worker uses the standard usage model and D1 only. No Workers Paid, Containers, paid add-ons, Cron keep-alive, or production traffic is configured. Monitor Workers request/CPU and D1 row-read/write limits before onboarding real traffic.
