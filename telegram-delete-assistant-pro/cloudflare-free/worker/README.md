# FXI Telegram Edge — isolated staging scaffold

This branch is a **GitHub-only preparation change**. It has not been deployed.

## Safety boundary
- Worker name: `fxi-telegram-edge-staging`, separate from the existing Worker.
- D1 database name: `fxi_bot_stage`.
- The D1 ID in `wrangler.toml` is deliberately an all-zero placeholder. Deployment is not ready until a separate staging D1 database is created and its ID is inserted here.
- Never replace the placeholder with the production D1 ID.
- No production Worker, production D1 database, Render service, Telegram webhook, or user data is changed by this branch.
- Do not run `wrangler deploy` until a dedicated staging database exists and the configuration has been reviewed.

## Current behavior
- `GET /health`: checks D1 connectivity.
- `GET /ready`: verifies migration 0001 is present.
- `POST /telegram/webhook`: validates Telegram's secret header, enforces a 1 MB payload cap, and stores updates durably.
- Duplicate updates remain idempotent. A duplicate whose prior status is `failed` is reset to `received`, increments its retry counter, and clears the previous error.
- This is still **durable ingestion only**. It does not execute production aiogram handlers, moderation, AI replies, admin panels, broadcasts, or scheduled jobs. Re-queueing a failed update is not a complete background processing worker.

## Local tests
Run from this directory: `python -m unittest discover -s tests -v`.
Tests use Python's standard library and an in-memory SQLite database. They do not deploy or contact Cloudflare/Telegram.

## Before any staging deployment
1. Create a new D1 database named `fxi_bot_stage` explicitly in Cloudflare.
2. Apply the migration to that staging database only.
3. Replace the all-zero placeholder with that staging database's ID.
4. Review the Worker name and D1 binding again.
5. Add staging-only secrets; never copy production secrets into staging.
6. Run local tests and a staging-only end-to-end test.
7. Keep the production webhook unchanged until the full handler bridge and rollback plan are proven.
