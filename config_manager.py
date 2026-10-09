"""Telegram-native admin UI for the self-hosted Xray services on Railway."""
import base64
import io
import json
import logging
import os
from urllib.parse import quote, urlencode

import aiohttp
import qrcode
from aiogram import F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
)

log = logging.getLogger(__name__)
TOKEN = os.getenv("XRAY_MANAGER_TOKEN", "")
SERVICES = {
    "vless": {
        "url": os.getenv("XRAY_VLESS_API_URL", "").strip().rstrip("/"),
        "host": os.getenv("XRAY_VLESS_HOST", "").strip(),
        "port": os.getenv("XRAY_VLESS_PORT", "").strip(),
        "label": "VLESS",
    },
    "vmess": {
        "url": os.getenv("XRAY_VMESS_API_URL", "").strip().rstrip("/"),
        "host": os.getenv("XRAY_VMESS_HOST", "").strip(),
        "port": os.getenv("XRAY_VMESS_PORT", "").strip(),
        "label": "VMess",
    },
}


class ConfigManagerError(RuntimeError):
    pass


def _service(protocol):
    protocol = protocol.lower()
    if protocol not in SERVICES:
        raise ConfigManagerError("پروتکل باید vless یا vmess باشد.")
    service = SERVICES[protocol]
    missing = [name for name, value in (
        ("XRAY_" + protocol.upper() + "_API_URL", service["url"]),
        ("XRAY_" + protocol.upper() + "_HOST", service["host"]),
        ("XRAY_" + protocol.upper() + "_PORT", service["port"]),
        ("XRAY_MANAGER_TOKEN", TOKEN),
    ) if not value]
    if missing:
        raise ConfigManagerError("تنظیمات سرویس Xray کامل نیست: " + ", ".join(missing))
    try:
        service["port_int"] = int(service["port"])
    except ValueError:
        raise ConfigManagerError("پورت عمومی Xray عددی نیست.")
    return service


async def _request(protocol, method, path, payload=None):
    service = _service(protocol)
    timeout = aiohttp.ClientTimeout(total=25)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method, service["url"] + path,
                headers={"Authorization": f"Bearer {TOKEN}"},
                json=payload,
            ) as response:
                raw = await response.text()
                try:
                    data = json.loads(raw) if raw else {}
                except ValueError:
                    data = {"error": "پاسخ سرویس Xray JSON معتبر نیست."}
                if response.status >= 400:
                    raise ConfigManagerError(str(data.get("error") or data.get("message") or f"سرویس Xray خطای HTTP {response.status} داد."))
                return data
    except asyncio.TimeoutError:
        raise ConfigManagerError("اتصال به سرویس Xray بیش از حد طول کشید.")
    except aiohttp.ClientError as exc:
        raise ConfigManagerError("اتصال به سرویس Xray برقرار نشد؛ تنظیمات Railway را بررسی کن.") from exc


def _reality_link(protocol, client, meta, service):
    host, port = service["host"], service["port_int"]
    client_id, email = client["id"], client["email"]
    sni = meta["serverName"]
    public_key, short_id = meta["publicKey"], meta["shortId"]
    if protocol == "vless":
        params = {
            "encryption": "none", "flow": "xtls-rprx-vision",
            "security": "reality", "sni": sni, "fp": "chrome",
            "pbk": public_key, "sid": short_id, "type": "tcp",
        }
        return f"vless://{quote(client_id, safe='')}@{host}:{port}?{urlencode(params)}#{quote(email)}"
    vmess = {
        "v": "2", "ps": email, "add": host, "port": str(port),
        "id": client_id, "aid": "0", "scy": "auto", "net": "tcp",
        "type": "none", "host": "", "path": "", "tls": "reality",
        "sni": sni, "fp": "chrome", "pbk": public_key, "sid": short_id,
    }
    encoded = base64.b64encode(json.dumps(vmess, separators=(",", ":")).encode()).decode()
    return "vmess://" + encoded


def _qr(link):
    code = qrcode.QRCode(box_size=7, border=3)
    code.add_data(link)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _human_bytes(value):
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _expiry(value):
    if not value:
        return "نامشخص"
    from datetime import datetime
    return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M")


