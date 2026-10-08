import os, asyncio, sqlite3, logging, time
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, ChatPermissions
)
from aiogram.enums import ChatMemberStatus
from aiohttp import web

TOKEN = os.getenv("BOT_TOKEN")
ADM = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is required")

logging.basicConfig(level=logging.INFO)
db = sqlite3.connect(os.getenv("DB_PATH", "bot.db"), check_same_thread=False)
db.execute("PRAGMA journal_mode=WAL")
db.executescript("""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT, name TEXT, joined TEXT);
CREATE TABLE IF NOT EXISTS filters(chat INTEGER, word TEXT, PRIMARY KEY(chat,word));
CREATE TABLE IF NOT EXISTS settings(
    chat INTEGER PRIMARY KEY,
    welcome INTEGER DEFAULT 1,
    antilink INTEGER DEFAULT 0,
    antispam INTEGER DEFAULT 0,
    captcha INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS warnings(chat INTEGER, user INTEGER, count INTEGER, PRIMARY KEY(chat,user));
CREATE TABLE IF NOT EXISTS spam(chat INTEGER, user INTEGER, last REAL, count INTEGER, PRIMARY KEY(chat,user));
CREATE TABLE IF NOT EXISTS notes(chat INTEGER, name TEXT, text TEXT, PRIMARY KEY(chat,name));
CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT, chat INTEGER, admin INTEGER, action TEXT, target INTEGER, created TEXT);
CREATE TABLE IF NOT EXISTS pending_captcha(chat INTEGER, user INTEGER, created REAL, PRIMARY KEY(chat,user));
CREATE TABLE IF NOT EXISTS mutes(chat INTEGER, user INTEGER, until REAL, PRIMARY KEY(chat,user));
""")
for col, typ in [("welcome","INTEGER DEFAULT 1"),("antilink","INTEGER DEFAULT 0"),("antispam","INTEGER DEFAULT 0"),("captcha","INTEGER DEFAULT 0")]:
    try:
        db.execute(f"ALTER TABLE settings ADD COLUMN {col} {typ}")
    except sqlite3.OperationalError:
        pass
db.commit()

bot = Bot(TOKEN)
dp = Dispatcher()
pending = set()

def save(m):
    u = m.from_user
    if not u:
        return
    db.execute(
        "INSERT OR IGNORE INTO users VALUES(?,?,?,?)",
        (u.id, u.username, u.full_name, datetime.utcnow().isoformat())
    )
    db.execute(
        "UPDATE users SET username=?,name=? WHERE id=?",
        (u.username, u.full_name, u.id)
    )
    db.commit()

def is_global_admin(uid):
    return uid in ADM

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 آمار", callback_data="stats"),
            InlineKeyboardButton(text="👥 کاربران", callback_data="users")
        ],
        [
            InlineKeyboardButton(text="🛡 امنیت", callback_data="security"),
            InlineKeyboardButton(text="📝 امکانات", callback_data="features")
        ],
        [
            InlineKeyboardButton(text="📜 لاگ‌ها", callback_data="logs"),
            InlineKeyboardButton(text="📢 همگانی", callback_data="bc")
        ]
    ])

async def group_admin(m):
    if m.chat.type == "private":
        await m.answer("این دستور داخل گروه است.")
        return False
    if is_global_admin(m.from_user.id):
        return True
    try:
        x = await bot.get_chat_member(m.chat.id, m.from_user.id)
        if x.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
            return True
    except Exception:
        pass
    await m.answer("⛔ فقط ادمین گروه.")
    return False

def target(m):
    return m.reply_to_message.from_user if m.reply_to_message else None

def log_action(chat, admin_id, action, target_id=0):
    db.execute(
        "INSERT INTO logs(chat,admin,action,target,created) VALUES(?,?,?,?,?)",
        (chat, admin_id, action, target_id, datetime.utcnow().isoformat())
    )
    db.commit()

