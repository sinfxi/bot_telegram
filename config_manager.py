"""Config manager for 3x-ui-compatible Xray panels."""
import os, io, json, time, uuid, base64, logging
from urllib.parse import urlencode, quote
import aiohttp
import qrcode
from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile

log = logging.getLogger(__name__)
URL = os.getenv("XRAY_PANEL_URL", "").strip().rstrip("/")
USERNAME = os.getenv("XRAY_PANEL_USERNAME", "").strip()
PASSWORD = os.getenv("XRAY_PANEL_PASSWORD", "")
PUBLIC_HOST = os.getenv("XRAY_PUBLIC_HOST", "").strip()
VERIFY_TLS = os.getenv("XRAY_VERIFY_TLS", "true").lower() not in {"0", "false", "no"}
_sessions = {}

class PanelError(RuntimeError):
    pass

class XrayPanel:
    def __init__(self):
        if not all((URL, USERNAME, PASSWORD, PUBLIC_HOST)):
            raise PanelError("تنظیمات پنل ناقص است؛ XRAY_PANEL_URL، XRAY_PANEL_USERNAME، XRAY_PANEL_PASSWORD و XRAY_PUBLIC_HOST را در Railway تنظیم کن.")
        self.session = aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(unsafe=True),
            timeout=aiohttp.ClientTimeout(total=20),
            connector=aiohttp.TCPConnector(ssl=VERIFY_TLS),
        )
        self.logged_in = False

    async def close(self):
        await self.session.close()

    async def request(self, method, path, **kwargs):
        async with self.session.request(method, URL + path, **kwargs) as resp:
            raw = await resp.text()
            if resp.status >= 400:
                raise PanelError(f"پنل پاسخ HTTP {resp.status} داد.")
            try:
                data = json.loads(raw)
            except ValueError:
                raise PanelError("پاسخ پنل JSON نیست؛ احتمالاً API این پنل سازگار نیست.")
            if isinstance(data, dict) and data.get("success") is False:
                raise PanelError(str(data.get("msg") or "عملیات پنل ناموفق بود."))
            return data

    async def login(self):
        data = await self.request("POST", "/login", data={"username": USERNAME, "password": PASSWORD})
        if isinstance(data, dict) and data.get("success") is False:
            raise PanelError("ورود به پنل ناموفق بود؛ نام کاربری و رمز را بررسی کن.")
        self.logged_in = True

    async def call(self, method, path, **kwargs):
        if not self.logged_in:
            await self.login()
        return await self.request(method, path, **kwargs)

    async def inbounds(self):
        data = await self.call("GET", "/panel/api/inbounds/list")
        obj = data.get("obj") if isinstance(data, dict) else None
        if not isinstance(obj, list):
            raise PanelError("فهرست ورودی‌ها از پنل دریافت نشد.")
        return obj

    async def add_client(self, inbound_id, client):
        # Current 3x-ui API. Fall back to the legacy endpoint for older installs.
        try:
            return await self.call(
                "POST", "/panel/api/clients/add",
                json={"client": client, "inboundIds": [int(inbound_id)]},
            )
        except PanelError as exc:
            if "HTTP 404" not in str(exc):
                raise
        payload = {"id": int(inbound_id), "settings": json.dumps({"clients": [client]}, separators=(",", ":"))}
        return await self.call("POST", "/panel/api/inbounds/addClient", json=payload)

    async def delete_client(self, inbound_id, client_id, email):
        try:
            return await self.call("POST", f"/panel/api/clients/del/{quote(str(email), safe='')}")
        except PanelError as exc:
            if "HTTP 404" not in str(exc):
                raise
        return await self.call("POST", f"/panel/api/inbounds/{int(inbound_id)}/delClient/{quote(str(client_id), safe='')}")

