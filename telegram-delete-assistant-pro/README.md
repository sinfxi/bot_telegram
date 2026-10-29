# Telegram Account Deletion Assistant

Persian Telegram guide bot with a password-protected web dashboard.

## Safety and limitations
- Telegram Bot API cannot delete a personal Telegram account.
- Users complete the process themselves on the official site: https://my.telegram.org/auth?to=delete
- Never ask for or store login codes, passwords, or two-step verification credentials.
- Dashboard counts represent interactions with this bot, not confirmed account deletions.

## Features
- Persian bot menu, cancel/back flows, security guidance
- SQLite event/user metrics
- HTTP Basic protected admin dashboard
- /health endpoint
- /stats command restricted to ADMIN_ID

## Environment variables
- BOT_TOKEN (required)
- ADMIN_PASSWORD (required; use a strong unique password)
- ADMIN_USER (optional, default admin)
- ADMIN_ID (optional; numeric Telegram ID for /stats)
- DB_PATH (default /data/bot.sqlite3)
- PORT (provided by host, default 8000)

## Run locally
Install dependencies with `python -m pip install -r requirements.txt`, then set environment variables and run `python app.py`.
Open `http://127.0.0.1:8000/` and enter the admin credentials.

## Railway notes
Set the service root directory to `/telegram-delete-assistant-pro`. Set all required variables in Railway's Variables panel. Attach a persistent volume at `/data` to preserve SQLite data across restarts. Keep one replica because Telegram polling should not run in multiple instances. Use HTTPS for the public dashboard.

For production/multiple replicas, use PostgreSQL and separate the bot worker from the web process.
