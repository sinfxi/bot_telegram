import asyncio
import os
import sqlite3
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "6384557276"))
DB_PATH = os.getenv("DB_PATH", "requests.db")
if not TOKEN:
    raise RuntimeError("Set BOT_TOKEN in Railway Variables; do not store it in source code.")

bot = Bot(TOKEN)
dp = Dispatcher()

def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect() as con:
        con.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, username TEXT, first_seen TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, uid TEXT NOT NULL, region TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL)")

def menu(admin=False):
    b = InlineKeyboardBuilder()
    b.button(text="🎮 ثبت درخواست لایک", callback_data="new")
    b.button(text="📋 درخواست‌های من", callback_data="mine")
    b.button(text="ℹ️ راهنما", callback_data="help")
    if admin: b.button(text="🛠 پنل مدیریت", callback_data="admin")
    b.adjust(1)
    return b.as_markup()

def admin_menu():
    b = InlineKeyboardBuilder()
    b.button(text="📊 آمار", callback_data="stats")
    b.button(text="🕒 درخواست‌های در انتظار", callback_data="pending")
    b.button(text="⬅️ منوی اصلی", callback_data="home")
    b.adjust(1)
    return b.as_markup()

@dp.message(CommandStart())
async def start(m: Message):
    with connect() as con:
        con.execute("INSERT INTO users VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
                    (m.from_user.id, m.from_user.username or "", datetime.now(timezone.utc).isoformat()))
    await m.answer("سلام! 👋\nبه ربات ثبت درخواست خدمات Free Fire خوش اومدی.\n\nدرخواستت رو از منو ثبت کن. اجرای واقعی لایک به API معتبر نیاز داره.",
                   reply_markup=menu(m.from_user.id == ADMIN_ID))

@dp.callback_query(F.data == "home")
async def home(c: CallbackQuery):
    await c.message.answer("منوی اصلی:", reply_markup=menu(c.from_user.id == ADMIN_ID))
    await c.answer()

@dp.callback_query(F.data == "help")
async def help_page(c: CallbackQuery):
    await c.message.answer("راهنما:\n۱) ثبت درخواست را بزن.\n۲) UID و ریجن را مثل این بفرست:\n123456789 / ME\n۳) وضعیت را از درخواست‌های من ببین.\n\nاین نسخه درخواست را مدیریت می‌کند؛ برای اجرای خودکار لایک باید API مجاز متصل شود.",
                           reply_markup=menu(c.from_user.id == ADMIN_ID))
    await c.answer()

@dp.callback_query(F.data == "new")
async def new_request(c: CallbackQuery):
    await c.message.answer("UID و Region را در یک پیام بفرست؛ نمونه:\n123456789 / ME")
    await c.answer()

@dp.message(F.text.regexp(r"^\s*\d{5,20}\s*/\s*[A-Za-z0-9_-]{2,12}\s*$"))
async def submit(m: Message):
    uid, region = [x.strip() for x in m.text.split("/", 1)]
    with connect() as con:
        cur = con.execute("INSERT INTO requests(user_id,uid,region,created_at) VALUES(?,?,?,?)",
                          (m.from_user.id, uid, region.upper(), datetime.now(timezone.utc).isoformat()))
        rid = cur.lastrowid
    await m.answer("✅ درخواست #" + str(rid) + " ثبت شد.\nUID: " + uid + "\nRegion: " + region.upper() + "\nوضعیت: در انتظار بررسی",
                   reply_markup=menu(m.from_user.id == ADMIN_ID))
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ تأیید", callback_data="approve:" + str(rid)),
            InlineKeyboardButton(text="❌ رد", callback_data="reject:" + str(rid))
        ]])
        await bot.send_message(ADMIN_ID, "🆕 درخواست #" + str(rid) + "\nکاربر: " + str(m.from_user.id) + "\nUID: " + uid + "\nRegion: " + region.upper(), reply_markup=kb)
    except Exception:
        pass

@dp.callback_query(F.data == "mine")
async def mine(c: CallbackQuery):
    with connect() as con:
        rows = con.execute("SELECT id,uid,region,status FROM requests WHERE user_id=? ORDER BY id DESC LIMIT 10", (c.from_user.id,)).fetchall()
    labels = {"pending":"در انتظار", "approved":"تأیید شده", "rejected":"رد شده"}
    text = "\n".join("#" + str(r["id"]) + " · UID " + r["uid"] + " · " + r["region"] + " · " + labels.get(r["status"], r["status"]) for r in rows)
    await c.message.answer(text or "هنوز درخواستی ثبت نکردی.", reply_markup=menu(c.from_user.id == ADMIN_ID))
    await c.answer()

@dp.callback_query(F.data == "admin")
@dp.callback_query(F.data == "stats")
async def stats(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        await c.answer("دسترسی ندارید.", show_alert=True); return
    with connect() as con:
        users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total = con.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        pending = con.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0]
        approved = con.execute("SELECT COUNT(*) FROM requests WHERE status='approved'").fetchone()[0]
    await c.message.answer("🛠 پنل مدیریت\n\n📊 کاربران: " + str(users) + "\nکل درخواست‌ها: " + str(total) + "\nدر انتظار: " + str(pending) + "\nتأییدشده: " + str(approved), reply_markup=admin_menu())
    await c.answer()

@dp.callback_query(F.data == "pending")
async def pending(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        await c.answer("دسترسی ندارید.", show_alert=True); return
    with connect() as con:
        rows = con.execute("SELECT id,user_id,uid,region FROM requests WHERE status='pending' ORDER BY id LIMIT 15").fetchall()
    if not rows: await c.message.answer("درخواستی در انتظار نیست.", reply_markup=admin_menu())
    for r in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ تأیید", callback_data="approve:" + str(r["id"])),
            InlineKeyboardButton(text="❌ رد", callback_data="reject:" + str(r["id"]))
        ]])
        await c.message.answer("#" + str(r["id"]) + " · کاربر " + str(r["user_id"]) + " · UID " + r["uid"] + " · " + r["region"], reply_markup=kb)
    await c.answer()

@dp.callback_query(F.data.startswith("approve:"))
@dp.callback_query(F.data.startswith("reject:"))
async def decide(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        await c.answer("دسترسی ندارید.", show_alert=True); return
    action, rid = c.data.split(":", 1)
    status = "approved" if action == "approve" else "rejected"
    with connect() as con:
        row = con.execute("SELECT user_id FROM requests WHERE id=?", (int(rid),)).fetchone()
        if row: con.execute("UPDATE requests SET status=? WHERE id=?", (status, int(rid)))
    if not row:
        await c.answer("درخواست پیدا نشد.", show_alert=True); return
    try: await bot.send_message(row["user_id"], "وضعیت درخواست #" + rid + ": " + ("تأیید شد." if status == "approved" else "رد شد."))
    except Exception: pass
    await c.message.edit_reply_markup(reply_markup=None)
    await c.answer("وضعیت به‌روزرسانی شد.")

@dp.message(Command("admin"))
async def admin_command(m: Message):
    if m.from_user.id != ADMIN_ID:
        await m.answer("دسترسی ندارید."); return
    await m.answer("پنل مدیریت", reply_markup=admin_menu())

@dp.message()
async def fallback(m: Message):
    await m.answer("برای ثبت درخواست، UID و Region را این‌طور بفرست:\n123456789 / ME", reply_markup=menu(m.from_user.id == ADMIN_ID))

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
