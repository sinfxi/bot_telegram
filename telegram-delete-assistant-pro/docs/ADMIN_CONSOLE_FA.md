# FXI Admin Console

The web product is administrator-only. The end-user web chat has been retired.

## Entry points
- `/` redirects to `/admin`.
- `/admin` is protected by HTTP Basic authentication.
- The former `/app` user interface and Telegram-login web-chat API have been removed.
- Users continue to interact with the bot through Telegram; this is not a user-facing web dashboard.

## Admin modules
1. **Overview** — registered Telegram users, administrators, configured AI providers, and bot on/off control.
2. **AI providers** — readiness overview without exposing API credentials. Readiness means required environment variables exist; it does not prove that the upstream key/model is valid.
3. **Users and administrators** — recent user IDs, add/remove delegated administrators, and protected primary administrators.
4. **Conversation archive** — searchable-by-selection conversation index and message thread viewer backed by PostgreSQL.
5. **Payment review** — list support/admin-access requests, inspect OCR amount/confidence and approve/reject with user notification. OCR is not proof of payment; the operator must verify the transfer independently.
6. **Broadcast** — send an announcement to the registered Telegram audience with a confirmation prompt in the browser.
7. **Assistant instructions** — edit the system prompt used by the AI assistant.
8. **System health** — Telegram polling state, PostgreSQL readiness, AI provider configuration counts, and bot operating state.

## Required configuration
- `ADMIN_PANEL_USERNAME`
- `ADMIN_PANEL_PASSWORD` (use a long unique secret)
- `ADMIN_IDS` (comma-separated primary Telegram administrator IDs)
- `ZEUS_BOT_TOKEN`
- `DATABASE_URL` for persistent state and conversation history
- Provider-specific API keys as documented in `docs/API_SETUP_FA.md`

## Security notes
- Never commit bot tokens, API keys, database credentials, or the admin password.
- The panel does not display provider secrets.
- Keep HTTPS enabled at the hosting provider.
- Give delegated admin access only to trusted Telegram IDs.
- Broadcast and payment approval are consequential actions; verify the target and content before confirming.
- Conversation history may contain personal data. Restrict panel access and apply a retention policy appropriate to the deployment.

## Current scope / not implemented claims
This release does not claim to provide a full audit-log explorer, CSV exports, granular role/permission matrix, user bans, scheduled campaigns, automated payment verification, or live provider credential editing. These require separate implementation and tests before being presented as available controls.
