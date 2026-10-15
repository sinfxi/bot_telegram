# Independent Telegram Bot

A separate Telegram bot implementation stored in its own directory so it does not overwrite the existing project.

## Features

- Persian interactive menu
- User profile and registration
- Suggestions/reports stored in SQLite
- Admin-only statistics and report notifications
- HTTP health endpoint for deployment monitoring
- Docker deployment support

## Environment variables

- BOT_TOKEN — required; set privately in the hosting provider.
- ADMIN_IDS — comma-separated Telegram numeric IDs allowed to use admin features.
- DATABASE_PATH — SQLite path; use a persistent mounted volume such as /data/bot.db.
- PORT — HTTP health-check port; defaults to 8080.

## Railway

Create a new service from this repository and set its Root Directory to /independent_bot. Add the environment variables above, attach a persistent volume mounted at /data, then deploy. Do not connect this directory to an existing production service until its configuration has been checked.

The implementation is an independent baseline. Additional public features can be added as separate modules; it does not access private APIs or data from any other bot.
