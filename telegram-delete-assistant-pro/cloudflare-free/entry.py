from __future__ import annotations

import asyncio
import hmac
import importlib
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asgi
from workers import WorkerEntrypoint

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Statically import the real bot so Pywrangler includes it in the Worker bundle.
# The admin HTML itself is served through the Workers ASSETS binding.
_original_path_read_text = Path.read_text
def _static_html_placeholder(self, *args, **kwargs):
    if self.name == "admin.html" and self.parent.name == "static":
        return ""
    return _original_path_read_text(self, *args, **kwargs)

Path.read_text = _static_html_placeholder
try:
    import zeus_bot as _module
finally:
    Path.read_text = _original_path_read_text

_ENV_KEYS = (
    "ZEUS_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET",
    "OPENROUTER_API_KEY",
    "ADMIN_IDS",
    "ADMIN_PANEL_PASSWORD",
    "ADMIN_PANEL_USERNAME",
    "OPENROUTER_MODEL",
    "OPENROUTER_SITE_URL",
    "ADMIN_PANEL_URL",
    "ADMIN_ALLOWED_ORIGINS",
    "TELEGRAM_BOT_USERNAME",
    "AI_SYSTEM_PROMPT",
    "ZEUS_ADMIN_ID",
    "OWNER_TELEGRAM_ID",
)
_bootstrap_lock = asyncio.Lock()
_request_lock = asyncio.Lock()
_module = None


class _AsyncioWorkerFacade:
    """Replace thread offloading with inline calls; Workers Python has no usable threads."""

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)

    async def to_thread(self, func, /, *args, **kwargs):
        return func(*args, **kwargs)


def _env_value(env, key: str) -> str:
    try:
        value = getattr(env, key)
    except Exception:
        value = None
    return str(value) if value is not None else ""


