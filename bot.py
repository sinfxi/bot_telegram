import os, asyncio, sqlite3, logging
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiohttp import web
TOKEN=os.environ.get("BOT_TOKEN"); ADMIN_IDS={int(x) for x in os.environ.get("ADMIN_IDS","").replace(" ","").split(",") if x}; DB=os.environ.get("DB_PATH","bot.db")
if not TOKEN: raise RuntimeError("BOT_TOKEN is required")
logging.basicConfig(level=logging.INFO); conn=sqlite3.connect(DB,check_same_thread=False)
conn.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT,first_name TEXT,joined TEXT)"); conn.commit()
bot=Bot(TOKEN); dp=Dispatcher()
def save_user(m):
    conn.execute("INSERT OR IGNORE INTO users VALUES(?,?,?,?)",(m.from_user.id,m.from_user.username,m.from_user.first_name,datetime.utcnow().isoformat())); conn.execute("UPDATE users SET username=?,first_name=? WHERE id=?",(m.from_user.username,m.from_user.first_name,m.from_user.id)); conn.commit()
def admin(uid): return uid in ADMIN_IDS
def kb(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 آمار",callback_data="stats"),InlineKeyboardButton(text="📢 همگانی",callback_data="broadcast")],[InlineKeyboardButton(text="👥 کاربران",callback_data="users"),InlineKeyboardButton(text="ℹ️ وضعیت",callback_data="status")]])
@dp.message(CommandStart())
async def start(m):
    save_user(m); await m.answer("🛠 پنل مدیریت" if admin(m.from_user.id) else "سلام 👋\nربات آماده است.",reply_markup=kb() if admin(m.from_user.id) else None)
@dp.message(Command("help"))
async def help(m): save_user(m); await m.answer("🤖 مدیریت کاربران، آمار، ارسال همگانی و اجرای 24/7 روی Railway.")
@dp.message(Command("admin"))
async def adm(m):
    save_user(m); await m.answer("🛠 پنل مدیریت",reply_markup=kb()) if admin(m.from_user.id) else await m.answer("⛔ دسترسی ندارید.")
@dp.callback_query(F.data.in_({"stats","users","status"}))
async def panel(c):
    if not admin(c.from_user.id): return await c.answer("⛔",show_alert=True)
    if c.data=="stats": t=f"📊 کاربران: {conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]}"
    elif c.data=="users":
        r=conn.execute("SELECT id,username,first_name FROM users ORDER BY id DESC LIMIT 20").fetchall(); t="👥 کاربران:\n"+"\n".join(f"{i+1}. {n or '-'} @{u or '-'} | {uid}" for i,(uid,u,n) in enumerate(r))
    else: t="🟢 فعال\n⚙️ Long polling\n💾 SQLite"
    await c.message.edit_text(t,reply_markup=kb()); await c.answer()
waiting=set()
@dp.callback_query(F.data=="broadcast")
async def bc(c):
    if not admin(c.from_user.id): return await c.answer("⛔",show_alert=True)
    waiting.add(c.from_user.id); await c.message.answer("📢 پیام همگانی را بفرست. /cancel"); await c.answer()
@dp.message(Command("cancel"))
async def cancel(m): waiting.discard(m.from_user.id); await m.answer("لغو شد.")
@dp.message()
async def allmsg(m):
    save_user(m)
    if admin(m.from_user.id) and m.from_user.id in waiting:
        waiting.discard(m.from_user.id); ok=bad=0
        for (uid,) in conn.execute("SELECT id FROM users").fetchall():
            try: await bot.copy_message(uid,m.chat.id,m.message_id); ok+=1
            except: bad+=1
            await asyncio.sleep(.04)
        await m.answer(f"✅ موفق: {ok}\n❌ ناموفق: {bad}")
async def health(r): return web.Response(text="OK")
async def main():
    app=web.Application(); app.router.add_get("/",health); app.router.add_get("/health",health); runner=web.AppRunner(app); await runner.setup(); await web.TCPSite(runner,"0.0.0.0",int(os.environ.get("PORT","8080"))).start(); await dp.start_polling(bot)
if __name__=="__main__": asyncio.run(main())