def ensure_settings(chat):
    db.execute("INSERT OR IGNORE INTO settings(chat) VALUES(?)", (chat,))
    db.commit()

def toggle_value(chat, field):
    ensure_settings(chat)
    row = db.execute(f"SELECT {field} FROM settings WHERE chat=?", (chat,)).fetchone()
    return bool(row[0]) if row else False

async def mute_user(chat_id, user_id, minutes=60):
    until = datetime.utcnow() + timedelta(minutes=minutes)
    await bot.restrict_chat_member(
        chat_id, user_id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=until
    )
    db.execute(
        "INSERT OR REPLACE INTO mutes VALUES(?,?,?)",
        (chat_id, user_id, until.timestamp())
    )
    db.commit()

@dp.message(CommandStart())
async def start(m):
    save(m)
    text = "🛠 پنل مدیریت آماده است." if is_global_admin(m.from_user.id) else "🤖 ربات همه‌کاره آماده است. /help"
    await m.answer(text, reply_markup=menu() if is_global_admin(m.from_user.id) else None)

@dp.message(Command("help"))
async def help_cmd(m):
    await m.answer("""🤖 ربات همه‌کاره V2

🛡 مدیریت:
 /ban /unban /mute /unmute /promote /demote
 /del /pin /warn /warnings /clearwarn

🔐 امنیت:
 /antilink on|off
 /antispam on|off
 /captcha on|off
 /filter کلمه
 /unfilter کلمه
 /filters

👋 گروه:
 /welcome on|off
 /rules

📝 ابزار:
 /note نام متن
 /getnote نام
 /notes
 /id

👑 ادمین:
 /admin /broadcast /cancel""")

@dp.message(Command("id"))
async def ident(m):
    await m.answer(f"🆔 User: {m.from_user.id}\n💬 Chat: {m.chat.id}")

@dp.message(Command("admin"))
async def admin_cmd(m):
    if not is_global_admin(m.from_user.id):
        return await m.answer("⛔ دسترسی ندارید.")
    await m.answer("🛠 پنل مدیریت V2", reply_markup=menu())

@dp.message(Command("ban"))
async def ban(m):
    if not await group_admin(m): return
    u = target(m)
    if not u: return await m.answer("کاربر را ریپلای کن.")
    try:
        await bot.ban_chat_member(m.chat.id, u.id)
        log_action(m.chat.id, m.from_user.id, "ban", u.id)
        await m.answer(f"🚫 {u.full_name} مسدود شد.")
    except Exception as e:
        await m.answer(f"❌ {e}")

@dp.message(Command("unban"))
async def unban(m):
    if not await group_admin(m): return
    u = target(m)
    if not u: return await m.answer("کاربر را ریپلای کن.")
    try:
        await bot.unban_chat_member(m.chat.id, u.id, only_if_banned=True)
        log_action(m.chat.id, m.from_user.id, "unban", u.id)
        await m.answer("✅ رفع مسدودی شد.")
    except Exception as e:
        await m.answer(f"❌ {e}")

@dp.message(Command("mute"))
async def mute(m):
    if not await group_admin(m): return
    u = target(m)
    if not u: return await m.answer("کاربر را ریپلای کن.")
    minutes = 60
    parts = (m.text or "").split()
    if len(parts) > 1 and parts[1].isdigit():
        minutes = max(1, min(int(parts[1]), 10080))
    try:
        await mute_user(m.chat.id, u.id, minutes)
        log_action(m.chat.id, m.from_user.id, f"mute {minutes}m", u.id)
        await m.answer(f"🔇 {u.full_name} برای {minutes} دقیقه ساکت شد.")
    except Exception as e:
        await m.answer(f"❌ {e}")

@dp.message(Command("unmute"))
async def unmute(m):
    if not await group_admin(m): return
    u = target(m)
    if not u: return await m.answer("کاربر را ریپلای کن.")
    try:
        await bot.restrict_chat_member(
            m.chat.id, u.id,
            permissions=ChatPermissions(can_send_messages=True)
        )
        db.execute("DELETE FROM mutes WHERE chat=? AND user=?", (m.chat.id, u.id))
        db.commit()
        log_action(m.chat.id, m.from_user.id, "unmute", u.id)
        await m.answer("🔊 رفع سکوت شد.")
    except Exception as e:
        await m.answer(f"❌ {e}")

