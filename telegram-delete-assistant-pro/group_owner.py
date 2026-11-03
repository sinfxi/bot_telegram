"""Secure, group-scoped owner portal for FXI Telegram communities."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from itsdangerous import URLSafeTimedSerializer


COOKIE_NAME = "fxi_group_owner_session"
SESSION_TTL = 12 * 60 * 60
OTP_TTL = 120
STATIC_DIR = Path(__file__).parent / "static"


def install_group_owner(app, bot):
    secret = os.getenv("SESSION_SECRET", "").strip() or bot.BOT_TOKEN
    signer = URLSafeTimedSerializer(secret, salt="fxi-group-owner-session") if secret else None
    request_stamps: dict[str, list[float]] = {}

    def origin_ok(request: Request) -> bool:
        return bot._admin_origin_allowed(request)

    def tg():
        return getattr(bot, "bot", None)

    def decode_session(request: Request):
        if not signer:
            return {}
        token = request.cookies.get(COOKIE_NAME, "")
        try:
            data = signer.loads(token, max_age=SESSION_TTL) if token else {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def verify_group_owner(chat_id: int, user_id: int):
        telegram = tg()
        if telegram is None:
            raise HTTPException(503, "ربات تلگرام در حال حاضر در دسترس نیست.")
        try:
            chat = await telegram.get_chat(chat_id)
            if chat.type not in {"group", "supergroup"}:
                raise HTTPException(400, "شناسه واردشده مربوط به گروه یا سوپرگروه نیست.")
            bot_member = await telegram.get_chat_member(chat_id, telegram.id)
            if bot_member.status not in {"administrator", "creator"}:
                raise HTTPException(403, "ربات باید ابتدا به گروه اضافه شود و دسترسی مدیر داشته باشد.")
            owner_member = await telegram.get_chat_member(chat_id, user_id)
            if owner_member.status != "creator":
                raise HTTPException(403, "این حساب مالک اصلی گروه نیست. فقط سازنده گروه اجازه ورود دارد.")
            return chat, owner_member
        except HTTPException:
            raise
        except Exception as exc:
            bot.log.info("Group owner verification failed for chat=%s user=%s: %s", chat_id, user_id, type(exc).__name__)
            raise HTTPException(403, "بررسی مالکیت گروه ممکن نشد؛ شناسه گروه و دسترسی مدیر ربات را بررسی کن.")

    async def require_group_owner(request: Request):
        data = decode_session(request)
        try:
            chat_id = int(data.get("chat_id", 0))
            user_id = int(data.get("user_id", 0))
            version = int(data.get("version", 0))
        except (TypeError, ValueError):
            raise HTTPException(401, "نشست معتبر نیست؛ دوباره وارد شو.")
        if chat_id >= 0 or user_id <= 0:
            raise HTTPException(401, "نشست معتبر نیست؛ دوباره وارد شو.")
        record = bot.admin_data.get("community", {}).get("chats", {}).get(str(chat_id), {})
        current_version = int(record.get("group_owner_session_version", 1)) if isinstance(record, dict) else 1
        if version != current_version:
            raise HTTPException(401, "نشست لغو شده است؛ دوباره وارد شو.")
        await verify_group_owner(chat_id, user_id)
        return {"chat_id": chat_id, "user_id": user_id}

    def rate_limit(request: Request):
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        stamps = [stamp for stamp in request_stamps.get(ip, []) if now - stamp < 900]
        if len(stamps) >= 8:
            raise HTTPException(429, "تعداد درخواست‌ها زیاد است؛ ۱۵ دقیقه دیگر دوباره تلاش کن.")
        stamps.append(now)
        request_stamps[ip] = stamps
        return ip

    def save():
        bot.save_admin_data()

    def record_for(chat_id: int):
        record = bot.community_chat(chat_id)
        if not isinstance(record.get("message_log"), list):
            record["message_log"] = []
        return record

    @app.get("/group-owner", response_class=HTMLResponse)
    async def group_owner_login_page(request: Request):
        session = decode_session(request)
        if session.get("chat_id") and session.get("user_id"):
            return RedirectResponse("/group-owner/panel", status_code=303)
        page = (STATIC_DIR / "group-owner-login.html").read_text(encoding="utf-8")
        return HTMLResponse(page, headers={"Cache-Control": "no-store, max-age=0"})

    @app.get("/group-owner/panel", response_class=HTMLResponse)
    async def group_owner_panel(auth=Depends(require_group_owner)):
        page = (STATIC_DIR / "group-owner.html").read_text(encoding="utf-8")
        return HTMLResponse(page, headers={"Cache-Control": "no-store, max-age=0"})

    @app.get("/group-owner/static/{asset}")
    async def group_owner_static(asset: str):
        allowed = {"group-owner.css", "group-owner.js"}
        if asset not in allowed:
            raise HTTPException(404, "فایل پیدا نشد.")
        path = STATIC_DIR / asset
        if not path.is_file():
            raise HTTPException(404, "فایل پیدا نشد.")
        return Response(path.read_text(encoding="utf-8"), media_type="text/css" if asset.endswith(".css") else "application/javascript",
                            headers={"Cache-Control": "public, max-age=300"})

    @app.post("/group-owner/api/request-code")
    async def group_owner_request_code(request: Request):
        if not origin_ok(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        rate_limit(request)
        try:
            payload = await request.json()
            chat_id = int(payload.get("chat_id", 0))
            user_id = int(payload.get("user_id", 0))
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(400, "شناسه عددی گروه و حساب تلگرام را درست وارد کن.")
        if chat_id >= 0 or user_id <= 0:
            raise HTTPException(400, "شناسه گروه باید منفی و شناسه کاربر باید مثبت باشد.")
        chat, _ = await verify_group_owner(chat_id, user_id)
        challenges = bot.admin_data.setdefault("group_owner_otp_challenges", {})
        key = f"{chat_id}:{user_id}"
        previous = challenges.get(key, {})
        now = time.time()
        if isinstance(previous, dict) and now - float(previous.get("sent_at", 0)) < 45:
            raise HTTPException(429, "برای دریافت کد تازه ۴۵ ثانیه صبر کن.")
        code = f"{secrets.randbelow(1_000_000):06d}"
        salt = secrets.token_hex(16)
        digest = hashlib.sha256(f"group-owner:{chat_id}:{user_id}:{salt}:{code}".encode()).hexdigest()
        challenges[key] = {"salt": salt, "hash": digest, "expires_at": now + OTP_TTL,
                           "sent_at": now, "attempts": 0, "title": chat.title or str(chat_id)}
        save()
        try:
            await tg().send_message(
                user_id,
                "🔐 <b>کد ورود پنل مالک گروه FXI</b>\n\n"
                f"گروه: <b>{(chat.title or 'گروه')[:120]}</b>\n"
                f"<code>{code}</code>\n\n"
                "⏳ این کد ۲ دقیقه اعتبار دارد و فقط یک‌بار قابل استفاده است.\n"
                "🛡 کد را در اختیار هیچ‌کس قرار نده.",
                parse_mode="HTML",
            )
        except Exception as exc:
            challenges.pop(key, None)
            save()
            bot.log.info("Group owner OTP delivery failed: %s", type(exc).__name__)
            raise HTTPException(503, "ارسال کد ممکن نشد؛ مالک گروه باید ابتدا ربات را در خصوصی Start کند.")
        return {"message": "کد ورود به تلگرام مالک گروه ارسال شد.", "expires_in": OTP_TTL, "group_title": chat.title}

    @app.post("/group-owner/api/login")
    async def group_owner_login(request: Request):
        if not origin_ok(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        rate_limit(request)
        try:
            payload = await request.json()
            chat_id = int(payload.get("chat_id", 0))
            user_id = int(payload.get("user_id", 0))
            code = str(payload.get("code", ""))
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(400, "اطلاعات ورود معتبر نیست.")
        if not re.fullmatch(r"[0-9]{6}", code):
            raise HTTPException(400, "کد باید دقیقاً ۶ رقم باشد.")
        key = f"{chat_id}:{user_id}"
        challenges = bot.admin_data.setdefault("group_owner_otp_challenges", {})
        challenge = challenges.get(key)
        now = time.time()
        if not isinstance(challenge, dict):
            raise HTTPException(401, "کد معتبر نیست یا قبلاً استفاده شده است.")
        if now >= float(challenge.get("expires_at", 0)):
            challenges.pop(key, None)
            save()
            raise HTTPException(401, "کد منقضی شده؛ کد تازه درخواست بده.")
        if int(challenge.get("attempts", 0)) >= 5:
            challenges.pop(key, None)
            save()
            raise HTTPException(429, "پس از ۵ تلاش ناموفق، کد باطل شد.")
        expected = hashlib.sha256(f"group-owner:{chat_id}:{user_id}:{challenge.get('salt','')}:{code}".encode()).hexdigest()
        if not hmac.compare_digest(expected, str(challenge.get("hash", ""))):
            challenge["attempts"] = int(challenge.get("attempts", 0)) + 1
            if challenge["attempts"] >= 5:
                challenges.pop(key, None)
            save()
            raise HTTPException(401, "کد اشتباه است.")
        await verify_group_owner(chat_id, user_id)
        # Consume OTP before issuing the session to prevent replay.
        challenges.pop(key, None)
        record = record_for(chat_id)
        version = int(record.get("group_owner_session_version", 1))
        save()
        response = JSONResponse({"redirect": "/group-owner/panel"})
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
        response.set_cookie(COOKIE_NAME, signer.dumps({"chat_id": chat_id, "user_id": user_id, "version": version}),
                            max_age=SESSION_TTL, httponly=True, secure=secure, samesite="strict", path="/group-owner")
        return response

    @app.post("/group-owner/api/logout")
    async def group_owner_logout(request: Request):
        if not origin_ok(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        response = JSONResponse({"redirect": "/group-owner"})
        response.delete_cookie(COOKIE_NAME, path="/group-owner")
        return response

    @app.get("/group-owner/api/overview")
    async def group_owner_overview(auth=Depends(require_group_owner)):
        chat_id = auth["chat_id"]
        record = record_for(chat_id)
        telegram = tg()
        chat = await telegram.get_chat(chat_id)
        member_count = None
        try:
            member_count = await telegram.get_chat_member_count(chat_id)
        except Exception:
            pass
        settings = record.setdefault("settings", {})
        return {
            "chat": {"id": chat_id, "title": chat.title or record.get("title") or str(chat_id),
                     "type": chat.type, "member_count": member_count,
                     "message_count": int(record.get("message_count", 0)),
                     "members_seen": len(record.get("members_seen", {})),
                     "bot_enabled": bool(record.get("settings", {}).get("bot_enabled", True)),
                     "last_activity": record.get("last_activity") or record.get("last_message_at", "")},
            "settings": {key: settings.get(key, default) for key, default in {
                "bot_enabled": True, "ai_enabled": True, "conversational_ai": False,
                "welcome_enabled": True, "anti_flood_enabled": True, "link_guard_enabled": False,
                "keyword_filter_enabled": False, "media_guard_enabled": False,
                "warn_limit": 3, "flood_limit": bot.COMMUNITY_MAX_MESSAGES,
                "welcome_message": ""}.items()},
            "rules": record.get("rules", ""),
            "blocked_words": record.get("blocked_words", []),
            "bot_status": "admin",
        }

    @app.get("/group-owner/api/messages")
    async def group_owner_messages(limit: int = 80, offset: int = 0, auth=Depends(require_group_owner)):
        record = record_for(auth["chat_id"])
        rows = record.get("message_log", [])
        limit = max(1, min(100, limit))
        offset = max(0, min(10000, offset))
        selected = list(reversed(rows)) [offset:offset + limit]
        return {"items": selected, "total": len(rows), "limit": limit, "offset": offset,
                "history_note": "فقط پیام‌هایی نمایش داده می‌شوند که پس از فعال‌شدن ثبت پیام توسط ربات دریافت شده‌اند."}

    @app.get("/group-owner/api/members")
    async def group_owner_members(limit: int = 100, auth=Depends(require_group_owner)):
        record = record_for(auth["chat_id"])
        members = record.get("members_seen", {})
        items = [{"user_id": int(uid), **profile} for uid, profile in members.items() if str(uid).isdigit() and isinstance(profile, dict)]
        items.sort(key=lambda item: str(item.get("last_seen", "")), reverse=True)
        return {"items": items[:max(1, min(200, limit))], "total_seen": len(items)}

    @app.post("/group-owner/api/settings")
    async def group_owner_update_settings(request: Request, auth=Depends(require_group_owner)):
        if not origin_ok(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(400, "تنظیمات معتبر نیست.")
        record = record_for(auth["chat_id"])
        settings = record.setdefault("settings", {})
        bool_keys = {"bot_enabled", "ai_enabled", "conversational_ai", "welcome_enabled",
                     "anti_flood_enabled", "link_guard_enabled", "keyword_filter_enabled", "media_guard_enabled"}
        changes = payload.get("settings", {})
        if not isinstance(changes, dict) or any(key not in bool_keys or not isinstance(value, bool) for key, value in changes.items()):
            raise HTTPException(422, "تنها تنظیمات مجاز روشن/خاموش قابل تغییر هستند.")
        settings.update(changes)
        if "warn_limit" in payload:
            value = int(payload["warn_limit"])
            if not 2 <= value <= 5:
                raise HTTPException(422, "حد اخطار باید بین ۲ تا ۵ باشد.")
            settings["warn_limit"] = value
        if "flood_limit" in payload:
            value = int(payload["flood_limit"])
            if not 3 <= value <= 20:
                raise HTTPException(422, "حد ضداسپم باید بین ۳ تا ۲۰ باشد.")
            settings["flood_limit"] = value
        if "welcome_message" in payload:
            settings["welcome_message"] = str(payload["welcome_message"]).strip()[:500]
        if "rules" in payload:
            rules = str(payload["rules"]).strip()
            if len(rules) > 3000:
                raise HTTPException(422, "قوانین حداکثر ۳۰۰۰ نویسه باشد.")
            record["rules"] = rules
        if "blocked_words" in payload:
            words = payload["blocked_words"]
            if not isinstance(words, list) or len(words) > 100:
                raise HTTPException(422, "حداکثر ۱۰۰ واژه مجاز است.")
            cleaned = []
            for word in words:
                word = str(word).strip().casefold()
                if not word or len(word) > 60 or any(char.isspace() for char in word):
                    raise HTTPException(422, "هر واژه باید کوتاه و بدون فاصله باشد.")
                if word not in cleaned:
                    cleaned.append(word)
            record["blocked_words"] = cleaned
        save()
        bot.log_admin_action("group_owner_settings_updated", f"chat={auth['chat_id']}; owner={auth['user_id']}; keys={','.join(changes.keys())}")
        return {"message": "تنظیمات گروه ذخیره شد.", "settings": settings, "rules": record.get("rules", "")}

    @app.post("/group-owner/api/messages/{message_id}/delete")
    async def group_owner_delete_message(message_id: int, request: Request, auth=Depends(require_group_owner)):
        if not origin_ok(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        record = record_for(auth["chat_id"])
        row = next((item for item in record.get("message_log", []) if int(item.get("message_id", 0)) == message_id), None)
        if row is None:
            raise HTTPException(404, "این پیام در تاریخچه ثبت‌شده پیدا نشد.")
        try:
            await tg().delete_message(auth["chat_id"], message_id)
        except Exception as exc:
            bot.log.info("Group owner delete failed chat=%s message=%s: %s", auth["chat_id"], message_id, type(exc).__name__)
            raise HTTPException(409, "حذف پیام ممکن نشد؛ پیام قدیمی است یا ربات مجوز حذف پیام ندارد.")
        record["message_log"] = [item for item in record.get("message_log", []) if int(item.get("message_id", 0)) != message_id]
        save()
        bot.log_admin_action("group_owner_message_deleted", f"chat={auth['chat_id']}; message={message_id}; owner={auth['user_id']}")
        return {"message": "پیام حذف شد."}

    @app.post("/group-owner/api/messages/{message_id}/edit")
    async def group_owner_edit_bot_message(message_id: int, request: Request, auth=Depends(require_group_owner)):
        if not origin_ok(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(400, "متن پیام معتبر نیست.")
        text = str(payload.get("text", "")).strip()
        if not text or len(text) > 4000:
            raise HTTPException(422, "متن جدید باید بین ۱ تا ۴۰۰۰ نویسه باشد.")
        record = record_for(auth["chat_id"])
        row = next((item for item in record.get("message_log", []) if int(item.get("message_id", 0)) == message_id), None)
        if row is None:
            raise HTTPException(404, "پیام در تاریخچه ثبت‌شده پیدا نشد.")
        if not row.get("is_bot"):
            raise HTTPException(403, "تلگرام اجازه ویرایش پیام اعضا را به ربات نمی‌دهد؛ فقط پیام‌های خود ربات قابل ویرایش‌اند.")
        try:
            await tg().edit_message_text(chat_id=auth["chat_id"], message_id=message_id, text=text)
        except Exception as exc:
            bot.log.info("Group owner edit failed chat=%s message=%s: %s", auth["chat_id"], message_id, type(exc).__name__)
            raise HTTPException(409, "ویرایش پیام ممکن نشد؛ شاید پیام حذف یا ویرایش‌ناپذیر شده باشد.")
        row["text"] = text
        row["edited_at"] = datetime.now(timezone.utc).isoformat()
        save()
        bot.log_admin_action("group_owner_bot_message_edited", f"chat={auth['chat_id']}; message={message_id}; owner={auth['user_id']}")
        return {"message": "پیام ربات ویرایش شد."}

    @app.post("/group-owner/api/members/{user_id}/{action}")
    async def group_owner_member_action(user_id: int, action: str, request: Request, auth=Depends(require_group_owner)):
        if not origin_ok(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        if action not in {"ban", "unban", "mute", "unmute"} or user_id <= 0:
            raise HTTPException(400, "عملیات یا شناسه کاربر معتبر نیست.")
        telegram = tg()
        chat_id = auth["chat_id"]
        try:
            member = await telegram.get_chat_member(chat_id, user_id)
            if member.status in {"creator", "administrator"} and action in {"ban", "mute"}:
                raise HTTPException(403, "مدیران و مالک گروه را نمی‌توان با این ابزار محدود کرد.")
            if action == "ban":
                await telegram.ban_chat_member(chat_id, user_id)
            elif action == "unban":
                await telegram.unban_chat_member(chat_id, user_id, only_if_banned=False)
            elif action == "mute":
                payload = await request.json()
                minutes = max(1, min(10080, int(payload.get("minutes", 60))))
                from aiogram.types import ChatPermissions
                await telegram.restrict_chat_member(chat_id, user_id, permissions=ChatPermissions(can_send_messages=False),
                                                    until_date=datetime.now(timezone.utc) + timedelta(minutes=minutes))
            else:
                from aiogram.types import ChatPermissions
                await telegram.restrict_chat_member(chat_id, user_id, permissions=ChatPermissions(
                    can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True,
                    can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True,
                    can_send_other_messages=True, can_add_web_page_previews=True))
        except HTTPException:
            raise
        except Exception as exc:
            bot.log.info("Group owner member action failed chat=%s user=%s action=%s: %s", chat_id, user_id, action, type(exc).__name__)
            raise HTTPException(409, "عملیات انجام نشد؛ مجوزهای مدیریتی ربات را بررسی کن.")
        bot.log_admin_action("group_owner_member_action", f"chat={chat_id}; user={user_id}; action={action}; owner={auth['user_id']}")
        return {"message": "عملیات انجام شد."}

    @app.post("/group-owner/api/leave")
    async def group_owner_remove_bot(request: Request, auth=Depends(require_group_owner)):
        if not origin_ok(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        try:
            await tg().leave_chat(auth["chat_id"])
        except Exception as exc:
            bot.log.info("Bot leave failed for group %s: %s", auth["chat_id"], type(exc).__name__)
            raise HTTPException(409, "خروج ربات از گروه انجام نشد.")
        record = bot.admin_data.get("community", {}).get("chats", {}).get(str(auth["chat_id"]), {})
        if isinstance(record, dict):
            record["bot_removed_at"] = datetime.now(timezone.utc).isoformat()
            record["group_owner_session_version"] = int(record.get("group_owner_session_version", 1)) + 1
        save()
        bot.log_admin_action("group_owner_removed_bot", f"chat={auth['chat_id']}; owner={auth['user_id']}")
        response = JSONResponse({"message": "ربات از گروه خارج شد.", "redirect": "/group-owner"})
        response.delete_cookie(COOKIE_NAME, path="/group-owner")
        return response

    @app.get("/group-owner/api/add-link")
    async def group_owner_add_link(auth=Depends(require_group_owner)):
        username = bot.TELEGRAM_BOT_USERNAME
        return {"url": f"https://t.me/{username}?startgroup=true", "note": "افزودن مستقیم ربات با شناسه گروه از طریق Telegram Bot API ممکن نیست؛ مالک باید از این لینک ربات را به گروه اضافه کند."}

    # Owner-bot-panel endpoints: same group data, but destructive actions are owner-only.
    @app.get("/admin/api/community/{chat_id}/messages")
    async def owner_panel_group_messages(chat_id: int, auth=Depends(bot.require_admin)):
        record = bot.admin_data.get("community", {}).get("chats", {}).get(str(chat_id))
        if not isinstance(record, dict):
            raise HTTPException(404, "گروه ثبت نشده است.")
        rows = list(reversed(record.get("message_log", [])))
        return {"items": rows[:100], "total": len(rows)}

    @app.post("/admin/api/community/{chat_id}/messages/{message_id}/delete")
    async def owner_panel_delete_group_message(chat_id: int, message_id: int, request: Request, auth=Depends(bot.require_admin)):
        if not origin_ok(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        if auth.get("auth_type") != "owner":
            raise HTTPException(403, "فقط مالک ربات اجازه این عملیات را دارد.")
        record = bot.admin_data.get("community", {}).get("chats", {}).get(str(chat_id), {})
        if not any(int(item.get("message_id", 0)) == message_id for item in record.get("message_log", [])):
            raise HTTPException(404, "پیام در تاریخچه ثبت‌شده نیست.")
        try:
            await tg().delete_message(chat_id, message_id)
        except Exception:
            raise HTTPException(409, "حذف پیام ممکن نشد؛ مجوز یا محدودیت زمانی تلگرام را بررسی کن.")
        record["message_log"] = [item for item in record.get("message_log", []) if int(item.get("message_id", 0)) != message_id]
        save()
        bot.log_admin_action("owner_panel_group_message_deleted", f"chat={chat_id}; message={message_id}")
        return {"message": "پیام حذف شد."}

    @app.post("/admin/api/community/{chat_id}/messages/{message_id}/edit")
    async def owner_panel_edit_group_message(chat_id: int, message_id: int, request: Request, auth=Depends(bot.require_admin)):
        if not origin_ok(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        if auth.get("auth_type") != "owner":
            raise HTTPException(403, "فقط مالک ربات اجازه این عملیات را دارد.")
        payload = await request.json()
        text = str(payload.get("text", "")).strip()
        if not text or len(text) > 4000:
            raise HTTPException(422, "متن جدید باید بین ۱ تا ۴۰۰۰ نویسه باشد.")
        record = bot.admin_data.get("community", {}).get("chats", {}).get(str(chat_id), {})
        row = next((item for item in record.get("message_log", []) if int(item.get("message_id", 0)) == message_id), None)
        if not row or not row.get("is_bot"):
            raise HTTPException(403, "فقط پیام‌های خود ربات قابل ویرایش هستند.")
        try:
            await tg().edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
        except Exception:
            raise HTTPException(409, "ویرایش پیام ممکن نشد.")
        row["text"] = text
        row["edited_at"] = datetime.now(timezone.utc).isoformat()
        save()
        bot.log_admin_action("owner_panel_group_message_edited", f"chat={chat_id}; message={message_id}")
        return {"message": "پیام ربات ویرایش شد."}

    @app.post("/admin/api/community/{chat_id}/leave")
    async def owner_panel_leave_group(chat_id: int, request: Request, auth=Depends(bot.require_admin)):
        if not origin_ok(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        if auth.get("auth_type") != "owner":
            raise HTTPException(403, "فقط مالک ربات اجازه خروج ربات از گروه را دارد.")
        try:
            await tg().leave_chat(chat_id)
        except Exception:
            raise HTTPException(409, "خروج ربات از گروه انجام نشد.")
        record = bot.admin_data.get("community", {}).get("chats", {}).get(str(chat_id), {})
        if isinstance(record, dict):
            record["bot_removed_at"] = datetime.now(timezone.utc).isoformat()
        save()
        bot.log_admin_action("owner_panel_bot_left_group", f"chat={chat_id}")
        return {"message": "ربات از گروه خارج شد."}

    @app.get("/admin/api/community/{chat_id}/add-link")
    async def owner_panel_group_add_link(chat_id: int, auth=Depends(bot.require_admin)):
        if auth.get("auth_type") != "owner":
            raise HTTPException(403, "فقط مالک ربات اجازه ساخت لینک افزودن را دارد.")
        return {"url": f"https://t.me/{bot.TELEGRAM_BOT_USERNAME}?startgroup=true",
                "note": "افزودن مستقیم از طریق Bot API ممکن نیست؛ این لینک افزودن ربات به گروه را باز می‌کند."}
