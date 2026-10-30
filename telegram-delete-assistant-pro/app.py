import asyncio
import base64
import html
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager, closing
from pathlib import Path
from urllib.parse import parse_qs

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession
import secrets

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
API_ID = int(os.getenv("TELEGRAM_API_ID", "0") or "0")
API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()
SESSION_ENCRYPTION_KEY = os.getenv("SESSION_ENCRYPTION_KEY", "").strip()
DB_PATH = Path(os.getenv("DB_PATH", "/data/bot.sqlite3"))
PORT = int(os.getenv("PORT", "8000"))

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fxi-telegram-automation")
security = HTTPBasic()
bot = None
dp = Dispatcher()
user_client = None
auth_client = None
pending_phone = ""
pending_code_hash = ""
pending_password_needed = False
bot_task = None
scheduler_task = None
client_lock = asyncio.Lock()


def db_connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=25)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with closing(db_connect()) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rules(
          id INTEGER PRIMARY KEY AUTOINCREMENT, trigger_text TEXT NOT NULL,
          response_text TEXT NOT NULL, match_type TEXT NOT NULL DEFAULT 'contains',
          enabled INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS contacts(
          peer_id INTEGER PRIMARY KEY, username TEXT NOT NULL DEFAULT '',
          display_name TEXT NOT NULL DEFAULT '', allowed INTEGER NOT NULL DEFAULT 0,
          updated_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS scheduled_messages(
          id INTEGER PRIMARY KEY AUTOINCREMENT, peer TEXT NOT NULL,
          message TEXT NOT NULL, send_at INTEGER NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS events(
          id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
          detail TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);
        """)
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('automation_enabled','0')")
        db.commit()


def get_setting(key, default=""):
    with closing(db_connect()) as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with closing(db_connect()) as db:
        db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, str(value)))
        db.commit()


def record(kind, detail=""):
    with closing(db_connect()) as db:
        db.execute("INSERT INTO events(kind,detail,created_at) VALUES(?,?,?)",
                   (kind, detail[:240], int(time.time())))
        db.commit()


def encrypt_session(session_string):
    if not SESSION_ENCRYPTION_KEY:
        raise RuntimeError("SESSION_ENCRYPTION_KEY is not configured.")
    return Fernet(SESSION_ENCRYPTION_KEY.encode()).encrypt(session_string.encode()).decode()


def decrypt_session(ciphertext):
    if not SESSION_ENCRYPTION_KEY:
        raise RuntimeError("SESSION_ENCRYPTION_KEY is not configured.")
    try:
        return Fernet(SESSION_ENCRYPTION_KEY.encode()).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Stored Telegram session could not be decrypted. Check SESSION_ENCRYPTION_KEY.") from exc


def save_session(session_string):
    set_setting("account_session_encrypted", encrypt_session(session_string))
    set_setting("account_connected", "1")


def saved_session():
    value = get_setting("account_session_encrypted")
    return decrypt_session(value) if value else ""


def is_admin(user_id):
    return ADMIN_ID > 0 and user_id == ADMIN_ID


def list_rules():
    with closing(db_connect()) as db:
        rows = db.execute("SELECT * FROM rules ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def add_rule(trigger_text, response_text, match_type="contains"):
    trigger_text = trigger_text.strip()
    response_text = response_text.strip()
    if not trigger_text or not response_text:
        raise ValueError("عبارت محرک و پاسخ نباید خالی باشند.")
    if match_type not in ("contains", "exact"):
        match_type = "contains"
    with closing(db_connect()) as db:
        cur = db.execute("INSERT INTO rules(trigger_text,response_text,match_type,enabled,created_at) VALUES(?,?,?,?,?)",
                         (trigger_text, response_text, match_type, 1, int(time.time())))
        db.commit()
        return cur.lastrowid


def page(title, body):
    return HTMLResponse(f"""<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} · FXI</title>
<style>
:root{{color-scheme:dark;--bg:#101713;--card:#1a241e;--line:#34463a;--text:#edf5ed;--muted:#a8b9ab;--accent:#b7d89a}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(ellipse at top,#263a2b 0,#101713 55%);color:var(--text);font:16px/1.8 system-ui,sans-serif}}
main{{max-width:980px;margin:32px auto;padding:0 16px}}header,.card{{background:#1a241eeb;border:1px solid var(--line);border-radius:18px;padding:20px;margin:14px 0}}
h1,h2{{margin-top:0}}h1{{font-size:26px}}p,.muted{{color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}}
label{{display:block;margin:8px 0 4px}}input,textarea,select{{width:100%;padding:11px;border:1px solid #455a49;border-radius:10px;background:#101713;color:var(--text);font:inherit}}
textarea{{min-height:85px}}button,.btn{{display:inline-block;background:var(--accent);color:#122015;border:0;border-radius:10px;padding:10px 16px;margin-top:10px;font-weight:700;cursor:pointer;text-decoration:none}}
button.secondary,.btn.secondary{{background:#2a3a2e;color:var(--text);border:1px solid var(--line)}}.pill{{display:inline-block;border:1px solid var(--line);border-radius:99px;padding:2px 10px;color:var(--accent)}}
.item{{padding:12px 0;border-bottom:1px solid var(--line);overflow-wrap:anywhere}}code{{color:var(--accent)}}a{{color:var(--accent)}}small{{color:var(--muted)}}
</style><main><header><span class="pill">FXI · Telegram Automation</span><h1>{html.escape(title)}</h1>
<p>مدیریت شخصی و کنترل‌شدهٔ قوانین، مخاطب‌ها و پیام‌ها</p><nav><a href="/">داشبورد</a> · <a href="/contacts">مخاطب‌ها</a> · <a href="/rules">قوانین</a> · <a href="/schedule">زمان‌بندی</a> · <a href="/account">اتصال حساب</a></nav></header>{body}</main></html>""")


async def require_admin(request: Request, credentials: HTTPBasicCredentials):
    ok_user = secrets.compare_digest(credentials.username, ADMIN_USER)
    ok_pass = bool(ADMIN_PASSWORD) and secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (ok_user and ok_pass):
        from fastapi.responses import Response
        raise HTTPException(status_code=401, detail="Authentication required",
                            headers={"WWW-Authenticate": "Basic"})


async def authorized(request: Request, credentials: HTTPBasicCredentials = None):
    if credentials is None:
        from fastapi import Depends
        raise HTTPException(status_code=401, detail="Use dashboard authentication")
    await require_admin(request, credentials)


async def start_user_client(session_string):
    global user_client
    async with client_lock:
        if user_client:
            try:
                await user_client.disconnect()
            except Exception:
                pass
            user_client = None
        if not (API_ID and API_HASH):
            log.warning("Telegram API credentials are not configured; personal-account features are disabled.")
            return False
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            set_setting("account_connected", "0")
            return False

        @client.on(events.NewMessage(incoming=True))
        async def on_incoming(event):
            try:
                if not event.is_private or event.sender_id is None:
                    return
                if get_setting("automation_enabled", "0") != "1":
                    return
                with closing(db_connect()) as db:
                    contact = db.execute("SELECT allowed FROM contacts WHERE peer_id=?", (event.sender_id,)).fetchone()
                    rules = db.execute("SELECT * FROM rules WHERE enabled=1 ORDER BY id", ()).fetchall()
                if not contact or not contact["allowed"]:
                    return
                text_in = (event.raw_text or "").strip()
                if not text_in:
                    return
                for rule in rules:
                    trigger = rule["trigger_text"]
                    matched = (text_in.casefold() == trigger.casefold()) if rule["match_type"] == "exact" else (trigger.casefold() in text_in.casefold())
                    if matched:
                        await event.reply(rule["response_text"])
                        record("auto_reply", f"peer={event.sender_id}; rule={rule['id']}")
                        break
            except Exception:
                log.exception("Incoming-message automation failed")

        user_client = client
        await user_client.get_me()
        set_setting("account_connected", "1")
        log.info("Personal Telegram client connected.")
        return True


async def bot_runner():
    global bot
    if not BOT_TOKEN:
        log.warning("BOT_TOKEN missing; Telegram management bot is disabled.")
        return
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    @dp.message(CommandStart())
    async def start_cmd(message: Message):
        if not is_admin(message.from_user.id):
            await message.answer("سلام! این ربات ابزار مدیریت خودکارسازی حساب شخصی است و فقط مدیر تعیین‌شده می‌تواند تنظیمات را تغییر دهد.")
            return
        await message.answer(
            "سلام! پنل مدیریت FXI آماده است.\n\n"
            "از پنل وب برای اتصال امن حساب، انتخاب مخاطب‌ها و تنظیم زمان‌بندی استفاده کن.\n"
            "فرمان‌ها: /status، /rules، /pause، /resume، /help\n"
            "پنل وب: " + os.getenv("PUBLIC_BASE_URL", "آدرس سرویس Render")
        )

    @dp.message(Command("help"))
    async def help_cmd(message: Message):
        if not is_admin(message.from_user.id):
            return
        await message.answer("/status — وضعیت\n/rules — قوانین\n/pause — توقف خودکارسازی\n/resume — فعال‌سازی")

    @dp.message(Command("status"))
    async def status_cmd(message: Message):
        if not is_admin(message.from_user.id):
            return
        state = "روشن" if get_setting("automation_enabled", "0") == "1" else "خاموش"
        connected = "متصل" if get_setting("account_connected", "0") == "1" else "قطع"
        await message.answer(f"خودکارسازی: <b>{state}</b>\nحساب شخصی: <b>{connected}</b>\nقوانین: {len(list_rules())}")

    @dp.message(Command("rules"))
    async def rules_cmd(message: Message):
        if not is_admin(message.from_user.id):
            return
        rules = list_rules()
        if not rules:
            await message.answer("هنوز قانونی ساخته نشده. برای افزودن قانون به پنل وب برو.")
            return
        lines = [f"#{r['id']} · {'روشن' if r['enabled'] else 'خاموش'} · {html.escape(r['trigger_text'][:50])}" for r in rules[:30]]
        await message.answer("\n".join(lines))

    @dp.message(Command("pause"))
    async def pause_cmd(message: Message):
        if is_admin(message.from_user.id):
            set_setting("automation_enabled", "0")
            await message.answer("⏸️ پاسخ‌گویی خودکار متوقف شد.")

    @dp.message(Command("resume"))
    async def resume_cmd(message: Message):
        if is_admin(message.from_user.id):
            if get_setting("account_connected", "0") != "1":
                await message.answer("اول حساب شخصی را از پنل وب متصل کن.")
                return
            set_setting("automation_enabled", "1")
            await message.answer("▶️ پاسخ‌گویی خودکار فعال شد. فقط مخاطب‌های مجاز هدف قرار می‌گیرند.")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


async def scheduler_runner():
    while True:
        try:
            if user_client and user_client.is_connected() and get_setting("automation_enabled", "0") == "1":
                now = int(time.time())
                with closing(db_connect()) as db:
                    due = db.execute("SELECT * FROM scheduled_messages WHERE enabled=1 AND send_at<=? ORDER BY send_at LIMIT 10", (now,)).fetchall()
                for item in due:
                    try:
                        await user_client.send_message(item["peer"], item["message"])
                        with closing(db_connect()) as db:
                            db.execute("UPDATE scheduled_messages SET enabled=0 WHERE id=?", (item["id"],))
                            db.commit()
                        record("scheduled_sent", f"schedule_id={item['id']}")
                    except Exception as exc:
                        log.warning("Scheduled message %s failed: %s", item["id"], type(exc).__name__)
                        with closing(db_connect()) as db:
                            db.execute("UPDATE scheduled_messages SET enabled=0 WHERE id=?", (item["id"],))
                            db.commit()
                        record("scheduled_failed", f"schedule_id={item['id']}; error={type(exc).__name__}")
        except Exception:
            log.exception("Scheduler loop failed")
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot_task, scheduler_task
    init_db()
    if not ADMIN_PASSWORD:
        log.warning("ADMIN_PASSWORD is empty; dashboard authentication is not configured.")
    if not SESSION_ENCRYPTION_KEY:
        log.warning("SESSION_ENCRYPTION_KEY missing; account connection cannot be saved.")
    try:
        session_string = saved_session()
        if session_string:
            await start_user_client(session_string)
    except Exception:
        log.exception("Could not restore personal Telegram session")
    bot_task = asyncio.create_task(bot_runner())
    scheduler_task = asyncio.create_task(scheduler_runner())
    yield
    for task in (bot_task, scheduler_task):
        if task:
            task.cancel()
    if user_client:
        await user_client.disconnect()


app = FastAPI(title="FXI Telegram Automation", lifespan=lifespan)


@app.get("/health", response_class=PlainTextResponse)
async def health():
    return "ok"


@app.middleware("http")
async def dashboard_auth(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    try:
        scheme, encoded = auth.split(" ", 1)
        if scheme.lower() != "basic":
            raise ValueError()
        decoded = base64.b64decode(encoded).decode("utf-8")
        username, password = decoded.split(":", 1)
        valid = secrets.compare_digest(username, ADMIN_USER) and bool(ADMIN_PASSWORD) and secrets.compare_digest(password, ADMIN_PASSWORD)
    except Exception:
        valid = False
    if not valid:
        from starlette.responses import Response
        return Response("Authentication required", status_code=401,
                        headers={"WWW-Authenticate": 'Basic realm="FXI Dashboard"'})
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin:
            expected = f"{request.url.scheme}://{request.url.netloc}"
            if origin.rstrip("/") != expected.rstrip("/"):
                return PlainTextResponse("Cross-origin request rejected", status_code=403)
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    connected = get_setting("account_connected", "0") == "1"
    enabled = get_setting("automation_enabled", "0") == "1"
    with closing(db_connect()) as db:
        contacts = db.execute("SELECT COUNT(*) n FROM contacts WHERE allowed=1").fetchone()["n"]
        pending = db.execute("SELECT COUNT(*) n FROM scheduled_messages WHERE enabled=1").fetchone()["n"]
        events_rows = db.execute("SELECT kind,detail,created_at FROM events ORDER BY id DESC LIMIT 8").fetchall()
    body = f"""
    <section class="grid">
      <div class="card"><h2>حساب شخصی</h2><p>{'متصل' if connected else 'متصل نیست'}</p><a class="btn" href="/account">مدیریت اتصال</a></div>
      <div class="card"><h2>پاسخ خودکار</h2><p>{'روشن' if enabled else 'خاموش'}</p>
        <form method="post" action="/automation/toggle"><button>{'توقف خودکارسازی' if enabled else 'روشن کردن خودکارسازی'}</button></form></div>
      <div class="card"><h2>مخاطب‌های مجاز</h2><p>{contacts} مخاطب</p><a class="btn secondary" href="/contacts">مدیریت مخاطب‌ها</a></div>
      <div class="card"><h2>پیام‌های زمان‌بندی‌شده</h2><p>{pending} مورد در صف</p><a class="btn secondary" href="/schedule">مدیریت زمان‌بندی</a></div>
    </section>
    <section class="card"><h2>آخرین رویدادها</h2>{''.join(f"<div class='item'><b>{html.escape(r['kind'])}</b> · {html.escape(r['detail'])}<br><small>{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['created_at']))}</small></div>" for r in events_rows) or '<p>هنوز رویدادی ثبت نشده.</p>'}</section>
    <section class="card"><p>ایمنی پیش‌فرض: پیام خودکار فقط برای مخاطب‌هایی ارسال می‌شود که خودت در فهرست مجاز کرده‌ای. ارسال انبوه وجود ندارد.</p></section>"""
    return page("داشبورد", body)


@app.post("/automation/toggle")
async def toggle_automation():
    new = "0" if get_setting("automation_enabled", "0") == "1" else "1"
    if new == "1" and get_setting("account_connected", "0") != "1":
        return page("حساب متصل نیست", '<section class="card"><p>برای فعال‌سازی، ابتدا حساب شخصی را متصل کن.</p><a class="btn" href="/account">اتصال حساب</a></section>')
    set_setting("automation_enabled", new)
    record("automation_toggle", new)
    return RedirectResponse("/", status_code=303)


@app.get("/account", response_class=HTMLResponse)
async def account_page():
    api_ready = bool(API_ID and API_HASH and SESSION_ENCRYPTION_KEY)
    connected = get_setting("account_connected", "0") == "1"
    body = f"""
    <section class="card"><h2>وضعیت اتصال</h2><p>{'حساب متصل است' if connected else 'حسابی متصل نیست'}</p>
    <p>{'تنظیمات API و رمزگذاری حاضر است.' if api_ready else 'برای فعال‌کردن این بخش، TELEGRAM_API_ID، TELEGRAM_API_HASH و SESSION_ENCRYPTION_KEY را در تنظیمات سرویس وارد کن.'}</p>
    <p>کد ورود در این صفحه وارد می‌شود، نه در چت ربات. کد یا رمز دومرحله‌ای را برای هیچ شخصی ارسال نکن. اتصال فقط برای حسابی است که مالک آن هستی.</p></section>
    <section class="card"><h2>مرحله ۱ · ارسال کد ورود</h2><form method="post" action="/account/send-code">
    <label>شماره تلفن با کد کشور</label><input name="phone" placeholder="+49..." required autocomplete="tel">
    <button {'disabled' if not api_ready else ''}>ارسال کد</button></form></section>
    <section class="card"><h2>مرحله ۲ · تأیید کد</h2><form method="post" action="/account/verify-code">
    <label>کد دریافت‌شده از تلگرام</label><input name="code" inputmode="numeric" autocomplete="one-time-code" required>
    <button {'disabled' if not api_ready else ''}>تأیید و اتصال</button></form></section>
    <section class="card"><h2>اگر رمز دومرحله‌ای درخواست شد</h2><form method="post" action="/account/verify-password">
    <label>رمز دومرحله‌ای</label><input name="password" type="password" autocomplete="current-password" required>
    <button {'disabled' if not api_ready else ''}>تأیید رمز</button></form></section>
    <section class="card"><form method="post" action="/account/disconnect"><button class="secondary">قطع اتصال و حذف نشست ذخیره‌شده</button></form></section>"""
    return page("اتصال حساب شخصی", body)


async def parse_form(request: Request):
    raw = (await request.body()).decode("utf-8", errors="replace")
    return {key: values[-1] for key, values in parse_qs(raw).items()}


@app.post("/account/send-code")
async def send_code(request: Request):
    global auth_client, pending_phone, pending_code_hash, pending_password_needed
    form = await parse_form(request)
    phone = form.get("phone", "").strip()
    if not (API_ID and API_HASH and SESSION_ENCRYPTION_KEY):
        return page("تنظیمات ناقص", '<section class="card">ابتدا TELEGRAM_API_ID، TELEGRAM_API_HASH و SESSION_ENCRYPTION_KEY را تنظیم کن.</section>')
    if not phone.startswith("+") or len(phone) < 8 or len(phone) > 20:
        return page("شماره نامعتبر", '<section class="card">شماره را همراه کد کشور وارد کن؛ نمونه: +49...</section>')
    try:
        if auth_client:
            await auth_client.disconnect()
        auth_client = TelegramClient(StringSession(), API_ID, API_HASH)
        await auth_client.connect()
        sent = await auth_client.send_code_request(phone)
        pending_phone = phone
        pending_code_hash = sent.phone_code_hash
        pending_password_needed = False
        record("login_code_requested", "phone redacted")
        return page("کد ارسال شد", '<section class="card"><p>اگر شماره درست باشد، تلگرام کد ورود را ارسال می‌کند. کد را در مرحلهٔ دوم وارد کن.</p><a class="btn" href="/account">ادامه</a></section>')
    except Exception as exc:
        log.warning("Telegram login code request failed: %s", type(exc).__name__)
        return page("ارسال کد ناموفق", '<section class="card"><p>ارسال کد انجام نشد. تنظیمات API، شماره و محدودیت‌های تلگرام را بررسی کن. جزئیات حساس عمداً در صفحه نمایش داده نمی‌شود.</p><a href="/account">بازگشت</a></section>')


@app.post("/account/verify-code")
async def verify_code(request: Request):
    global auth_client, pending_password_needed
    form = await parse_form(request)
    code = "".join(ch for ch in form.get("code", "") if ch.isdigit())
    if not auth_client or not pending_phone or not pending_code_hash or not code:
        return page("فرایند ورود آماده نیست", '<section class="card"><p>ابتدا کد را درخواست کن.</p><a href="/account">بازگشت</a></section>')
    try:
        await auth_client.sign_in(phone=pending_phone, code=code, phone_code_hash=pending_code_hash)
        await finalize_login()
        return page("حساب متصل شد", '<section class="card"><p>حساب با موفقیت متصل شد و نشست به‌صورت رمزگذاری‌شده ذخیره شد.</p><a class="btn" href="/">رفتن به داشبورد</a></section>')
    except SessionPasswordNeededError:
        pending_password_needed = True
        return page("رمز دومرحله‌ای لازم است", '<section class="card"><p>حساب تأیید دومرحله‌ای دارد. رمز را در فرم مخصوص همین پنل وارد کن.</p><a class="btn" href="/account">ادامه</a></section>')
    except Exception as exc:
        log.warning("Telegram code verification failed: %s", type(exc).__name__)
        return page("تأیید انجام نشد", '<section class="card"><p>کد نادرست یا منقضی شده است. دوباره کد درخواست کن و آن را در این پنل وارد کن.</p><a href="/account">بازگشت</a></section>')


@app.post("/account/verify-password")
async def verify_password(request: Request):
    global auth_client, pending_password_needed
    form = await parse_form(request)
    password = form.get("password", "")
    if not auth_client or not pending_password_needed or not password:
        return page("فرایند ورود آماده نیست", '<section class="card"><p>ابتدا کد ورود را تأیید کن.</p><a href="/account">بازگشت</a></section>')
    try:
        await auth_client.sign_in(password=password)
        await finalize_login()
        return page("حساب متصل شد", '<section class="card"><p>حساب با موفقیت متصل شد و نشست به‌صورت رمزگذاری‌شده ذخیره شد.</p><a class="btn" href="/">رفتن به داشبورد</a></section>')
    except Exception as exc:
        log.warning("Telegram 2FA verification failed: %s", type(exc).__name__)
        return page("رمز تأیید نشد", '<section class="card"><p>رمز نادرست است یا تلگرام ورود را نپذیرفت. دوباره تلاش کن.</p><a href="/account">بازگشت</a></section>')


async def finalize_login():
    global auth_client, pending_phone, pending_code_hash, pending_password_needed
    session_string = auth_client.session.save()
    save_session(session_string)
    await auth_client.disconnect()
    auth_client = None
    pending_phone = ""
    pending_code_hash = ""
    pending_password_needed = False
    await start_user_client(session_string)
    record("account_connected", "Telegram personal account")


@app.post("/account/disconnect")
async def disconnect_account():
    global user_client, auth_client, pending_phone, pending_code_hash, pending_password_needed
    if user_client:
        await user_client.disconnect()
        user_client = None
    if auth_client:
        await auth_client.disconnect()
        auth_client = None
    pending_phone = ""
    pending_code_hash = ""
    pending_password_needed = False
    set_setting("account_session_encrypted", "")
    set_setting("account_connected", "0")
    set_setting("automation_enabled", "0")
    record("account_disconnected", "session deleted")
    return RedirectResponse("/account", status_code=303)


@app.get("/rules", response_class=HTMLResponse)
async def rules_page():
    rows = list_rules()
    items = []
    for r in rows:
        items.append(f"""<div class="item"><b>#{r['id']} · {html.escape(r['trigger_text'])}</b> · {'روشن' if r['enabled'] else 'خاموش'} · {r['match_type']}
        <p>{html.escape(r['response_text'])}</p><form method="post" action="/rules/{r['id']}/toggle" style="display:inline"><button class="secondary">{'خاموش کردن' if r['enabled'] else 'روشن کردن'}</button></form>
        <form method="post" action="/rules/{r['id']}/delete" style="display:inline"><button class="secondary">حذف</button></form></div>""")
    body = f"""<section class="card"><h2>ساخت قانون جدید</h2><form method="post" action="/rules/add">
    <label>عبارت محرک</label><input name="trigger_text" required maxlength="250">
    <label>پاسخ</label><textarea name="response_text" required maxlength="3000"></textarea>
    <label>نوع تطبیق</label><select name="match_type"><option value="contains">شامل عبارت</option><option value="exact">تطبیق دقیق</option></select>
    <button>ذخیره قانون</button></form></section><section class="card"><h2>قوانین فعلی</h2>{''.join(items) or '<p>قانونی ثبت نشده.</p>'}</section>"""
    return page("مدیریت قوانین", body)


@app.post("/rules/add")
async def rules_add(request: Request):
    form = await parse_form(request)
    try:
        rule_id = add_rule(form.get("trigger_text", ""), form.get("response_text", ""), form.get("match_type", "contains"))
        record("rule_added", f"rule_id={rule_id}")
    except ValueError as exc:
        return page("خطا", f'<section class="card">{html.escape(str(exc))}</section>')
    return RedirectResponse("/rules", status_code=303)


@app.post("/rules/{rule_id}/toggle")
async def rule_toggle(rule_id: int):
    with closing(db_connect()) as db:
        row = db.execute("SELECT enabled FROM rules WHERE id=?", (rule_id,)).fetchone()
        if row:
            db.execute("UPDATE rules SET enabled=? WHERE id=?", (0 if row["enabled"] else 1, rule_id))
            db.commit()
    return RedirectResponse("/rules", status_code=303)


@app.post("/rules/{rule_id}/delete")
async def rule_delete(rule_id: int):
    with closing(db_connect()) as db:
        db.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        db.commit()
    record("rule_deleted", f"rule_id={rule_id}")
    return RedirectResponse("/rules", status_code=303)


@app.get("/contacts", response_class=HTMLResponse)
async def contacts_page():
    with closing(db_connect()) as db:
        rows = db.execute("SELECT * FROM contacts ORDER BY allowed DESC, display_name COLLATE NOCASE LIMIT 300").fetchall()
    items = []
    for c in rows:
        label = html.escape(c["display_name"] or c["username"] or str(c["peer_id"]))
        username = f" @{html.escape(c['username'])}" if c["username"] else ""
        items.append(f"""<div class="item"><b>{label}</b>{username} · ID <code>{c['peer_id']}</code> · {'مجاز' if c['allowed'] else 'غیرفعال'}
        <form method="post" action="/contacts/{c['peer_id']}/toggle"><button class="secondary">{'غیرفعال کردن' if c['allowed'] else 'مجاز کردن'}</button></form></div>""")
    body = f"""<section class="card"><p>مخاطب‌ها از حساب متصل‌شده دریافت می‌شوند. پیش‌فرض همه غیرفعال‌اند؛ فقط مخاطب‌هایی که خودت مجاز کنی پاسخ خودکار می‌گیرند.</p>
    <form method="post" action="/contacts/sync"><button>همگام‌سازی مخاطب‌ها</button></form></section>
    <section class="card"><h2>فهرست مخاطب‌ها</h2>{''.join(items) or '<p>هنوز مخاطبی همگام‌سازی نشده.</p>'}</section>"""
    return page("مخاطب‌ها", body)


@app.post("/contacts/sync")
async def contacts_sync():
    if not user_client or not user_client.is_connected():
        return page("حساب متصل نیست", '<section class="card">ابتدا حساب شخصی را متصل کن.</section>')
    count = 0
    async for dialog in user_client.iter_dialogs(limit=500):
        entity = dialog.entity
        if getattr(entity, "bot", False) or not getattr(entity, "id", None):
            continue
        if getattr(entity, "id", 0) == (await user_client.get_me()).id:
            continue
        username = getattr(entity, "username", "") or ""
        first = getattr(entity, "first_name", "") or ""
        last = getattr(entity, "last_name", "") or ""
        title = getattr(entity, "title", "") or ""
        name = (first + " " + last).strip() or title or username or str(entity.id)
        with closing(db_connect()) as db:
            db.execute("INSERT INTO contacts(peer_id,username,display_name,allowed,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(peer_id) DO UPDATE SET username=excluded.username,display_name=excluded.display_name,updated_at=excluded.updated_at",
                       (entity.id, username, name, 0, int(time.time())))
            db.commit()
        count += 1
    record("contacts_synced", f"count={count}")
    return page("همگام‌سازی انجام شد", f'<section class="card"><p>{count} مخاطب/گفت‌وگو بررسی شد. برای فعال‌سازی پاسخ خودکار، مخاطب‌های مجاز را جداگانه انتخاب کن.</p><a class="btn" href="/contacts">دیدن فهرست</a></section>')


@app.post("/contacts/{peer_id}/toggle")
async def contact_toggle(peer_id: int):
    with closing(db_connect()) as db:
        row = db.execute("SELECT allowed FROM contacts WHERE peer_id=?", (peer_id,)).fetchone()
        if row:
            db.execute("UPDATE contacts SET allowed=?,updated_at=? WHERE peer_id=?",
                       (0 if row["allowed"] else 1, int(time.time()), peer_id))
            db.commit()
    record("contact_permission_changed", f"peer_id={peer_id}")
    return RedirectResponse("/contacts", status_code=303)


@app.get("/schedule", response_class=HTMLResponse)
async def schedule_page():
    with closing(db_connect()) as db:
        rows = db.execute("SELECT * FROM scheduled_messages ORDER BY enabled DESC,send_at DESC LIMIT 100").fetchall()
    items = []
    for r in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["send_at"]))
        items.append(f"<div class='item'><b>#{r['id']} · {html.escape(r['peer'])}</b> · {when} · {'در صف' if r['enabled'] else 'تمام‌شده/غیرفعال'}<p>{html.escape(r['message'])}</p></div>")
    body = f"""<section class="card"><h2>زمان‌بندی پیام</h2><p>هر پیام فقط به یک مخاطب مشخص فرستاده می‌شود. تاریخ و ساعت را با منطقهٔ زمانی UTC وارد کن تا از ابهام منطقهٔ زمانی جلوگیری شود.</p>
    <form method="post" action="/schedule/add"><label>شناسه یا نام کاربری مخاطب</label><input name="peer" placeholder="@username یا شناسه" required>
    <label>متن پیام</label><textarea name="message" required maxlength="3000"></textarea>
    <label>زمان ارسال (UTC)</label><input name="send_at" type="datetime-local" required>
    <button>ثبت زمان‌بندی</button></form></section><section class="card"><h2>پیام‌های ثبت‌شده</h2>{''.join(items) or '<p>موردی در صف نیست.</p>'}</section>"""
    return page("زمان‌بندی پیام‌ها", body)


@app.post("/schedule/add")
async def schedule_add(request: Request):
    from datetime import datetime, timezone
    form = await parse_form(request)
    peer_input = form.get("peer", "").strip()
    message = form.get("message", "").strip()
    date_value = form.get("send_at", "").strip()
    try:
        if not peer_input or not message or len(message) > 3000:
            raise ValueError()
        if not user_client or not user_client.is_connected():
            return page("حساب متصل نیست", '<section class="card">ابتدا حساب شخصی را متصل کن.</section>')
        entity = await user_client.get_entity(peer_input)
        peer_id = int(entity.id)
        with closing(db_connect()) as db:
            allowed = db.execute("SELECT allowed FROM contacts WHERE peer_id=?", (peer_id,)).fetchone()
        if not allowed or not allowed["allowed"]:
            return page("مخاطب مجاز نیست", '<section class="card">ابتدا مخاطب را در بخش مخاطب‌ها همگام‌سازی و به‌صورت دستی مجاز کن.</section>')
        parsed = datetime.fromisoformat(date_value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        send_at = int(parsed.timestamp())
        if send_at < int(time.time()) + 30:
            return page("زمان نامعتبر", '<section class="card">زمان ارسال باید حداقل ۳۰ ثانیه در آینده باشد.</section>')
        with closing(db_connect()) as db:
            db.execute("INSERT INTO scheduled_messages(peer,message,send_at,enabled,created_at) VALUES(?,?,?,?,?)",
                       (str(peer_id), message, send_at, 1, int(time.time())))
            db.commit()
        record("schedule_added", f"peer_id={peer_id}")
    except Exception:
        return page("اطلاعات نامعتبر", '<section class="card">مخاطب، متن و زمان را بررسی کن. تاریخ باید معتبر باشد.</section>')
    return RedirectResponse("/schedule", status_code=303)
