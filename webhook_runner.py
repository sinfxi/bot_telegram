"""Webhook entrypoint for the existing aiogram bot.

Run this on Railway instead of bot.py. Telegram webhooks and getUpdates polling
are mutually exclusive, so this prevents any old poller from stealing updates.
"""
import asyncio
import hmac
import logging
import os

from aiohttp import web
from aiogram.types import Update

import bot as core

logging.basicConfig(level=logging.INFO)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
PORT = int(os.getenv("PORT", "8080"))


async def health(_request):
    return web.Response(text="OK")


async def telegram_update(request):
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(supplied, WEBHOOK_SECRET):
        raise web.HTTPForbidden(text="forbidden")
    try:
        payload = await request.json()
        update = Update.model_validate(payload, context={"bot": core.bot})
        await core.dp.feed_update(core.bot, update)
    except Exception:
        logging.exception("Failed to process Telegram webhook update")
        # Return 500 so Telegram retries this update.
        raise web.HTTPInternalServerError(text="update processing failed")
    return web.Response(text="OK")


async def main():
    if not WEBHOOK_URL or not WEBHOOK_SECRET:
        raise RuntimeError("WEBHOOK_URL and WEBHOOK_SECRET must be configured")
    if not (8 <= len(WEBHOOK_SECRET) <= 256):
        raise RuntimeError("WEBHOOK_SECRET must be 8-256 characters")

    app = web.Application(client_max_size=2 * 1024 * 1024)
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_post("/telegram/webhook", telegram_update)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    # Webhook mode makes Telegram reject getUpdates calls from any stale poller.
    await core.bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=False,
        allowed_updates=core.dp.resolve_used_update_types(),
    )
    await core.set_bot_commands()
    maintenance_task = asyncio.create_task(core.maintenance())
    logging.info("Telegram webhook active at %s", WEBHOOK_URL)

    try:
        await asyncio.Event().wait()
    finally:
        maintenance_task.cancel()
        await runner.cleanup()
        await core.bot.session.close()
        core.db.close()


if __name__ == "__main__":
    asyncio.run(main())
