import asyncio
import html
import logging
import os
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager, closing
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
DB_PATH = Path(os.getenv("DB_PATH", "/data/bot.sqlite3"))
PORT = int(os.getenv("PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("conversation-automation")

if not ADMIN_PASSWORD:
    raise RuntimeError("Set a strong ADMIN_PASSWORD environment variable.")
if ADMIN_ID <= 0:
    log.warning("ADMIN_ID is not configured; owner-only rule management will be unavailable.")

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with closing(connect()) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            response TEXT NOT NULL,
            match_type TEXT NOT NULL DEFAULT 'contains',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_seen INTEGER NOT NULL,
            last_seen INTEGER NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_type TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_rules_enabled ON rules(enabled);
        CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
        """)
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('automation_enabled','1')")
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('fallback_response','پیامت رسید 🌱 اگر پاسخ آماده‌ای برای آن تعریف شده باشد، همین‌جا نمایش داده می‌شود.')")
        db.commit()

def setting(key, default=""):
    with closing(connect()) as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def set_setting(key, value):
    with closing(connect()) as db:
        db.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        db.commit()

def add_event(user_id, event_type, detail=""):
    with closing(connect()) as db:
        db.execute(
            "INSERT INTO events(user_id,event_type,detail,created_at) VALUES(?,?,?,?)",
            (user_id, event_type, detail[:180], int(time.time())),
        )
        db.commit()

def register_user(user_id):
    now = int(time.time())
    with closing(connect()) as db:
        db.execute("""
        INSERT INTO users(user_id,first_seen,last_seen,message_count)
        VALUES(?,?,?,1)
        ON CONFLICT(user_id) DO UPDATE SET
          last_seen=excluded.last_seen,
          message_count=users.message_count+1
        """, (user_id, now, now))
        db.commit()

def list_rules(enabled_only=False):
    with closing(connect()) as db:
        if enabled_only:
            rows = db.execute("SELECT * FROM rules WHERE enabled=1 ORDER BY id").fetchall()
        else:
            rows = db.execute("SELECT * FROM rules ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]

def create_rule(keyword, response, match_type="contains"):
    with closing(connect()) as db:
        cur = db.execute(
            "INSERT INTO rules(keyword,response,match_type,enabled,created_at) VALUES(?,?,?,?,?)",
            (keyword.strip(), response.strip(), match_type, 1, int(time.time())),
        )
        db.commit()
        return cur.lastrowid

def update_rule(rule_id, **fields):
    allowed = {"enabled"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    assignments = ", ".join(f"{k}=?" for k in fields)
    with closing(connect()) as db:
        db.execute(f"UPDATE rules SET {assignments} WHERE id=?", (*fields.values(), rule_id))
        db.commit()

def delete_rule(rule_id):
    with closing(connect()) as db:
        db.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        db.commit()

def find_response(text):
    normalized = text.casefold().strip()
    for rule in list_rules(enabled_only=True):
        keyword = rule["keyword"].casefold().strip()
        if not keyword:
            continue
        matched = normalized == keyword if rule["match_type"] == "exact" else keyword in normalized
        if matched:
            return rule
    return None

def stats():
    today = int(time.time()) // 86400 * 86400
    with closing(connect()) as db:
        users = db.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        active = db.execute("SELECT COUNT(*) n FROM users WHERE last_seen>=?", (today,)).fetchone()["n"]
        messages = db.execute("SELECT COALESCE(SUM(message_count),0) n FROM users").fetchone()["n"]
        events = db.execute(
            "SELECT event_type,COUNT(*) n FROM events WHERE created_at>=? GROUP BY event_type",
            (today,),
        ).fetchall()
    return users, active, messages, {r["event_type"]: r["n"] for r in events}

class RuleWizard(StatesGroup):
    keyword = State()
    response = State()
    match_type = State()

bot = None
if BOT_TOKEN:
    try:
        bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    except Exception:
        log.exception("BOT_TOKEN could not initialize; Telegram polling is disabled.")
else:
    log.warning("BOT_TOKEN is not set; only the health/dashboard web service can run.")

dp = Dispatcher(storage=MemoryStorage())

def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)

def home_keyboard(is_admin=False):
    rows = [
        [InlineKeyboardButton(text="⚡ وضعیت خودکارسازی", callback_data="automation:status")],
        [InlineKeyboardButton(text="🧪 آزمایش پاسخ", callback_data="automation:test")],
        [InlineKeyboardButton(text="❓ راهنما", callback_data="help")],
    ]
    if is_admin:
        rows.insert(1, [InlineKeyboardButton(text="🧩 قوانین پاسخ", callback_data="rules:list")])
        rows.insert(2, [InlineKeyboardButton(text="➕ ساخت قانون", callback_data="rules:add")])
        rows.append([InlineKeyboardButton(text="📊 آمار", callback_data="stats")])
    return kb(rows)

def is_admin(user_id):
    return ADMIN_ID > 0 and user_id == ADMIN_ID

def owner_only(message_or_callback):
    user = message_or_callback.from_user
    return is_admin(user.id)

HOME_TEXT = (
    "<b>⚡ دستیار خودکارسازی گفت‌وگو</b>\n\n"
    "قوانین پاسخ‌گویی تعریف کن تا ربات هنگام دریافت پیام، پاسخ مناسب را به‌صورت خودکار ارسال کند.\n\n"
    "• پاسخ بر اساس کلمه یا عبارت\n"
    "• تطبیق دقیق یا وجود عبارت در متن\n"
    "• روشن/خاموش کردن خودکارسازی\n"
    "• مدیریت قوانین و آمار\n\n"
    "<b>محدودیت مهم:</b> ربات فقط پیام‌هایی را می‌بیند که به خودِ ربات ارسال شده‌اند. "
    "با Bot API نمی‌تواند پیام‌های خصوصی اکانت شخصی یا گفت‌وگوهای دیگر ربات‌ها را بخواند."
)

async def show(target, text, markup=None):
    if isinstance(target, CallbackQuery):
        await target.answer()
        try:
            await target.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                await target.message.answer(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)

def rules_text():
    rules = list_rules()
    if not rules:
        return "هنوز قانونی ساخته نشده. روی «ساخت قانون» بزن."
    lines = ["<b>🧩 قوانین پاسخ‌گویی</b>"]
    for r in rules[:30]:
        status = "🟢" if r["enabled"] else "⚪"
        mode = "دقیق" if r["match_type"] == "exact" else "شامل عبارت"
        keyword = html.escape(r["keyword"][:60])
        response = html.escape(r["response"][:90])
        lines.append(f"\n{status} <b>#{r['id']}</b> · {mode}\n🔎 {keyword}\n💬 {response}")
    return "\n".join(lines)

def rules_keyboard():
    rows = [[InlineKeyboardButton(text="➕ قانون جدید", callback_data="rules:add")]]
    for r in list_rules()[:20]:
        state = "خاموش" if r["enabled"] else "روشن"
        rows.append([
            InlineKeyboardButton(text=f"#{r['id']} {'🟢' if r['enabled'] else '⚪'}", callback_data=f"rules:view:{r['id']}"),
            InlineKeyboardButton(text=f"⏻ {state}", callback_data=f"rules:toggle:{r['id']}"),
            InlineKeyboardButton(text="🗑", callback_data=f"rules:delete:{r['id']}"),
        ])
    rows.append([InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="home")])
    return kb(rows)

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    register_user(message.from_user.id)
    add_event(message.from_user.id, "start")
    await message.answer(HOME_TEXT, reply_markup=home_keyboard(is_admin(message.from_user.id)))

@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "<b>راهنمای ربات</b>\n"
        "/start — منوی اصلی\n/cancel — لغو ساخت قانون\n"
        "/status — وضعیت خودکارسازی\n"
        "/rules — فهرست قوانین (مدیر)\n/add — ساخت قانون (مدیر)\n"
        "/pause و /resume — توقف/فعال‌سازی (مدیر)\n/stats — آمار (مدیر)"
    )

@dp.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("عملیات لغو شد.", reply_markup=home_keyboard(is_admin(message.from_user.id)))

@dp.message(Command("status"))
async def status_command(message: Message):
    status = "🟢 روشن" if setting("automation_enabled", "1") == "1" else "🔴 خاموش"
    await message.answer(f"وضعیت خودکارسازی: <b>{status}</b>")

@dp.message(Command("pause"))
async def pause_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ این فرمان فقط برای مدیر ربات است.")
        return
    set_setting("automation_enabled", "0")
    add_event(message.from_user.id, "automation_paused")
    await message.answer("🔴 خودکارسازی متوقف شد. قوانین ذخیره شده‌اند.")

@dp.message(Command("resume"))
async def resume_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ این فرمان فقط برای مدیر ربات است.")
        return
    set_setting("automation_enabled", "1")
    add_event(message.from_user.id, "automation_resumed")
    await message.answer("🟢 خودکارسازی دوباره فعال شد.")

@dp.message(Command("rules"))
async def rules_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ فقط مدیر می‌تواند قوانین را مدیریت کند.")
        return
    await message.answer(rules_text(), reply_markup=rules_keyboard())

@dp.message(Command("add"))
async def add_command(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ فقط مدیر می‌تواند قانون بسازد.")
        return
    await state.set_state(RuleWizard.keyword)
    await message.answer("🔎 عبارت یا کلمه‌ای را بفرست که باید شناسایی شود. برای لغو /cancel را بزن.")

@dp.message(Command("stats"))
async def stats_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ اجازه دسترسی نداری.")
        return
    users, active, messages, today_events = stats()
    await message.answer(
        "<b>📊 آمار خودکارسازی</b>\n"
        f"کاربران ثبت‌شده: {users}\nفعال امروز: {active}\n"
        f"کل پیام‌های دریافتی: {messages}\n"
        f"پاسخ‌های خودکار امروز: {today_events.get('auto_reply', 0)}\n"
        f"آزمایش پاسخ امروز: {today_events.get('test', 0)}"
    )

@dp.callback_query(F.data == "home")
async def home_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(callback, HOME_TEXT, home_keyboard(is_admin(callback.from_user.id)))

@dp.callback_query(F.data == "automation:status")
async def automation_status(callback: CallbackQuery):
    enabled = setting("automation_enabled", "1") == "1"
    text = "🟢 خودکارسازی روشن است." if enabled else "🔴 خودکارسازی خاموش است."
    if is_admin(callback.from_user.id):
        text += "\n\nاز /pause برای توقف و /resume برای فعال‌سازی استفاده کن."
    await show(callback, text, home_keyboard(is_admin(callback.from_user.id)))

@dp.callback_query(F.data == "automation:test")
async def automation_test(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("🧪 متن آزمایشی را بفرست تا بررسی کنم کدام قانون با آن مطابقت دارد.")
    add_event(callback.from_user.id, "test_prompt")

@dp.callback_query(F.data == "rules:list")
async def rules_list_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی مدیر لازم است.", show_alert=True)
        return
    await show(callback, rules_text(), rules_keyboard())

@dp.callback_query(F.data == "rules:add")
async def rules_add_callback(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی مدیر لازم است.", show_alert=True)
        return
    await state.set_state(RuleWizard.keyword)
    await show(callback, "🔎 عبارت یا کلمه‌ای را بفرست که باید شناسایی شود. برای لغو /cancel را بزن.")

@dp.message(RuleWizard.keyword)
async def rule_keyword(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        await message.answer("⛔ دسترسی مدیر لازم است.")
        return
    keyword = (message.text or "").strip()
    if not keyword or len(keyword) > 100:
        await message.answer("عبارت باید بین 1 تا 100 نویسه باشد. دوباره بفرست.")
        return
    await state.update_data(keyword=keyword)
    await state.set_state(RuleWizard.response)
    await message.answer("💬 حالا پاسخ خودکار را بفرست (حداکثر 3500 نویسه).")

@dp.message(RuleWizard.response)
async def rule_response(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        await message.answer("⛔ دسترسی مدیر لازم است.")
        return
    response = (message.text or "").strip()
    if not response or len(response) > 3500:
        await message.answer("پاسخ باید بین 1 تا 3500 نویسه باشد. دوباره بفرست.")
        return
    await state.update_data(response=response)
    await state.set_state(RuleWizard.match_type)
    await message.answer(
        "نوع تطبیق را انتخاب کن:",
        reply_markup=kb([
            [InlineKeyboardButton(text="🔍 شامل عبارت", callback_data="rules:mode:contains")],
            [InlineKeyboardButton(text="🎯 تطبیق دقیق", callback_data="rules:mode:exact")],
            [InlineKeyboardButton(text="❌ لغو", callback_data="rules:cancel")],
        ]),
    )

@dp.callback_query(F.data.startswith("rules:mode:"))
async def rule_mode(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی مدیر لازم است.", show_alert=True)
        return
    mode = callback.data.rsplit(":", 1)[-1]
    if mode not in {"contains", "exact"}:
        await callback.answer("حالت نامعتبر است.", show_alert=True)
        return
    data = await state.get_data()
    if not data.get("keyword") or not data.get("response"):
        await state.clear()
        await show(callback, "فرایند ساخت قانون منقضی شد؛ دوباره تلاش کن.")
        return
    rule_id = create_rule(data["keyword"], data["response"], mode)
    await state.clear()
    add_event(callback.from_user.id, "rule_created", str(rule_id))
    await show(callback, f"✅ قانون #{rule_id} ساخته و فعال شد.", rules_keyboard())

@dp.callback_query(F.data == "rules:cancel")
async def rule_cancel_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(callback, "ساخت قانون لغو شد.", home_keyboard(is_admin(callback.from_user.id)))

@dp.callback_query(F.data.startswith("rules:view:"))
async def rule_view(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی مدیر لازم است.", show_alert=True)
        return
    rule_id = int(callback.data.rsplit(":", 1)[-1])
    rule = next((r for r in list_rules() if r["id"] == rule_id), None)
    if not rule:
        await show(callback, "این قانون پیدا نشد.", rules_keyboard())
        return
    mode = "تطبیق دقیق" if rule["match_type"] == "exact" else "شامل عبارت"
    await show(
        callback,
        f"<b>قانون #{rule_id}</b>\nوضعیت: {'روشن' if rule['enabled'] else 'خاموش'}\n"
        f"حالت: {mode}\nعبارت: {html.escape(rule['keyword'])}\n"
        f"پاسخ:\n{html.escape(rule['response'])}",
        rules_keyboard(),
    )

@dp.callback_query(F.data.startswith("rules:toggle:"))
async def rule_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی مدیر لازم است.", show_alert=True)
        return
    rule_id = int(callback.data.rsplit(":", 1)[-1])
    rule = next((r for r in list_rules() if r["id"] == rule_id), None)
    if rule:
        update_rule(rule_id, enabled=0 if rule["enabled"] else 1)
        add_event(callback.from_user.id, "rule_toggled", str(rule_id))
    await show(callback, rules_text(), rules_keyboard())

@dp.callback_query(F.data.startswith("rules:delete:"))
async def rule_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی مدیر لازم است.", show_alert=True)
        return
    rule_id = int(callback.data.rsplit(":", 1)[-1])
    delete_rule(rule_id)
    add_event(callback.from_user.id, "rule_deleted", str(rule_id))
    await show(callback, "🗑 قانون حذف شد.\n\n" + rules_text(), rules_keyboard())

@dp.callback_query(F.data == "stats")
async def stats_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی مدیر لازم است.", show_alert=True)
        return
    users, active, messages, today_events = stats()
    await show(
        callback,
        f"<b>📊 آمار</b>\nکاربران: {users}\nفعال امروز: {active}\n"
        f"پیام‌های دریافتی: {messages}\nپاسخ‌های خودکار امروز: {today_events.get('auto_reply', 0)}",
        home_keyboard(True),
    )

@dp.message(RuleWizard.match_type)
async def ignore_while_mode(message: Message):
    await message.answer("از دکمه‌های نوع تطبیق استفاده کن یا /cancel را بزن.")

@dp.message()
async def automatic_reply(message: Message, state: FSMContext):
    if not message.from_user or message.from_user.is_bot:
        return
    if await state.get_state():
        return
    register_user(message.from_user.id)
    text = (message.text or message.caption or "").strip()
    if not text:
        await message.answer("فعلاً فقط پیام‌های متنی را پردازش می‌کنم.")
        return
    if setting("automation_enabled", "1") != "1":
        await message.answer("⏸ خودکارسازی موقتاً متوقف است.")
        return
    rule = find_response(text)
    if rule:
        add_event(message.from_user.id, "auto_reply", str(rule["id"]))
        await message.answer(html.escape(rule["response"]))
    else:
        fallback = setting("fallback_response", "")
        if fallback:
            await message.answer(fallback)

auth = HTTPBasic()

def admin_auth(credentials: HTTPBasicCredentials = Depends(auth)):
    if not (
        secrets.compare_digest(credentials.username, ADMIN_USER)
        and secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

async def bot_runner():
    if bot is None:
        log.error("Bot polling disabled: configure a valid BOT_TOKEN in the host environment.")
        return
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        log.info("Starting Telegram conversation automation polling.")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Telegram polling stopped unexpectedly.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(bot_runner()) if bot is not None else None
    app.state.bot_task = task
    yield
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if bot is not None:
        await bot.session.close()

app = FastAPI(title="Telegram Conversation Automation", lifespan=lifespan)

@app.get("/health", response_class=PlainTextResponse)
async def health():
    return "ok"

@app.get("/", response_class=HTMLResponse)
async def dashboard(_: str = Depends(admin_auth)):
    users, active, messages, today_events = stats()
    enabled = setting("automation_enabled", "1") == "1"
    status = "روشن 🟢" if enabled else "خاموش 🔴"
    rules = list_rules()
    def render_rule_row(rule):
        mode = "دقیق" if rule["match_type"] == "exact" else "شامل عبارت"
        status = "روشن" if rule["enabled"] else "خاموش"
        return "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            rule["id"], html.escape(rule["keyword"]), mode, status, html.escape(rule["response"][:300])
        )
    table_rows = "".join(render_rule_row(rule) for rule in rules)
    body = f"""
    <!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>پنل خودکارسازی گفت‌وگو</title>
    <style>
    *{{box-sizing:border-box}}body{{margin:0;background:#101713;color:#f1f5ef;font-family:Tahoma,Arial,sans-serif}}
    main{{max-width:1000px;margin:40px auto;padding:20px}}h1{{font-size:28px}}p{{color:#c2cec4}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px}}
    .card{{background:#1b2720;border:1px solid #35483a;border-radius:16px;padding:20px}}
    .value{{font-size:25px;font-weight:bold;margin-top:12px;color:#c9e6a7}}
    table{{width:100%;border-collapse:collapse;margin-top:16px;background:#1b2720;border-radius:14px;overflow:hidden}}
    th,td{{text-align:right;padding:12px;border-bottom:1px solid #35483a;vertical-align:top}}th{{color:#c9e6a7}}
    .muted{{font-size:13px;color:#aab8ad}}@media(max-width:600px){{main{{margin:10px auto;padding:12px}}h1{{font-size:22px}}}}
    </style><main><h1>⚡ پنل خودکارسازی گفت‌وگو</h1>
    <p>وضعیت: <b>{status}</b> · این پنل گزارش می‌دهد؛ مدیریت قوانین از داخل تلگرام انجام می‌شود.</p>
    <section class="grid">
      <div class="card">کاربران ثبت‌شده<div class="value">{users}</div></div>
      <div class="card">فعال امروز<div class="value">{active}</div></div>
      <div class="card">کل پیام‌ها<div class="value">{messages}</div></div>
      <div class="card">پاسخ‌های امروز<div class="value">{today_events.get('auto_reply', 0)}</div></div>
    </section><h2>قوانین پاسخ‌گویی</h2>
    <table><thead><tr><th>شناسه</th><th>عبارت</th><th>نوع</th><th>وضعیت</th><th>پاسخ</th></tr></thead><tbody>
    {table_rows}
    </tbody></table><p class="muted">این سرویس فقط پیام‌های ارسال‌شده به خود ربات را پردازش می‌کند. اطلاعات محرمانه یا کدهای ورود را برای ربات ارسال نکنید.</p>
    </main></html>
    """
    return HTMLResponse(body)

@app.get("/ready", response_class=PlainTextResponse)
async def ready():
    return "ready" if bot is not None else "web-ready; BOT_TOKEN missing or invalid"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=PORT)
