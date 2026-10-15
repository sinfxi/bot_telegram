import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
DB_PATH = os.getenv("DATABASE_PATH", "/data/bot.db")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("independent_bot")
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("PRAGMA journal_mode=WAL")
db.executescript("""
CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY,
  username TEXT,
  full_name TEXT NOT NULL,
  joined_at TEXT NOT NULL,
  last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS pending_reports(user_id INTEGER PRIMARY KEY);
""")
db.commit()
bot = Bot(TOKEN)
dp = Dispatcher()

def now():
    return datetime.now(timezone.utc).isoformat()

def home_keyboard(user_id: int):
    rows = [
        [InlineKeyboardButton(text="👤 پروفایل من", callback_data="profile"),
         InlineKeyboardButton(text="🧰 امکانات", callback_data="features")],
        [InlineKeyboardButton(text="📝 ارسال پیشنهاد یا گزارش", callback_data="report"),
         InlineKeyboardButton(text="ℹ️ راهنما", callback_data="help")],
    ]
    if user_id in ADMIN_IDS:
        rows.append([InlineKeyboardButton(text="🛠 مدیریت", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.message(CommandStart())
async def start(message: Message):
    u = message.from_user
    if not u:
        return
    stamp = now()
    db.execute("""INSERT INTO users(user_id,username,full_name,joined_at,last_seen)
        VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
        username=excluded.username, full_name=excluded.full_name, last_seen=excluded.last_seen""",
        (u.id, u.username, u.full_name, stamp, stamp))
    db.commit()
    await message.answer(f"سلام {u.first_name or 'دوست من'}! 👋\n\nبه ربات خوش اومدی. از منوی زیر شروع کن:",
                         reply_markup=home_keyboard(u.id))

@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer("برای استفاده از امکانات، /start رو بزن و از منوی تعاملی انتخاب کن.")

@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    u = call.from_user
    row = db.execute("SELECT joined_at FROM users WHERE user_id=?", (u.id,)).fetchone()
    count = db.execute("SELECT COUNT(*) FROM reports WHERE user_id=?", (u.id,)).fetchone()[0]
    joined = row[0][:10] if row else "نامشخص"
    await call.message.edit_text(
        f"👤 پروفایل شما\n\nشناسه: {u.id}\nنام کاربری: @{u.username or 'ندارد'}\nتاریخ عضویت: {joined}\nگزارش‌های ثبت‌شده: {count}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ منوی اصلی", callback_data="home")]]))
    await call.answer()

@dp.callback_query(F.data == "features")
async def features(call: CallbackQuery):
    await call.message.edit_text(
        "🧰 امکانات فعلی\n\n• پروفایل کاربری\n• ثبت پیشنهاد و گزارش\n• پنل مدیریت محدود به مدیران\n• آمار پایه کاربران\n\nقابلیت‌های بیشتر را می‌توان به‌صورت ماژولار اضافه کرد.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ منوی اصلی", callback_data="home")]]))
    await call.answer()

@dp.callback_query(F.data == "help")
async def help_menu(call: CallbackQuery):
    await call.message.edit_text(
        "ℹ️ راهنما\n\nاز دکمه‌های منو استفاده کن. برای ثبت گزارش، گزینهٔ «ارسال پیشنهاد یا گزارش» را بزن و سپس متن را ارسال کن.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ منوی اصلی", callback_data="home")]]))
    await call.answer()

@dp.callback_query(F.data == "report")
async def report_prompt(call: CallbackQuery):
    db.execute("INSERT OR REPLACE INTO pending_reports(user_id) VALUES(?)", (call.from_user.id,))
    db.commit()
    await call.message.answer("متن پیشنهاد یا گزارش را در یک پیام بفرست. برای لغو، /cancel را ارسال کن.")
    await call.answer()

@dp.message(Command("cancel"))
async def cancel_report(message: Message):
    db.execute("DELETE FROM pending_reports WHERE user_id=?", (message.from_user.id,))
    db.commit()
    await message.answer("عملیات لغو شد.")

@dp.message(F.text)
async def capture_report(message: Message):
    u = message.from_user
    if not u or message.text.startswith("/"):
        return
    pending = db.execute("SELECT 1 FROM pending_reports WHERE user_id=?", (u.id,)).fetchone()
    if not pending:
        return
    report_text = message.text.strip()
    if len(report_text) < 3:
        await message.answer("لطفاً متن کمی کامل‌تر بفرست.")
        return
    db.execute("INSERT INTO reports(user_id,message,created_at) VALUES(?,?,?)", (u.id, report_text[:3000], now()))
    db.execute("DELETE FROM pending_reports WHERE user_id=?", (u.id,))
    db.commit()
    await message.answer("✅ گزارش شما ثبت شد. ممنون که اطلاع دادی!")
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"📝 گزارش جدید از {u.full_name} (ID: {u.id})\n\n{report_text[:3000]}")
        except Exception:
            log.exception("Could not notify admin %s", admin_id)

@dp.callback_query(F.data == "admin")
async def admin_panel(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("دسترسی ندارید.", show_alert=True)
        return
    users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    reports = db.execute("SELECT COUNT(*) FROM reports WHERE status='open'").fetchone()[0]
    await call.message.edit_text(
        f"🛠 پنل مدیریت\n\n👥 کاربران ثبت‌شده: {users}\n📝 گزارش‌های باز: {reports}\n\nبرای دریافت آمار با دستور /stats اقدام کن.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ منوی اصلی", callback_data="home")]]))
    await call.answer()

@dp.message(Command("stats"))
async def stats(message: Message):
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ این دستور مخصوص مدیر است.")
        return
    users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    reports = db.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    await message.answer(f"📊 آمار ربات\nکاربران: {users}\nکل گزارش‌ها: {reports}")

@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    await call.message.edit_text("منوی اصلی 👇", reply_markup=home_keyboard(call.from_user.id))
    await call.answer()

async def health(request):
    return web.json_response({"status": "ok", "service": "telegram-bot"})

async def main():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("Health endpoint listening on port %s", port)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()
        await bot.session.close()
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