async def _load_application(env):
    global _module
    if _module is not None:
        return _module

    async with _bootstrap_lock:
        if _module is not None:
            return _module

        for key in _ENV_KEYS:
            value = _env_value(env, key)
            if value:
                os.environ[key] = value

        os.environ["FXI_DEPLOYMENT_PLATFORM"] = "Cloudflare Workers"
        os.environ["DATABASE_URL"] = ""
        os.environ.setdefault("ADMIN_PANEL_URL", "https://fxi-telegram-edge.fxi-media-engine.workers.dev")

        module = _module
        bot_token = _env_value(env, "ZEUS_BOT_TOKEN")
        module.BOT_TOKEN = bot_token
        module.SESSION_SERIALIZER = (
            module.URLSafeTimedSerializer(bot_token, salt="fxi-web-session") if bot_token else None
        )
        module.ADMIN_PANEL_URL = os.getenv("ADMIN_PANEL_URL", "https://fxi-telegram-edge.fxi-media-engine.workers.dev").rstrip("/")
        os.environ.setdefault("OPENROUTER_SITE_URL", module.ADMIN_PANEL_URL)
        module.ADMIN_PANEL_USERNAME = os.getenv("ADMIN_PANEL_USERNAME", "fxi-admin").strip()
        module.ADMIN_PANEL_PASSWORD = _env_value(env, "ADMIN_PANEL_PASSWORD").strip()
        module.TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "The_fxi_bot").strip().lstrip("@")
        module.SYSTEM_PROMPT = os.getenv("AI_SYSTEM_PROMPT", module.SYSTEM_PROMPT)
        module.ADMIN_IDS = {
            int(part.strip())
            for part in _env_value(env, "ADMIN_IDS").replace(";", ",").split(",")
            if part.strip().isdigit()
        }
        owner_id = _env_value(env, "OWNER_TELEGRAM_ID") or _env_value(env, "ZEUS_ADMIN_ID")
        if owner_id.isdigit():
            module.ADMIN_IDS.add(int(owner_id))
        for admin_id in module.ADMIN_IDS:
            if admin_id not in module.admin_data.setdefault("admins", []):
                module.admin_data["admins"].append(admin_id)
        module.PROVIDERS["openrouter"]["key"] = _env_value(env, "OPENROUTER_API_KEY").strip()
        module.PROVIDERS["openrouter"]["model"] = os.getenv("OPENROUTER_MODEL", "openrouter/free").strip()
        allowed_origins = [module.ADMIN_PANEL_URL, *os.getenv("ADMIN_ALLOWED_ORIGINS", "").split(",")]
        module.ADMIN_ALLOWED_ORIGINS = {
            f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
            for value in allowed_origins if value.strip()
            for parsed in [module.urlsplit(value.strip())]
            if parsed.scheme.lower() in {"http", "https"} and parsed.netloc
        }
        module.DATABASE_URL = ""
        module.DATABASE_READY = False
        module.asyncio = _AsyncioWorkerFacade()
        module._cloudflare_state_dirty = False
        module._cloudflare_d1 = None

        def mark_state_dirty() -> None:
            module.prune_ephemeral_admin_state()
            module._cloudflare_state_dirty = True

        module.save_admin_data = mark_state_dirty

        @asynccontextmanager
        async def no_process_lifespan(_app):
            # Cloudflare Workers are request-driven; never start Aiogram polling or
            # long-running watchdog tasks. Telegram updates enter through feed_update.
            yield

        module.app.router.lifespan_context = no_process_lifespan

        async def persistent_ask_ai(user_id: int, provider_id: str, user_text: str) -> str:
            if provider_id != "openrouter" or provider_id not in module.PROVIDERS:
                return "⚠️ در این نسخه فقط OpenRouter قابل استفاده است."
            if not module.feature_enabled("ai_chat"):
                return "⛔ پاسخ‌گویی هوشمند توسط مدیر غیرفعال شده است."
            if not module.provider_ready(provider_id):
                return "🔒 OpenRouter فعال نیست؛ مدیر باید OPENROUTER_API_KEY را تنظیم کند."

            key = (int(user_id), provider_id)
            async with module.history_locks[key]:
                history_key = f"{int(user_id)}:{provider_id}"
                all_histories = module.admin_data.setdefault("chat_histories", {})
                history = all_histories.setdefault(history_key, [])
                try:
                    status, data = await module.ask_compatible(provider_id, history, user_text)
                    if status >= 400:
                        return module.api_error(provider_id, status, data)
                    answer = module.extract_answer(provider_id, data)
                    if not answer:
                        return "⚠️ سرویس OpenRouter پاسخ خالی برگرداند؛ مدل و تنظیمات API را بررسی کن."
                    stamp = module.datetime.now(module.timezone.utc).isoformat()
                    history.extend([
                        {"role": "user", "content": user_text, "provider_id": provider_id, "created_at": stamp},
                        {"role": "assistant", "content": answer, "provider_id": provider_id, "created_at": stamp},
                    ])
                    del history[:-module.MAX_HISTORY_MESSAGES]
                    module.histories[key] = history
                    module.save_admin_data()
                    return answer
                except asyncio.TimeoutError:
                    return "⏳ سرویس OpenRouter پاسخ نداد؛ دوباره تلاش کن."
                except Exception:
                    module.log.exception("Cloudflare persistent AI request failed")
                    return "⚠️ هنگام استفاده از OpenRouter خطایی رخ داد؛ کمی بعد دوباره تلاش کن."

        module.ask_ai = persistent_ask_ai

        from fastapi import Request, Depends
        from fastapi.responses import JSONResponse, Response, HTMLResponse
        from fastapi.routing import APIRoute
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.types import Update
        import aiohttp

        async def ensure_schema(db) -> None:
            await db.prepare(
                "CREATE TABLE IF NOT EXISTS fxi_bot_state "
                "(id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL, "
                "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            ).run()
            await db.prepare(
                "CREATE TABLE IF NOT EXISTS fxi_telegram_updates "
                "(update_id INTEGER PRIMARY KEY, payload_json TEXT NOT NULL, "
                "status TEXT NOT NULL DEFAULT 'received', attempts INTEGER NOT NULL DEFAULT 0, "
                "received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, processed_at TEXT, last_error TEXT)"
            ).run()

        async def ensure_bot() -> None:
            if module.bot is not None:
                return
            token = module.BOT_TOKEN
            if not token:
                raise RuntimeError("ZEUS_BOT_TOKEN is not configured")
            module.bot = Bot(token, default=DefaultBotProperties(parse_mode=None))
            me = await module.bot.get_me()
            if me.username:
                module.TELEGRAM_BOT_USERNAME = me.username.lstrip("@")
            if module.HTTP_SESSION is None or module.HTTP_SESSION.closed:
                module.HTTP_SESSION = aiohttp.ClientSession(timeout=module.REQUEST_TIMEOUT)
            # The existing admin metrics endpoint uses this polling-task sentinel.
            class WebhookActive:
                @staticmethod
                def done():
                    return False
            module.polling_task = WebhookActive()

        @module.app.middleware("http")
        async def persist_d1_state(request: Request, call_next):
            env_obj = request.scope.get("env")
            db = getattr(env_obj, "DB", None) if env_obj is not None else None
            if db is None:
                return JSONResponse({"ok": False, "error": "d1_binding_unavailable"}, status_code=503)

            async with _request_lock:
                module._cloudflare_d1 = db
                await ensure_schema(db)
                row = await db.prepare("SELECT data FROM fxi_bot_state WHERE id = 1").first()
                state_missing = not bool(row)
                if row and row["data"]:
                    try:
                        saved = json.loads(row["data"])
                        if isinstance(saved, dict):
                            module.admin_data.clear()
                            module.admin_data.update(saved)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        return JSONResponse({"ok": False, "error": "state_record_invalid"}, status_code=503)
                module.bot_enabled = bool(module.admin_data.get("bot_enabled", True))
                module._cloudflare_state_dirty = state_missing
                try:
                    response = await call_next(request)
                except Exception:
                    await flush_state(db)
                    raise
                if request.url.path == "/telegram/webhook" or request.url.path.startswith("/admin/api/"):
                    module._cloudflare_state_dirty = True
                await flush_state(db)
                return response

        async def flush_state(db) -> None:
            if not module._cloudflare_state_dirty:
                return
            serialized = json.dumps(module.admin_data, ensure_ascii=False, separators=(",", ":"), default=str)
            await db.prepare(
                "INSERT INTO fxi_bot_state (id, data, updated_at) VALUES (1, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = CURRENT_TIMESTAMP"
            ).bind(serialized).run()
            module._cloudflare_state_dirty = False

        async def health(_request: Request):
            try:
                await module._cloudflare_d1.prepare("SELECT 1 AS ok").first()
                return {"ok": True, "service": "fxi-telegram-edge", "database": "connected"}
            except Exception:
                return JSONResponse({"ok": False, "database": "unavailable"}, status_code=503)

        async def readiness(request: Request):
            try:
                await ensure_bot()
                db = module._cloudflare_d1
                await db.prepare("SELECT 1 AS ok").first()
                secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
                if not secret:
                    raise RuntimeError("TELEGRAM_WEBHOOK_SECRET is not configured")
                webhook_url = str(request.base_url).rstrip("/") + "/telegram/webhook"
                await module.bot.set_webhook(
                    url=webhook_url,
                    secret_token=secret,
                    allowed_updates=module.dp.resolve_used_update_types(),
                    drop_pending_updates=False,
                )
                return {
                    "ok": True,
                    "ready": True,
                    "telegram": "authenticated",
                    "webhook": "configured",
                    "database": "connected",
                    "ai_configured": module.provider_ready("openrouter"),
                }
            except Exception as exc:
                module.log.exception("Cloudflare readiness check failed")
                return JSONResponse(
                    {"ok": False, "ready": False, "reason": type(exc).__name__},
                    status_code=503,
                )

        async def telegram_webhook(request: Request):
            expected = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
            supplied = request.headers.get("x-telegram-bot-api-secret-token", "")
            if not expected or not hmac.compare_digest(supplied, expected):
                return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

            try:
                payload = await request.json()
            except Exception:
                return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
            update_id = payload.get("update_id") if isinstance(payload, dict) else None
            if not isinstance(update_id, int) or update_id < 0:
                return JSONResponse({"ok": False, "error": "invalid_update_id"}, status_code=400)

            db = module._cloudflare_d1
            await db.prepare(
                "INSERT OR IGNORE INTO fxi_telegram_updates (update_id, payload_json, status) VALUES (?, ?, 'received')"
            ).bind(update_id, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))).run()
            saved_update = await db.prepare(
                "SELECT status FROM fxi_telegram_updates WHERE update_id = ?"
            ).bind(update_id).first()
            if saved_update and saved_update["status"] == "processed":
                return {"ok": True, "duplicate": True}

            try:
                await ensure_bot()
                update = Update.model_validate(payload, context={"bot": module.bot})
                await module.dp.feed_update(module.bot, update)
                await db.prepare(
                    "UPDATE fxi_telegram_updates SET status = 'processed', processed_at = CURRENT_TIMESTAMP, "
                    "last_error = NULL WHERE update_id = ?"
                ).bind(update_id).run()
                return {"ok": True, "processed": True}
            except Exception as exc:
                module.log.exception("Telegram webhook update failed: update_id=%s", update_id)
                await db.prepare(
                    "UPDATE fxi_telegram_updates SET status = 'failed', attempts = attempts + 1, last_error = ? "
                    "WHERE update_id = ?"
                ).bind(type(exc).__name__, update_id).run()
                return JSONResponse({"ok": False, "error": "update_processing_failed"}, status_code=500)

        async def fetch_static(request: Request, asset_path: str):
            if not asset_path or any(part in {"", ".", ".."} for part in asset_path.split("/")):
                return JSONResponse({"ok": False, "error": "asset_not_found"}, status_code=404)
            env_obj = request.scope.get("env")
            assets = getattr(env_obj, "ASSETS", None) if env_obj is not None else None
            if assets is None:
                return JSONResponse({"ok": False, "error": "assets_binding_unavailable"}, status_code=503)
            upstream = await assets.fetch("https://assets.local/" + asset_path)
            body = await upstream.bytes()
            headers = {}
            for key in ("content-type", "cache-control", "etag", "last-modified"):
                value = upstream.headers.get(key)
                if value:
                    headers[key] = value
            return Response(content=body, status_code=upstream.status, headers=headers)

        async def admin_page(request: Request):
            return await fetch_static(request, "admin.html")

        async def group_owner_page(request: Request):
            return await fetch_static(request, "group-owner.html")

        async def group_owner_login_page(request: Request):
            return await fetch_static(request, "group-owner-login.html")

        async def static_asset(request: Request, asset_path: str):
            return await fetch_static(request, asset_path)

        async def d1_conversations(_auth=Depends(module.require_admin)):
            items = []
            for key, messages in module.admin_data.get("chat_histories", {}).items():
                if not isinstance(messages, list) or not messages:
                    continue
                try:
                    user_id, provider_id = key.rsplit(":", 1)
                    last = messages[-1]
                    items.append({
                        "user_id": int(user_id),
                        "message_count": len(messages),
                        "last_message": last.get("created_at"),
                        "preview": str(last.get("content", ""))[:180],
                    })
                except (TypeError, ValueError, AttributeError):
                    continue
            items.sort(key=lambda item: item.get("last_message") or "", reverse=True)
            return {"items": items[:100]}

        async def d1_conversation(user_id: int, _auth=Depends(module.require_admin)):
            messages = []
            prefix = f"{int(user_id)}:"
            for key, rows in module.admin_data.get("chat_histories", {}).items():
                if not str(key).startswith(prefix) or not isinstance(rows, list):
                    continue
                messages.extend(rows)
            messages.sort(key=lambda item: item.get("created_at") or "")
            return {"messages": messages[-100:]}

        # Cloudflare static assets replace local FileResponse reads in the Worker runtime.
        module.app.router.routes.insert(0, APIRoute("/static/{asset_path:path}", static_asset, methods=["GET"]))
        module.app.router.routes.insert(0, APIRoute("/group-owner-login", group_owner_login_page, methods=["GET"]))
        module.app.router.routes.insert(0, APIRoute("/group-owner", group_owner_page, methods=["GET"]))
        module.app.router.routes.insert(0, APIRoute("/admin/", admin_page, methods=["GET"]))
        module.app.router.routes.insert(0, APIRoute("/admin", admin_page, methods=["GET"]))
        module.app.router.routes.insert(0, APIRoute("/admin/api/conversations/{user_id}", d1_conversation, methods=["GET"]))
        module.app.router.routes.insert(0, APIRoute("/admin/api/conversations", d1_conversations, methods=["GET"]))

        # Put Cloudflare-specific routes before the legacy readiness/health handlers.
        module.app.router.routes.insert(0, APIRoute("/telegram/webhook", telegram_webhook, methods=["POST"]))
        module.app.router.routes.insert(0, APIRoute("/ready", readiness, methods=["GET"]))
        module.app.router.routes.insert(0, APIRoute("/health", health, methods=["GET"]))

        _module = module
        return module


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        app_module = await _load_application(self.env)
        return await asgi.fetch(app_module.app, request, self.env)