@dp.message(Command("del"))
async def delete_cmd(m):
    if not await group_admin(m): return
    if not m.reply_to_message: return await m.answer("پیام را ریپلای کن.")
    try:
        await m.reply_to_message.delete()
        await m.delete()
    except Exception:
        pass

@dp.message(Command("pin"))
async def pin_cmd(m):
    if not await group_admin(m): return
    if not m.reply_to_message: return await m.answer("پیام را ریپلای کن.")
    try:
        await m.reply_to_message.pin()
        log_action(m.chat.id, m.from_user.id, "pin", m.reply_to_message.from_user.id if m.reply_to_message.from_user else 0)
        await m.answer("📌 سنجاق شد.")
    except Exception as e:
        await m.answer(f"❌ {e}")

@dp.message(Command("warn"))
async def warn(m):
    if not await group_admin(m): return
    u = target(m)
    if not u: return await m.answer("کاربر را ریپلای کن.")
    row = db.execute("SELECT count FROM warnings WHERE chat=? AND user=?", (m.chat.id, u.id)).fetchone()
    n = (row[0] if row else 0) + 1
    db.execute("INSERT OR REPLACE INTO warnings VALUES(?,?,?)", (m.chat.id, u.id, n))
    db.commit()
    log_action(m.chat.id, m.from_user.id, f"warn {n}", u.id)
    if n >= 3:
        try:
            await mute_user(m.chat.id, u.id, 60)
        except Exception:
            pass
        await m.answer(f"🔴 {u.full_name}: اخطار {n}/3 — یک ساعت محدود شد.")
    else:
        await m.answer(f"⚠️ {u.full_name}: اخطار {n}/3")

@dp.message(Command("warnings"))
async def warnings(m):
    u = target(m) or m.from_user
    row = db.execute("SELECT count FROM warnings WHERE chat=? AND user=?", (m.chat.id, u.id)).fetchone()
    await m.answer(f"⚠️ اخطارهای {u.full_name}: {row[0] if row else 0}/3")

@dp.message(Command("clearwarn"))
async def clearwarn(m):
    if not await group_admin(m): return
    u = target(m)
    if not u: return await m.answer("کاربر را ریپلای کن.")
    db.execute("DELETE FROM warnings WHERE chat=? AND user=?", (m.chat.id, u.id))
    db.commit()
    log_action(m.chat.id, m.from_user.id, "clearwarn", u.id)
    await m.answer("✅ اخطارهای کاربر پاک شد.")

@dp.message(Command("promote"))
async def promote(m):
    if not await group_admin(m): return
    u = target(m)
    if not u: return await m.answer("کاربر را ریپلای کن.")
    try:
        await bot.promote_chat_member(
            m.chat.id, u.id,
            can_manage_chat=True, can_delete_messages=True,
            can_restrict_members=True, can_pin_messages=True
        )
        log_action(m.chat.id, m.from_user.id, "promote", u.id)
        await m.answer("👑 کاربر ادمین شد.")
    except Exception as e:
        await m.answer(f"❌ {e}")

@dp.message(Command("demote"))
async def demote(m):
    if not await group_admin(m): return
    u = target(m)
    if not u: return await m.answer("کاربر را ریپلای کن.")
    try:
        await bot.promote_chat_member(
            m.chat.id, u.id,
            can_manage_chat=False, can_delete_messages=False,
            can_restrict_members=False, can_pin_messages=False
        )
        log_action(m.chat.id, m.from_user.id, "demote", u.id)
        await m.answer("✅ دسترسی‌های مدیریتی حذف شد.")
    except Exception as e:
        await m.answer(f"❌ {e}")

