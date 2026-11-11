# FXI Telegram Edge — JavaScript Worker

This branch replaces the Python/Aiogram runtime with a lightweight JavaScript webhook Worker designed for the Cloudflare Workers Free CPU budget.

## Current implementation
- Telegram webhook with secret-header verification.
- Telegram update deduplication and processing status in D1.
- Private chat replies; group replies only to commands, explicit bot mentions, or replies to the bot.
- OpenRouter chat completions with bounded per-chat history stored in D1.
- Basic `/start`, `/help`, and admin-only `/status`.
- Health and readiness endpoints.

## Deploy
From this directory:
```sh
npx wrangler deploy --config wrangler.toml
```

Required Worker secrets: `ZEUS_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `OPENROUTER_API_KEY`.
Required variable: `ADMIN_IDS`; optional: `OPENROUTER_MODEL`, `TELEGRAM_BOT_USERNAME`.

After deployment:
1. Check `/health` returns 200.
2. Check `/ready` returns 200.
3. Register webhook using Telegram `setWebhook` with URL `https://fxi-telegram-edge.fxi-media-engine.workers.dev/telegram/webhook` and the exact same secret token.
4. Verify `getWebhookInfo`, then send a private message and test group mention/reply.

This is a minimal functional runtime, not a complete port of the former Python bot. Existing advanced moderation, owner/manager panel, broadcasts, channel analytics and archive management still require porting and end-to-end tests before claiming feature parity.
