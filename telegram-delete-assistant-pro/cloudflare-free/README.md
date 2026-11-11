# FXI Telegram Edge — Cloudflare

The Cloudflare runtime now has a Python Worker entrypoint that imports the existing Aiogram/FastAPI application and routes Telegram webhook updates into the real dispatcher. It does not start long-running polling tasks.

## Runtime design
- `cloudflare-free/entry.py` is the Python Worker entrypoint.
- FastAPI is served through Cloudflare's ASGI adapter.
- `POST /telegram/webhook` validates Telegram's secret header, deduplicates updates in D1, and calls `Dispatcher.feed_update()`.
- `GET /ready` authenticates the bot with Telegram, checks D1, and configures the webhook only after the handler is loaded.
- The bot's admin state and bounded AI conversation history are persisted as JSON in `fxi_bot_state` in D1. Community message logs remain bounded in that state document.
- The existing PostgreSQL-only indexed archive endpoints are not enabled in this D1 runtime; the admin conversation views require D1-specific routes before they can be considered complete.
- No Render polling, Render keepalive, or Cron Trigger is used.

## Build and deploy
Run from `telegram-delete-assistant-pro/`:

```bash
uv sync
uv run pywrangler dev
uv run pywrangler deploy
```

The repository workflow runs compile/import checks and a Wrangler dry-run. A successful package build is not by itself proof that Telegram updates are being processed.

## Required Cloudflare secrets
- `ZEUS_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET`
- `OPENROUTER_API_KEY`
- `ADMIN_IDS`
- `ADMIN_PANEL_PASSWORD`

Never commit secret values.

## Release gate
The production release is complete only after the Python Worker bundle deploys, `/ready` returns HTTP 200, Telegram's webhook points to this Worker, a real private message receives a reply, a group update is processed, and D1 state survives a subsequent request/restart. Do not delete any remaining legacy database until the D1 state and chat-history checks have passed.