async def setting_command(m, field, title):
    if not await group_admin(m): return
    parts = (m.text or "").split(maxsplit=1)
    value = parts[1].lower() if len(parts) > 1 else ""
    if value not in ("on", "off"):
        return await m.answer(f"/{field} on یا /{field} off")
    ensure_settings(m.chat.id)
    db.execute(f"UPDATE settings SET {field}=? WHERE chat=?", (value == "on", m.chat.id))
    db.commit()
    log_action(m.chat.id, m.from_user.id, f"{field} {value}")
    await m.answer(f"{title} " + ("فعال شد." if value == "on" else "خاموش شد."))

@dp.message(Command("antilink"))
async def antilink(m):
    await setting_command(m, "antilink", "🔗 ضدلینک")

@dp.message(Command("antispam"))
async def antispam(m):
    await setting_command(m, "antispam", "🛡 ضداسپم")

@dp.message(Command("captcha"))
async def captcha(m):
    await setting_command(m, "captcha", "🧩 کپچا")

@dp.message(Command("filter"))
async def add_filter(m):
    if not await group_admin(m): return
    p = (m.text or "").split(maxsplit=1)
    if len(p) < 2: return await m.answer("مثال: /filter کلمه")
    word = p[1].lower().strip()
    db.execute("INSERT OR IGNORE INTO filters VALUES(?,?)", (m.chat.id, word))
    db.commit()
    log_action(m.chat.id, m.from_user.id, f"filter + {word}")
    await m.answer("✅ فیلتر اضافه شد.")

@dp.message(Command("unfilter"))
async def rem_filter(m):
    if not await group_admin(m): return
    p = (m.text or "").split(maxsplit=1)
    if len(p) < 2: return await m.answer("مثال: /unfilter کلمه")
    db.execute("DELETE FROM filters WHERE chat=? AND word=?", (m.chat.id, p[1].lower().strip()))
    db.commit()
    log_action(m.chat.id, m.from_user.id, "filter -")
    await m.answer("✅ فیلتر حذف شد.")

@dp.message(Command("filters"))
async def filters(m):
    r = db.execute("SELECT word FROM filters WHERE chat=? ORDER BY word", (m.chat.id,)).fetchall()
    await m.answer("🔎 فیلترها:\n" + ("\n".join("• " + x[0] for x in r) or "خالی"))

@dp.message(Command("welcome"))
async def welcome(m):
    await setting_command(m, "welcome", "👋 خوشامد")

@dp.message(Command("rules"))
async def rules(m):
    await m.answer("📜 قوانین گروه:\n1) احترام متقابل\n2) بدون اسپم و فلود\n3) تبلیغ بدون اجازه ممنوع\n4) لینک مشکوک ممنوع")

@dp.message(Command("note"))
async def note(m):
    if not await group_admin(m): return
    p = (m.text or "").split(maxsplit=2)
    if len(p) < 3: return await m.answer("مثال: /note قوانین متن قوانین")
    db.execute("INSERT OR REPLACE INTO notes VALUES(?,?,?)", (m.chat.id, p[1].lower(), p[2]))
    db.commit()
    await m.answer("📝 یادداشت ذخیره شد.")

@dp.message(Command("getnote"))
async def getnote(m):
    p = (m.text or "").split(maxsplit=1)
    if len(p) < 2: return await m.answer("مثال: /getnote قوانین")
    r = db.execute("SELECT text FROM notes WHERE chat=? AND name=?", (m.chat.id, p[1].lower())).fetchone()
    await m.answer(r[0] if r else "❌ یادداشت پیدا نشد.")

@dp.message(Command("notes"))
async def notes(m):
    r = db.execute("SELECT name FROM notes WHERE chat=? ORDER BY name", (m.chat.id,)).fetchall()
    await m.answer("📝 یادداشت‌ها:\n" + ("\n".join("• " + x[0] for x in r) or "خالی"))