def register_config_handlers(dp, bot, admin_ids):
    def allowed(uid):
        return uid in admin_ids

    def menu():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ ساخت VLESS", callback_data="xray:create:vless"),
             InlineKeyboardButton(text="➕ ساخت VMess", callback_data="xray:create:vmess")],
            [InlineKeyboardButton(text="👥 کاربران VLESS", callback_data="xray:list:vless"),
             InlineKeyboardButton(text="👥 کاربران VMess", callback_data="xray:list:vmess")],
            [InlineKeyboardButton(text="📊 وضعیت سرویس‌ها", callback_data="xray:status")],
        ])

    @dp.message(Command("config"))
    async def config_home(message: Message):
        if not message.from_user or not allowed(message.from_user.id):
            return await message.answer("⛔ این پنل فقط برای مدیر اصلی ربات است.")
        await message.answer(
            "🛰️ پنل اختصاصی Xray روی Railway\n\n"
            "• VLESS و VMess با REALITY\n"
            "• QR و لینک اتصال\n"
            "• محدودیت حجم و تاریخ انقضا\n"
            "• تمدید و لغو دسترسی\n\n"
            "فرمان‌ها:\n"
            "/confignew vless 30 20\n"
            "/confignew vmess 30 20\n"
            "/configlist vless\n"
            "/configlist vmess\n"
            "/configrenew vless UUID 30 [GB]\n"
            "/configrevoke vless UUID",
            reply_markup=menu(),
        )

    @dp.callback_query(F.data.startswith("xray:"))
    async def config_callback(callback: CallbackQuery):
        if not allowed(callback.from_user.id):
            return await callback.answer("فقط مدیر اصلی دسترسی دارد.", show_alert=True)
        data = (callback.data or "").split(":")
        action = data[1] if len(data) > 1 else ""
        try:
            if action == "status":
                lines = []
                for protocol in ("vless", "vmess"):
                    try:
                        meta = await _request(protocol, "GET", "/admin/meta")
                        clients = await _request(protocol, "GET", "/admin/clients")
                        enabled = sum(1 for c in clients.get("clients", []) if c.get("enabled"))
                        lines.append(f"✅ {protocol.upper()}: فعال، {enabled} کاربر فعال، پورت داخلی {meta.get('listenPort')}")
                    except Exception as exc:
                        lines.append(f"❌ {protocol.upper()}: {str(exc)[:180]}")
                await callback.message.answer("وضعیت سرویس‌ها:\n" + "\n".join(lines))
            elif action == "create" and len(data) == 3:
                protocol = data[2]
                _service(protocol)
                await callback.message.answer(
                    f"برای ساخت {protocol.upper()} دستور زیر را بفرست:\n"
                    f"/confignew {protocol} 30 20\n\n"
                    "عدد اول روز اعتبار و عدد دوم حجم به GB است."
                )
            elif action == "list" and len(data) == 3:
                protocol = data[2]
                clients = (await _request(protocol, "GET", "/admin/clients")).get("clients", [])
                if not clients:
                    await callback.message.answer(f"برای {protocol.upper()} کاربری ثبت نشده است.")
                else:
                    await callback.message.answer(f"فهرست {protocol.upper()} (حداکثر 20 کاربر اخیر):")
                    for client in clients[:20]:
                        status = "فعال" if client["enabled"] else "غیرفعال/منقضی"
                        text = (
                            f"👤 {client['email']}\n"
                            f"شناسه: {client['id']}\n"
                            f"وضعیت: {status}\n"
                            f"مصرف: {_human_bytes(client['usedBytes'])} از {_human_bytes(client['totalBytes'])}\n"
                            f"انقضا: {_expiry(client['expiryAt'])}"
                        )
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="🔄 تمدید ۳۰ روز", callback_data=f"xray:renew:{protocol}:{client['id']}"),
                            InlineKeyboardButton(text="🗑 لغو", callback_data=f"xray:revoke:{protocol}:{client['id']}"),
                        ]])
                        await callback.message.answer(text, reply_markup=keyboard)
            elif action == "renew" and len(data) == 4:
                protocol, client_id = data[2], data[3]
                client = await _request(protocol, "PATCH", "/admin/clients/" + quote(client_id, safe=""), {"days": 30})
                await callback.message.answer(
                    f"✅ کاربر تمدید شد.\n{client['email']}\nانقضا: {_expiry(client['expiryAt'])}\n"
                    f"حجم باقی‌مانده: {_human_bytes(client['remainingBytes'])}"
                )
            elif action == "revoke" and len(data) == 4:
                protocol, client_id = data[2], data[3]
                await _request(protocol, "DELETE", "/admin/clients/" + quote(client_id, safe=""))
                await callback.message.answer("✅ دسترسی کاربر لغو شد.")
            else:
                await callback.message.answer("عملیات پنل شناخته نشد.")
        except Exception as exc:
            log.exception("Xray Telegram panel action failed")
            await callback.message.answer(f"❌ {str(exc)[:600]}")
        await callback.answer()

    @dp.message(Command("confignew"))
    async def config_new(message: Message):
        if not message.from_user or not allowed(message.from_user.id):
            return await message.answer("⛔ فقط مدیر اصلی ربات می‌تواند کانفیگ بسازد.")
        parts = (message.text or "").split()
        if len(parts) != 4:
            return await message.answer("فرمت: /confignew <vless|vmess> <days> <GB>\nمثال: /confignew vless 30 20")
        protocol = parts[1].lower()
        try:
            _service(protocol)
            days, gb = int(parts[2]), float(parts[3])
            if not 1 <= days <= 3650 or not 0.1 <= gb <= 100000:
                raise ValueError
        except (ValueError, ConfigManagerError):
            return await message.answer("پروتکل باید vless/vmess، روز ۱ تا ۳۶۵۰ و حجم ۰٫۱ تا ۱۰۰۰۰۰ گیگابایت باشد.")
        try:
            meta = await _request(protocol, "GET", "/admin/meta")
            client = await _request(protocol, "POST", "/admin/clients", {
                "days": days, "gb": gb, "telegramUserId": message.from_user.id,
            })
            link = _reality_link(protocol, client, client["reality"], _service(protocol))
            caption = (
                f"✅ کانفیگ واقعی {protocol.upper()} ساخته شد\n"
                f"شناسه: {client['email']}\n"
                f"حجم: {gb:g} GB\nاعتبار: {days} روز\n"
                f"انقضا: {_expiry(client['expiryAt'])}\n"
                f"امنیت: REALITY | SNI: {meta['serverName']}\n"
                f"سقف حجم و انقضا روی سرویس Xray اعمال می‌شود."
            )
            await message.answer_photo(BufferedInputFile(_qr(link), filename=f"{client['email']}.png"), caption=caption)
            await message.answer(link)
        except Exception as exc:
            log.exception("Xray client creation failed")
            await message.answer(f"❌ ساخت کانفیگ ناموفق بود: {str(exc)[:600]}")

    @dp.message(Command("configlist"))
    async def config_list(message: Message):
        if not message.from_user or not allowed(message.from_user.id):
            return await message.answer("⛔ فقط مدیر اصلی دسترسی دارد.")
        parts = (message.text or "").split()
        if len(parts) != 2:
            return await message.answer("فرمت: /configlist <vless|vmess>")
        try:
            protocol = parts[1].lower()
            clients = (await _request(protocol, "GET", "/admin/clients")).get("clients", [])
            if not clients:
                return await message.answer("کاربری ثبت نشده است.")
            for client in clients[:20]:
                status = "فعال" if client["enabled"] else "غیرفعال/منقضی"
                text = (
                    f"👤 {client['email']}\nشناسه: {client['id']}\nوضعیت: {status}\n"
                    f"مصرف: {_human_bytes(client['usedBytes'])} از {_human_bytes(client['totalBytes'])}\n"
                    f"انقضا: {_expiry(client['expiryAt'])}"
                )
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🔄 تمدید ۳۰ روز", callback_data=f"xray:renew:{protocol}:{client['id']}"),
                    InlineKeyboardButton(text="🗑 لغو", callback_data=f"xray:revoke:{protocol}:{client['id']}"),
                ]])
                await message.answer(text, reply_markup=keyboard)
        except Exception as exc:
            await message.answer(f"❌ {str(exc)[:600]}")

    @dp.message(Command("configrenew"))
    async def config_renew(message: Message):
        if not message.from_user or not allowed(message.from_user.id):
            return await message.answer("⛔ فقط مدیر اصلی دسترسی دارد.")
        parts = (message.text or "").split()
        if len(parts) not in (4, 5):
            return await message.answer("فرمت: /configrenew <vless|vmess> <UUID> <days> [GB]")
        try:
            protocol, client_id = parts[1].lower(), parts[2]
            _service(protocol)
            days = int(parts[3])
            body = {"days": days}
            if len(parts) == 5:
                body["gb"] = float(parts[4])
            client = await _request(protocol, "PATCH", "/admin/clients/" + quote(client_id, safe=""), body)
            await message.answer(
                f"✅ تمدید انجام شد.\n{client['email']}\nانقضا: {_expiry(client['expiryAt'])}\n"
                f"حجم مصرف‌شده: {_human_bytes(client['usedBytes'])}\n"
                f"حجم کل: {_human_bytes(client['totalBytes'])}"
            )
        except Exception as exc:
            await message.answer(f"❌ تمدید ناموفق بود: {str(exc)[:600]}")

    @dp.message(Command("configrevoke"))
    async def config_revoke(message: Message):
        if not message.from_user or not allowed(message.from_user.id):
            return await message.answer("⛔ فقط مدیر اصلی دسترسی دارد.")
        parts = (message.text or "").split()
        if len(parts) != 3:
            return await message.answer("فرمت: /configrevoke <vless|vmess> <UUID>")
        try:
            protocol, client_id = parts[1].lower(), parts[2]
            await _request(protocol, "DELETE", "/admin/clients/" + quote(client_id, safe=""))
            await message.answer("✅ دسترسی کاربر لغو شد.")
        except Exception as exc:
            await message.answer(f"❌ لغو دسترسی ناموفق بود: {str(exc)[:600]}")
