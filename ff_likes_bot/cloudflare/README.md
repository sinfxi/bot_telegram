# Cloudflare Workers — Free Fire Request Bot

This version receives Telegram updates via webhook and stores requests in Cloudflare D1.

## Included
- Telegram webhook endpoint: `/telegram-webhook`
- Request registration and status tracking
- Admin review for Telegram ID `6384557276`
- D1-backed user, session and request storage

## Deploy
1. In Cloudflare, create a Worker named `iranff-request-bot`.
2. Create a D1 database named `iranff-request-bot-db`.
3. Run `schema.sql` against the D1 database.
4. Replace `REPLACE_WITH_D1_DATABASE_ID` in `wrangler.toml` with the D1 database ID.
5. Deploy `worker.js` from this folder using Wrangler or paste its contents into the Cloudflare dashboard.
6. Add Worker secrets `BOT_TOKEN` and `WEBHOOK_SECRET`. Generate a random webhook secret (letters, digits, underscores, hyphens; 1–256 chars). Never commit the bot token to GitHub.
7. Set the Telegram webhook to `https://YOUR-WORKER-DOMAIN/telegram-webhook` and include the same webhook secret as Telegram's `secret_token`.

Webhook setup request (run privately, substituting values locally):
`https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://YOUR-WORKER-DOMAIN/telegram-webhook&secret_token=<WEBHOOK_SECRET>`

Do not paste your bot token into public chats, code, or repository files. Any token already shared in chat should be revoked with @BotFather and replaced.

## Important limitation
This bot registers and manages requests; it does not automatically send Free Fire likes. Real automation requires an authorized, legitimate API for that service. Do not use stolen accounts, session tokens, or exploit endpoints.