@dp.message(F.new_chat_members)
async def new_members(m):
    save(m)
    enabled = toggle_value(m.chat.id, "captcha")
    welcome_on = toggle_value(m.chat.id, "welcome")
    for u in m.new_chat_members:
        if enabled and not u.is_bot:
            try:
                await bot.restrict_chat_member(
                    m.chat.id, u.id,
                    permissions=ChatPermissions(can_send_messages=False)
                )
                db.execute(
                    "INSERT OR REPLACE INTO pending_captcha VALUES(?,?,?)",
                    (m.chat.id, u.id, time.time())
                )
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="✅ من ربات نیستم",
                        callback_data=f"cap:{m.chat.id}:{u.id}"
                    )
                ]])
                await m.answer(f"🧩 {u.full_name} برای ورود باید تأیید شود.", reply_markup=kb)
            except Exception:
                pass
        elif welcome_on:
            await m.answer(f"👋 خوش آمدی {u.full_name}!")
    db.commit()

@dp.callback_query(F.data.startswith("cap:"))
async def captcha_callback(c):
    try:
        _, chat, user = c.data.split(":")
        chat_id, user_id = int(chat), int(user)
    except Exception:
        return await c.answer("خطا", show_alert=True)
    if c.from_user.id != user_id:
        return await c.answer("این دکمه برای شما نیست.", show_alert=True)
    row = db.execute(
        "SELECT created FROM pending_captcha WHERE chat=? AND user=?",
        (chat_id, user_id)
    ).fetchone()
    if not row:
        return await c.answer("این تأییدیه منقضی شده.", show_alert=True)
    if time.time() - row[0] > 300:
        db.execute("DELETE FROM pending_captcha WHERE chat=? AND user=?", (chat_id, user_id))
        db.commit()
        return await c.answer("⏱ زمان CAPTCHA تمام شده است.", show_alert=True)
    try:
        await bot.restrict_chat_member(
            chat_id, user_id,
            permissions=ChatPermissions(can_send_messages=True)
        )
        db.execute("DELETE FROM pending_captcha WHERE chat=? AND user=?", (chat_id, user_id))
        db.commit()
        await c.message.edit_text("✅ تأیید شد؛ خوش آمدی!")
        await c.answer()
    except Exception:
        await c.answer("❌ تأیید انجام نشد.", show_alert=True)

@dp.callback_query(F.data.in_({"stats","users","security","features","logs"}))
async def panel(c):
    if not is_global_admin(c.from_user.id):
        return await c.answer("⛔", show_alert=True)
    if c.data == "stats":
        users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        filters_n = db.execute("SELECT COUNT(*) FROM filters").fetchone()[0]
        warnings_n = db.execute("SELECT COALESCE(SUM(count),0) FROM warnings").fetchone()[0]
        logs_n = db.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
        pending_n = db.execute("SELECT COUNT(*) FROM pending_captcha").fetchone()[0]
        t = (
            "📊 آمار V2\n"
            f"👥 کاربران ثبت‌شده: {users}\n"
            f"🔎 فیلترها: {filters_n}\n"
            f"⚠️ اخطارها: {warnings_n}\n"
            f"📜 لاگ‌ها: {logs_n}\n"
            f"🧩 CAPTCHA فعال: {pending_n}"
        )
    elif c.data == "users":
        r = db.execute(
            "SELECT id,name,username FROM users ORDER BY joined DESC LIMIT 20"
        ).fetchall()
        t = "👥 آخرین کاربران:\n" + (
            "\n".join(f"{i+1}. {n} @{u or '-'} | {uid}" for i, (uid,n,u) in enumerate(r))
            or "خالی"
        )
    elif c.data == "logs":
        r = db.execute(
            "SELECT action,target,created FROM logs ORDER BY id DESC LIMIT 15"
        ).fetchall()
        t = "📜 آخرین فعالیت‌ها:\n" + (
            "\n".join(f"• {a} | target={target} | {created[:19]}" for a,target,created in r)
            or "هنوز لاگی ثبت نشده."
        )
    elif c.data == "security":
        t = (
            "🛡 امنیت V2\n"
            "/antilink on|off\n"
            "/antispam on|off\n"
            "/captcha on|off\n"
            "/filter کلمه\n"
            "/unfilter کلمه"
        )
    else:
        t = (
            "⚙️ امکانات V2\n"
            "• مدیریت اعضا\n• Warning خودکار\n• Anti-Link\n"
            "• Anti-Spam + محدودسازی\n• CAPTCHA زمان‌دار\n"
            "• Notes\n• Welcome\n• Broadcast\n• Action Logs"
        )
    await c.message.edit_text(t, reply_markup=menu())
    await c.answer()