def _json(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            pass
    return {}

def _clients(inbound):
    data = _json(inbound.get("settings"))
    values = data.get("clients", [])
    return values if isinstance(values, list) else []

def _link(inbound, client_id, email):
    protocol = str(inbound.get("protocol", "")).lower()
    if protocol not in {"vless", "vmess"}:
        raise PanelError("در حال حاضر ساخت لینک فقط برای VLESS و VMess فعال است.")
    port = int(inbound.get("port") or 0)
    if not port:
        raise PanelError("پورت ورودی پنل معتبر نیست.")
    stream = _json(inbound.get("streamSettings"))
    network, security = stream.get("network", "tcp"), stream.get("security", "none")
    params = {"type": network, "security": security}
    tls = _json(stream.get("tlsSettings"))
    reality = _json(stream.get("realitySettings"))
    if security == "tls":
        params["sni"] = tls.get("serverName") or ((tls.get("serverNames") or [PUBLIC_HOST])[0])
        params["fp"] = _json(tls.get("settings")).get("fingerprint", "chrome")
    elif security == "reality":
        settings = _json(reality.get("settings"))
        names, ids = reality.get("serverNames") or [], reality.get("shortIds") or []
        params["sni"] = names[0] if names else PUBLIC_HOST
        params["fp"] = settings.get("fingerprint", "chrome")
        if settings.get("publicKey"): params["pbk"] = settings["publicKey"]
        if ids: params["sid"] = ids[0]
        if settings.get("spiderX"): params["spx"] = settings["spiderX"]
    if network == "ws":
        ws = _json(stream.get("wsSettings"))
        if ws.get("path"): params["path"] = ws["path"]
        if (_json(ws.get("headers"))).get("Host"): params["host"] = _json(ws.get("headers"))["Host"]
    elif network == "grpc":
        grpc = _json(stream.get("grpcSettings"))
        if grpc.get("serviceName"): params["serviceName"] = grpc["serviceName"]
    client = next((c for c in _clients(inbound) if str(c.get("id", "")) == str(client_id)), {})
    if protocol == "vless":
        if client.get("flow"): params["flow"] = client["flow"]
        return f"vless://{quote(str(client_id), safe='')}@{PUBLIC_HOST}:{port}?{urlencode(params)}#{quote(email)}"
    data = {"v":"2","ps":email,"add":PUBLIC_HOST,"port":str(port),"id":str(client_id),"aid":"0","scy":"auto","net":network,"type":"none","host":"","path":"","tls":"tls" if security=="tls" else "","sni":params.get("sni","")}
    if network == "ws":
        ws = _json(stream.get("wsSettings"))
        data["path"] = ws.get("path", "")
        data["host"] = _json(ws.get("headers")).get("Host", "")
    return "vmess://" + base64.b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()

def _qr(link):
    code = qrcode.QRCode(box_size=7, border=3)
    code.add_data(link)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()

def register_config_handlers(dp, bot, admin_ids):
    def allowed(uid):
        return uid in admin_ids

    async def panel():
        item = _sessions.get("main")
        if item is None or item.session.closed:
            item = XrayPanel()
            _sessions["main"] = item
        return item

    @dp.message(Command("config"))
    async def config_home(message: Message):
        if not message.from_user or not allowed(message.from_user.id):
            return await message.answer("⛔ این پنل فقط برای مدیر اصلی ربات است.")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ ساخت کانفیگ", callback_data="xray:create")],
            [InlineKeyboardButton(text="📋 فهرست ورودی‌ها", callback_data="xray:inbounds")],
            [InlineKeyboardButton(text="📊 وضعیت پنل", callback_data="xray:status")],
        ])
        await message.answer("🛰️ پنل مدیریت کانفیگ\n\n"
            "ساخت: /confignew <inbound_id> <days> <GB>\n"
            "فهرست کاربران: /configlist <inbound_id>\n"
            "لغو دسترسی: /configrevoke <inbound_id> <client_uuid>", reply_markup=keyboard)

    @dp.callback_query(F.data.startswith("xray:"))
    async def config_callback(callback: CallbackQuery):
        if not allowed(callback.from_user.id):
            return await callback.answer("دسترسی مدیر اصلی لازم است.", show_alert=True)
        action = callback.data.split(":")[1]
        try:
            api = await panel()
            inbounds = await api.inbounds()
            if action in {"status", "inbounds"}:
                active = sum(1 for x in inbounds if x.get("enable", True))
                lines = [f"ID {x.get('id')} | {x.get('protocol')} | پورت {x.get('port')} | {'فعال' if x.get('enable', True) else 'خاموش'}" for x in inbounds[:40]]
                text = f"اتصال برقرار است. ورودی‌ها: {len(inbounds)}، فعال: {active}" if action == "status" else ("\n".join(lines) or "ورودی‌ای پیدا نشد.")
                await callback.message.answer(text)
            elif action == "create":
                choices = [x for x in inbounds if x.get("enable", True) and str(x.get("protocol","")).lower() in {"vless","vmess"}]
                if not choices:
                    await callback.message.answer("ورودی فعال VLESS یا VMess پیدا نشد.")
                else:
                    buttons = [[InlineKeyboardButton(text=f"{x.get('protocol')} :{x.get('port')} (ID {x.get('id')})", callback_data=f"xray:choose:{x.get('id')}")] for x in choices[:30]]
                    await callback.message.answer("ورودی را انتخاب کن؛ سپس دستور پیشنهادی را اجرا کن.", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
            elif action == "choose":
                inbound_id = int(callback.data.split(":")[2])
                await callback.message.answer(f"برای ساخت کانفیگ اجرا کن:\n/confignew {inbound_id} 30 20")
        except Exception as exc:
            log.exception("Xray panel callback failed")
            await callback.message.answer(f"❌ خطا: {str(exc)[:500]}")
        await callback.answer()

    @dp.message(Command("confignew"))
    async def config_new(message: Message):
        if not message.from_user or not allowed(message.from_user.id):
            return await message.answer("⛔ فقط مدیر اصلی ربات می‌تواند کانفیگ بسازد.")
        parts = (message.text or "").split()
        if len(parts) != 4:
            return await message.answer("فرمت: /confignew <inbound_id> <days> <GB>\nمثال: /confignew 1 30 20")
        try:
            inbound_id, days, gb = int(parts[1]), int(parts[2]), float(parts[3])
            if inbound_id < 1 or not 1 <= days <= 3650 or not 0.1 <= gb <= 100000: raise ValueError
        except ValueError:
            return await message.answer("مقادیر نامعتبرند؛ days باید 1 تا 3650 و GB باید 0.1 تا 100000 باشد.")
        try:
            api = await panel()
            inbounds = await api.inbounds()
            inbound = next((x for x in inbounds if int(x.get("id", -1)) == inbound_id), None)
            if not inbound or not inbound.get("enable", True):
                return await message.answer("ورودی پیدا نشد یا غیرفعال است.")
            protocol = str(inbound.get("protocol", "")).lower()
            if protocol not in {"vless", "vmess"}:
                return await message.answer("این ورودی VLESS یا VMess نیست.")
            client_id = str(uuid.uuid4())
            email = f"tg-{message.from_user.id}-{int(time.time())}"
            client = {"id":client_id,"email":email,"enable":True,"totalGB":int(gb*1024**3),
                "expiryTime":int((time.time()+days*86400)*1000),"limitIp":0,
                "tgId":int(message.from_user.id),"subId":uuid.uuid4().hex[:16],"flow":"",
                "comment":"Created by Telegram bot","reset":0,"resetDay":0,"resetMax":0,
                "resetWeekday":0,"security":"none"}
            await api.add_client(inbound_id, client)
            link = _link(inbound, client_id, email)
            await message.answer_photo(BufferedInputFile(_qr(link), filename=f"{email}.png"),
                caption=f"✅ کانفیگ در پنل ثبت شد\nپروتکل: {protocol.upper()}\nحجم: {gb:g} GB\nاعتبار: {days} روز\nشناسه: {email}")
            await message.answer(link)
        except Exception as exc:
            log.exception("Xray client creation failed")
            await message.answer(f"❌ ساخت کانفیگ ناموفق بود: {str(exc)[:500]}")

    @dp.message(Command("configlist"))
    async def config_list(message: Message):
        if not message.from_user or not allowed(message.from_user.id):
            return await message.answer("⛔ فقط مدیر اصلی ربات به این بخش دسترسی دارد.")
        parts = (message.text or "").split()
        if len(parts) != 2 or not parts[1].isdigit():
            return await message.answer("فرمت: /configlist <inbound_id>")
        try:
            api = await panel()
            inbound = next((x for x in await api.inbounds() if int(x.get("id",-1)) == int(parts[1])), None)
            if not inbound: return await message.answer("ورودی پیدا نشد.")
            clients = _clients(inbound)
            if not clients: return await message.answer("کاربری ثبت نشده است.")
            lines = []
            for c in clients[:40]:
                expiry = int(c.get("expiryTime") or 0)
                when = "نامحدود" if not expiry else time.strftime("%Y-%m-%d", time.localtime(expiry/1000))
                lines.append(f"• {c.get('email','?')} | {'فعال' if c.get('enable',True) else 'خاموش'} | {when} | UUID: {c.get('id','-')}")
            await message.answer("\n".join(lines)[:3900])
        except Exception as exc:
            log.exception("Xray client listing failed")
            await message.answer(f"❌ دریافت فهرست ناموفق بود: {str(exc)[:500]}")

    @dp.message(Command("configrevoke"))
    async def config_revoke(message: Message):
        if not message.from_user or not allowed(message.from_user.id):
            return await message.answer("⛔ فقط مدیر اصلی ربات به این بخش دسترسی دارد.")
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) != 3 or not parts[1].isdigit():
            return await message.answer("فرمت: /configrevoke <inbound_id> <client_uuid>")
        try:
            api = await panel()
            inbound = next((x for x in await api.inbounds() if int(x.get("id",-1)) == int(parts[1])), None)
            if not inbound: return await message.answer("ورودی پیدا نشد.")
            client = next((x for x in _clients(inbound) if str(x.get("id","")) == parts[2]), None)
            if not client: return await message.answer("این کاربر در ورودی پیدا نشد.")
            await api.delete_client(int(parts[1]), parts[2], str(client.get("email", parts[2])))
            await message.answer(f"✅ دسترسی {client.get('email',parts[2])} حذف شد.")
        except Exception as exc:
            log.exception("Xray client revoke failed")
            await message.answer(f"❌ حذف دسترسی ناموفق بود: {str(exc)[:500]}")
