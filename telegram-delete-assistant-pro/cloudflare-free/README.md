# FXI Telegram Edge (Cloudflare)

This Worker is currently a webhook-ingestion scaffold, not the production Telegram bot.

## Current behavior
- GET /health: verifies the D1 binding.
- GET /ready: intentionally returns HTTP 503 until the production Aiogram dispatcher is connected.
- POST /telegram/webhook: validates Telegram's webhook secret and stores deduplicated updates in D1.
- No Render keepalive, Render URL, or Cron Trigger is configured.

## Production blockers
1. Connect the real Aiogram dispatcher through a webhook-compatible Python Worker entrypoint.
2. Port persistent bot state, chat history, and community archive from PostgreSQL/file fallbacks to Cloudflare-supported storage.
3. Add the Telegram bot token, webhook secret, OpenRouter key, and owner/admin configuration as Cloudflare secrets/variables. Never commit them.
4. Set Telegram's webhook only after /ready returns HTTP 200 and an end-to-end Telegram message test passes.

Do not treat successful deployment of this ingestion Worker as proof that the bot is online.