@dp.callback_query(F.data == "bc")
async def bc(c):
    if not is_global_admin(c.from_user.id):
        return await c.answer("⛔", show_alert=True)
    pending.add(c.from_user.id)
    await c.message.answer("📢 پیام همگانی را بفرست. /cancel")
    await c.answer()

@dp.message(Command("broadcast"))
async def broadcast(m):
    if not is_global_admin(m.from_user.id):
        return await m.answer("⛔")
    pending.add(m.from_user.id)
    await m.answer("📢 پیام را بفرست. /cancel")

@dp.message(Command("cancel"))
async def cancel(m):
    pending.discard(m.from_user.id)
    await m.answer("لغو شد.")

@dp.message()
async def allmsg(m):
    save(m)
    if is_global_admin(m.from_user.id) and m.from_user.id in pending:
        pending.discard(m.from_user.id)
        ok = bad = 0
        for (uid,) in db.execute("SELECT id FROM users"):
            try:
                await bot.copy_message(uid, m.chat.id, m.message_id)
                ok += 1
            except Exception:
                bad += 1
            await asyncio.sleep(0.04)
        return await m.answer(f"📢 تمام شد\n✅ {ok}\n❌ {bad}")

    if m.chat.type == "private" or not m.text:
        return

    low = m.text.lower()
    blocked_reason = None

    words = [x[0] for x in db.execute(
        "SELECT word FROM filters WHERE chat=?", (m.chat.id,)
    )]
    for word in words:
        if word and word in low:
            blocked_reason = "word-filter"
            break

    if not blocked_reason and toggle_value(m.chat.id, "antilink"):
        if "http://" in low or "https://" in low or "t.me/" in low or "www." in low:
            blocked_reason = "anti-link"

    if toggle_value(m.chat.id, "antispam"):
        now = time.time()
        s = db.execute(
            "SELECT last,count FROM spam WHERE chat=? AND user=?",
            (m.chat.id, m.from_user.id)
        ).fetchone()
        count = s[1] + 1 if s and now - s[0] < 8 else 1
        db.execute(
            "INSERT OR REPLACE INTO spam VALUES(?,?,?,?)",
            (m.chat.id, m.from_user.id, now, count)
        )
        db.commit()
        if count >= 5:
            blocked_reason = "anti-spam"
            try:
                await mute_user(m.chat.id, m.from_user.id, 5)
                log_action(m.chat.id, 0, "auto-mute-spam", m.from_user.id)
            except Exception:
                pass

    if blocked_reason:
        try:
            await m.delete()
        except Exception:
            pass

async def maintenance():
    while True:
        try:
            now = time.time()
            db.execute("DELETE FROM pending_captcha WHERE created < ?", (now - 300,))
            db.execute("DELETE FROM spam WHERE last < ?", (now - 30,))
            db.execute("DELETE FROM mutes WHERE until < ?", (now,))
            db.commit()
        except Exception:
            logging.exception("maintenance error")
        await asyncio.sleep(60)

async def health(_):
    return web.Response(text="OK")

async def main():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(
        runner, "0.0.0.0", int(os.getenv("PORT", "8080"))
    ).start()

    maintenance_task = asyncio.create_task(maintenance())
    try:
        await dp.start_polling(bot)
    finally:
        maintenance_task.cancel()
        await bot.session.close()
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
