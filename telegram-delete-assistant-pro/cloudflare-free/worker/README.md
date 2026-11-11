# FXI Telegram Edge (Cloudflare Worker)

This is the first runtime slice for the Cloudflare migration.

## Current scope
- `GET /health`: checks D1 connectivity.
- `GET /ready`: verifies migration 0001 is present.
- `POST /telegram/webhook`: validates Telegram's webhook secret header and durably records each update in D1 using `update_id` idempotency.
- `src/store.ts`: D1 repository methods for bot state, AI chat history, and community message archive (list/search/get/edit/delete).

## Important limitation
This worker currently performs **durable update ingestion only**. The D1 repository methods are implemented as an adapter layer but are not yet wired into the existing bot handlers. It does not yet execute the existing aiogram handlers, moderation, AI replies, admin panels, broadcasts, or scheduled jobs. Do not point the production Telegram bot webhook at it until the handler bridge and end-to-end tests are complete.

## Local validation
Install Wrangler and run:
```sh
npx wrangler dev
```

Set the secret locally or in Cloudflare:
```sh
npx wrangler secret put TELEGRAM_WEBHOOK_SECRET
```

Deploy only after reviewing the account binding and adding the secret:
```sh
npx wrangler deploy
```
