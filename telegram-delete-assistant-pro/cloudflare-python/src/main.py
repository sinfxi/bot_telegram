"""Isolated Cloudflare Python Worker runtime for the FXI Telegram assistant.

This staging runtime intentionally does not import zeus_bot.py: the production
application starts long-lived polling/background tasks and uses PostgreSQL.
The Worker receives Telegram webhook updates and uses D1 + Workers fetch.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from urllib.parse import urlparse

from workers import WorkerEntrypoint, Response, fetch

LOG = logging.getLogger("fxi.telegram.cloudflare")
MAX_TEXT = 3500
BOT_USERNAME = "The_fxi_bot"


def _field(value, key: str, default=None):
    try:
        return value[key]
    except Exception:
        return getattr(value, key, default)


def _json(payload: dict, status: int = 200) -> Response:
    return Response.json(payload, status=status, headers={"cache-control": "no-store"})


def _clean(value: object, limit: int = MAX_TEXT) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def _constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


async def _telegram(token: str, method: str, payload: dict | None = None) -> dict:
    if not token:
        raise RuntimeError("telegram_token_missing")
    response = await fetch(
        f"https://api.telegram.org/bot{token}/{method}",
        method="POST",
        headers={"content-type": "application/json"},
        body=json.dumps(payload or {}),
    )
    data = await response.json()
    if not response.ok or data.get("ok") is not True:
        raise RuntimeError(f"telegram_api_{method}_failed")
    return data.get("result") or {}


async def _ensure_schema(db) -> None:
    statements = [
        """CREATE TABLE IF NOT EXISTS fxi_py_updates (
            update_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'received',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            processed_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS fxi_py_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE INDEX IF NOT EXISTS idx_fxi_py_messages_chat
            ON fxi_py_messages(chat_id, id DESC)""",
        """CREATE TABLE IF NOT EXISTS fxi_py_channel_posts (
            chat_id TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            posted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(chat_id, message_id)
        )""",
    ]
    for statement in statements:
        await db.prepare(statement).run()


async def _remember(db, chat_id: str, role: str, content: str) -> None:
    await db.prepare(
        "INSERT INTO fxi_py_messages(chat_id, role, content) VALUES(?,?,?)"
    ).bind(chat_id, role, _clean(content, 4000)).run()
    await db.prepare(
        """DELETE FROM fxi_py_messages WHERE chat_id = ?
           AND id NOT IN (SELECT id FROM fxi_py_messages
                          WHERE chat_id = ? ORDER BY id DESC LIMIT 12)"""
    ).bind(chat_id, chat_id).run()


async def _history(db, chat_id: str) -> list[dict]:
    result = await db.prepare(
        "SELECT role, content FROM fxi_py_messages WHERE chat_id = ? ORDER BY id DESC LIMIT 12"
    ).bind(chat_id).all()
    rows = _field(result, "results", []) or []
    return [{"role": _field(row, "role", ""), "content": _field(row, "content", "")} for row in reversed(list(rows))]


async def _ai_reply(env, history: list[dict], prompt: str) -> str:
    key = getattr(env, "OPENROUTER_API_KEY", "")
    if not key:
        return "پیامت رو گرفتم؛ اتصال هوش مصنوعی هنوز در محیط آزمایشی تنظیم نشده."
    model = getattr(env, "OPENROUTER_MODEL", "openrouter/auto")
    messages = [
        {
            "role": "system",
            "content": "تو دستیار فارسی‌زبان FXI هستی. طبیعی، دقیق و دوستانه پاسخ بده. کوتاه و مرتبط بنویس.",
        },
        *history,
        {"role": "user", "content": prompt},
    ]
    response = await fetch(
        "https://openrouter.ai/api/v1/chat/completions",
        method="POST",
        headers={
            "authorization": f"Bearer {key}",
            "content-type": "application/json",
            "http-referer": "https://fxi-telegram-edge.fxi-media-engine.workers.dev",
            "x-title": "FXI Telegram Assistant",
        },
        body=json.dumps({"model": model, "messages": messages, "temperature": 0.7, "max_tokens": 500}),
    )
    if not response.ok:
        raise RuntimeError("openrouter_request_failed")
    data = await response.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("openrouter_empty_response")
    return _clean((choices[0].get("message") or {}).get("content"), 3800)


async def _handle_update(update: dict, env, db) -> None:
    message = update.get("message") or update.get("edited_message")
    channel_post = update.get("channel_post") or update.get("edited_channel_post")
    if channel_post:
        chat = channel_post.get("chat") or {}
        content = _clean(channel_post.get("text") or channel_post.get("caption"))
        if chat.get("id") is not None and content:
            await db.prepare(
                """INSERT INTO fxi_py_channel_posts(chat_id, message_id, content)
                   VALUES(?,?,?) ON CONFLICT(chat_id,message_id)
                   DO UPDATE SET content=excluded.content"""
            ).bind(str(chat["id"]), channel_post.get("message_id"), content).run()
        return

    if not message:
        return
    sender = message.get("from") or {}
    if sender.get("is_bot"):
        return
    chat = message.get("chat") or {}
    if chat.get("id") is None:
        return
    text = _clean(message.get("text") or message.get("caption"))
    if not text:
        return

    chat_id = str(chat["id"])
    chat_type = chat.get("type", "")
    username = _clean(getattr(env, "TELEGRAM_BOT_USERNAME", BOT_USERNAME), 64).lstrip("@").lower()
    command = text.split(maxsplit=1)[0].split("@", 1)[0].lower()
    if command == "/start":
        await _telegram(env.ZEUS_BOT_TOKEN, "sendMessage", {
            "chat_id": chat_id,
            "text": "سلام! 👋 من ربات FXI هستم. برای گفتگو پیام بده.",
            "reply_to_message_id": message.get("message_id"),
        })
        return
    if command == "/help":
        await _telegram(env.ZEUS_BOT_TOKEN, "sendMessage", {
            "chat_id": chat_id,
            "text": "در گفت‌وگوی خصوصی پیام بده؛ در گروه من را با @The_fxi_bot منشن کن یا به پیامم پاسخ بده.",
        })
        return

    reply = message.get("reply_to_message") or {}
    reply_from = reply.get("from") or {}
    addressed = chat_type == "private" or f"@{username}" in text.lower() or (
        (reply_from.get("username") or "").lower() == username
    )
    if not addressed:
        return

    prompt = _clean(text.replace(f"@{username}", "").strip()) or text
    history = await _history(db, chat_id)
    await _remember(db, chat_id, "user", prompt)
    answer = await _ai_reply(env, history, prompt)
    await _telegram(env.ZEUS_BOT_TOKEN, "sendMessage", {
        "chat_id": chat_id,
        "text": answer,
        "reply_to_message_id": message.get("message_id"),
        "allow_sending_without_reply": True,
    })
    await _remember(db, chat_id, "assistant", answer)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        parsed = urlparse(request.url)
        path = parsed.path

        if request.method == "GET" and path in ("/", "/health"):
            return _json({"service": "FXI Telegram Python Worker", "ok": True, "runtime": "python-workers"})

        if request.method == "GET" and path == "/ready":
            try:
                await self.env.DB.prepare("SELECT 1").first()
                configured = bool(getattr(self.env, "ZEUS_BOT_TOKEN", "")) and bool(
                    getattr(self.env, "TELEGRAM_WEBHOOK_SECRET", "")
                )
                return _json({"ready": configured, "database": "connected",
                              "telegram_secrets_configured": configured}, 200 if configured else 503)
            except Exception:
                LOG.exception("readiness_check_failed")
                return _json({"ready": False, "database": "unavailable"}, 503)

        if request.method == "POST" and path == "/telegram/webhook":
            expected = getattr(self.env, "TELEGRAM_WEBHOOK_SECRET", "")
            supplied = request.headers.get("x-telegram-bot-api-secret-token", "")
            if not expected or not _constant_time_equal(supplied, expected):
                return _json({"ok": False}, 401)
            try:
                update = await request.json()
            except Exception:
                return _json({"error": "invalid_json"}, 400)
            update_id = update.get("update_id") if isinstance(update, dict) else None
            if not isinstance(update_id, int) or update_id < 0:
                return _json({"error": "invalid_update_id"}, 400)

            # Schema is deployed through versioned D1 migrations, never per webhook.
            await self.env.DB.prepare(
                "INSERT OR IGNORE INTO fxi_py_updates(update_id) VALUES(?)"
            ).bind(update_id).run()
            claim = await self.env.DB.prepare(
                """UPDATE fxi_py_updates
                   SET status='processing', claimed_at=CURRENT_TIMESTAMP
                   WHERE update_id=? AND (
                     status IN ('received','failed') OR
                     (status='processing' AND claimed_at < datetime('now','-2 minutes'))
                   )"""
            ).bind(update_id).run()
            if _field(_field(claim, "meta", {}), "changes", 0) != 1:
                return _json({"ok": True, "duplicate": True})
            try:
                await _handle_update(update, self.env, self.env.DB)
                await self.env.DB.prepare(
                    "UPDATE fxi_py_updates SET status='processed', processed_at=CURRENT_TIMESTAMP, claimed_at=NULL WHERE update_id=?"
                ).bind(update_id).run()
                return _json({"ok": True, "processed": True})
            except Exception:
                LOG.exception("telegram_update_failed")
                await self.env.DB.prepare(
                    "UPDATE fxi_py_updates SET status='failed', claimed_at=NULL WHERE update_id=?"
                ).bind(update_id).run()
                return _json({"ok": False, "error": "processing_failed"}, 500)

        if request.method == "GET" and path.startswith("/static/"):
            assets = getattr(self.env, "ASSETS", None)
            if assets:
                return await assets.fetch(request)
        return _json({"error": "not_found"}, 404)
