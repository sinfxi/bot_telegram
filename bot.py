import os, asyncio, sqlite3, logging, time, ast, operator, random, secrets, string, re
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from collections import defaultdict
from openai import AsyncOpenAI

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, ChatPermissions, BotCommand, BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats
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
CREATE TABLE IF NOT EXISTS chat_texts(chat INTEGER, key TEXT, text TEXT, PRIMARY KEY(chat,key));
CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY AUTOINCREMENT, chat INTEGER, reporter INTEGER, target INTEGER, reason TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS ai_settings(chat INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 1, style TEXT DEFAULT 'khaki');
CREATE TABLE IF NOT EXISTS ai_history(id INTEGER PRIMARY KEY AUTOINCREMENT, chat INTEGER, user INTEGER, role TEXT, content TEXT, created REAL);
CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY AUTOINCREMENT, chat INTEGER NOT NULL, user INTEGER NOT NULL, text TEXT NOT NULL, due REAL NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS faq(chat INTEGER NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL, PRIMARY KEY(chat, question));
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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
AI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
AI_STYLES = {
    "khaki": ("خاکی و خودمونی", "مثل یک رفیق باحال و محترم، فارسی محاوره‌ای و طبیعی حرف بزن؛ نه رسمی و نه مصنوعی. کوتاه و صمیمی باش، شوخی ملایم اشکالی ندارد."),
    "funny": ("شوخ و بامزه", "فارسی محاوره‌ای، بانمک و پرانرژی حرف بزن. شوخی کن ولی توهین یا تحقیر نکن."),
    "chill": ("آروم و ریلکس", "خیلی راحت، آرام و بی‌تکلف به فارسی محاوره‌ای جواب بده؛ فشار نیاور و زیاده‌گویی نکن."),
    "pro": ("حرفه‌ای و دقیق", "فارسی روشن و حرفه‌ای، منظم و دقیق جواب بده؛ همچنان گرم و قابل‌فهم باش."),
    "coach": ("رفیق انگیزشی", "مثل رفیقی که حواسش هست، صمیمی و تشویق‌کننده جواب بده؛ واقع‌بین باش و شعار توخالی نده."),
    "gamer": ("گیمر و اینترنتی", "فارسی محاوره‌ای با حال‌وهوای گیمرها و اینترنت حرف بزن؛ اصطلاحات را طبیعی و به‌اندازه استفاده کن."),
    "short": ("کوتاه و مستقیم", "فارسی خودمانی و خیلی مختصر جواب بده؛ مستقیم برو سر اصل مطلب."),
}
ai_locks = defaultdict(asyncio.Lock)

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
        [InlineKeyboardButton(text="🛡️ مدیریت اعضا", callback_data="mod"), InlineKeyboardButton(text="🔐 امنیت", callback_data="security")],
        [InlineKeyboardButton(text="👋 مدیریت گروه", callback_data="group"), InlineKeyboardButton(text="🧰 ابزارها", callback_data="tools")],
        [InlineKeyboardButton(text="🤖 هوش مصنوعی", callback_data="ai_panel"), InlineKeyboardButton(text="📊 آمار", callback_data="stats")],
        [InlineKeyboardButton(text="👥 کاربران", callback_data="users"), InlineKeyboardButton(text="🚨 گزارش‌ها", callback_data="reports")],
        [InlineKeyboardButton(text="📜 لاگ‌ها", callback_data="logs"), InlineKeyboardButton(text="📢 همگانی", callback_data="bc")],
    ])

def ai_settings(chat_id):
    row = db.execute("SELECT enabled,style FROM ai_settings WHERE chat=?", (chat_id,)).fetchone()
    if not row:
        enabled = 1 if os.getenv("AI_ENABLED", "1").lower() in ("1","true","yes","on") else 0
        db.execute("INSERT OR IGNORE INTO ai_settings(chat,enabled,style) VALUES(?,?,?)", (chat_id,enabled,"khaki"))
        db.commit()
        return bool(enabled), "khaki"
    return bool(row[0]), row[1] if row[1] in AI_STYLES else "khaki"

def ai_keyboard():
    rows = []
    styles = list(AI_STYLES.items())
    for i in range(0, len(styles), 2):
        rows.append([InlineKeyboardButton(text=styles[i][1][0], callback_data=f"aistyle:{styles[i][0]}")])
        if i + 1 < len(styles):
            rows[-1].append(InlineKeyboardButton(text=styles[i+1][1][0], callback_data=f"aistyle:{styles[i+1][0]}"))
    rows.append([InlineKeyboardButton(text="🔛 روشن/خاموش", callback_data="aitoggle"), InlineKeyboardButton(text="🧹 پاک‌کردن حافظه", callback_data="aiclear")])
    rows.append([InlineKeyboardButton(text="⬅️ پنل اصلی", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def ai_reply(chat_id, user_id, user_text, user_name="دوست"):
    if not ai_client:
        return "هوش مصنوعی هنوز وصل نشده 😅 ادمین باید OPENAI_API_KEY رو توی متغیرهای محیطی ربات تنظیم کنه."
    enabled, style = ai_settings(chat_id)
    if not enabled:
        return None
    style_name, style_prompt = AI_STYLES.get(style, AI_STYLES["khaki"])
    async with ai_locks[(chat_id,user_id)]:
        db.execute("DELETE FROM ai_history WHERE created < ?", (time.time()-86400,))
        history = db.execute("SELECT role,content FROM ai_history WHERE chat=? AND user=? ORDER BY id DESC LIMIT 12", (chat_id,user_id)).fetchall()
        history.reverse()
        instructions = ("تو دستیار گفتگویی یک ربات تلگرام هستی. با فارسی روان جواب بده و با کاربر صادق باش. "
            "خودت را انسان واقعی جا نزن. اطلاعات شخصی دیگران را افشا نکن. اگر چیزی را نمی‌دانی واضح بگو. "
            f"نام نمایشی کاربر: {user_name}. سبک فعلی: {style_name}. {style_prompt} "
            "پاسخ معمولاً کوتاه و مناسب تلگرام باشد؛ وقتی کاربر توضیح کامل خواست، مفصل‌تر جواب بده.")
        try:
            response = await ai_client.responses.create(
                model=AI_MODEL, instructions=instructions,
                input=[{"role": role, "content": content} for role,content in history] + [{"role":"user","content":user_text}],
                max_output_tokens=500,
            )
            answer = (response.output_text or "یه لحظه قاطی کردم 😅 دوباره می‌گی؟").strip()
            db.execute("INSERT INTO ai_history(chat,user,role,content,created) VALUES(?,?,?,?,?)", (chat_id,user_id,"user",user_text[:3000],time.time()))
            db.execute("INSERT INTO ai_history(chat,user,role,content,created) VALUES(?,?,?,?,?)", (chat_id,user_id,"assistant",answer[:4000],time.time()))
            db.commit()
            return answer[:4000]
        except Exception:
            logging.exception("AI response failed")
            return "الان اتصال هوش مصنوعی یه مشکلی پیدا کرده 😕 یه کم دیگه دوباره امتحان کن."


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


def get_chat_text(chat_id, key, default=""):
    row = db.execute("SELECT text FROM chat_texts WHERE chat=? AND key=?", (chat_id, key)).fetchone()
    return row[0] if row else default

def set_chat_text(chat_id, key, text):
    db.execute("INSERT OR REPLACE INTO chat_texts VALUES(?,?,?)", (chat_id, key, text))
    db.commit()

async def is_admin_user(chat_id, user_id):
    if is_global_admin(user_id):
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
    except Exception:
        return False

async def set_bot_commands():
    group_commands = [
        BotCommand(command="start", description="شروع ربات"),
        BotCommand(command="help", description="نمایش همه قابلیت‌ها"),
        BotCommand(command="admin", description="پنل مدیریت"),
        BotCommand(command="ban", description="مسدود کردن کاربر"),
        BotCommand(command="unban", description="رفع مسدودی"),
        BotCommand(command="kick", description="اخراج کاربر"),
        BotCommand(command="mute", description="محدودسازی زمان‌دار"),
        BotCommand(command="unmute", description="رفع محدودیت"),
        BotCommand(command="warn", description="ثبت اخطار"),
        BotCommand(command="warnings", description="مشاهده اخطارها"),
        BotCommand(command="clearwarn", description="پاک کردن اخطارها"),
        BotCommand(command="promote", description="ارتقای کاربر به ادمین"),
        BotCommand(command="demote", description="حذف دسترسی ادمینی"),
        BotCommand(command="del", description="حذف پیام"),
        BotCommand(command="pin", description="سنجاق پیام"),
        BotCommand(command="unpin", description="برداشتن سنجاق"),
        BotCommand(command="userinfo", description="اطلاعات کاربر"),
        BotCommand(command="admins", description="لیست ادمین‌ها"),
        BotCommand(command="stats", description="آمار گروه"),
        BotCommand(command="chatinfo", description="اطلاعات گروه"),
        BotCommand(command="lock", description="قفل کردن ارسال پیام"),
        BotCommand(command="unlock", description="باز کردن قفل گروه"),
        BotCommand(command="antilink", description="کنترل لینک"),
        BotCommand(command="antispam", description="کنترل اسپم"),
        BotCommand(command="captcha", description="CAPTCHA اعضای جدید"),
        BotCommand(command="filter", description="افزودن کلمه فیلتر"),
        BotCommand(command="unfilter", description="حذف کلمه فیلتر"),
        BotCommand(command="filters", description="لیست فیلترها"),
        BotCommand(command="welcome", description="فعال/غیرفعال کردن خوشامد"),
        BotCommand(command="setwelcome", description="تنظیم متن خوشامد"),
        BotCommand(command="rules", description="نمایش قوانین"),
        BotCommand(command="setrules", description="تنظیم قوانین"),
        BotCommand(command="note", description="ذخیره یادداشت"),
        BotCommand(command="getnote", description="دریافت یادداشت"),
        BotCommand(command="notes", description="لیست یادداشت‌ها"),
        BotCommand(command="report", description="گزارش کاربر"),
        BotCommand(command="id", description="نمایش شناسه‌ها"),
        BotCommand(command="ai", description="فعال یا غیرفعال کردن هوش مصنوعی"),
        BotCommand(command="style", description="انتخاب لحن هوش مصنوعی"),
        BotCommand(command="clearchat", description="پاک کردن حافظه گفتگو"),
        BotCommand(command="dice", description="تاس انداختن"),
        BotCommand(command="coin", description="شیر یا خط"),
        BotCommand(command="joke", description="گفتن جوک"),
        BotCommand(command="password", description="ساخت رمز تصادفی"),
        BotCommand(command="profile", description="نمایش پروفایل"),
        BotCommand(command="reminders", description="فهرست یادآوری‌ها"),
        BotCommand(command="calc", description="ماشین‌حساب"),
        BotCommand(command="poll", description="ساخت نظرسنجی"),
        BotCommand(command="ask", description="پرسش از پاسخ‌های ذخیره‌شده"),
        BotCommand(command="faq", description="افزودن پاسخ آماده"),
        BotCommand(command="faqs", description="فهرست پرسش‌های آماده"),
        BotCommand(command="delfaq", description="حذف پرسش آماده"),
    ]
    private_commands = [
        BotCommand(command="start", description="شروع ربات"),
        BotCommand(command="help", description="نمایش همه قابلیت‌ها"),
        BotCommand(command="admin", description="پنل مدیریت"),
        BotCommand(command="stats", description="آمار ربات"),
        BotCommand(command="id", description="نمایش شناسه"),
        BotCommand(command="ai", description="روشن/خاموش کردن هوش مصنوعی"),
        BotCommand(command="style", description="انتخاب لحن هوش مصنوعی"),
        BotCommand(command="clearchat", description="پاک کردن حافظه گفتگو"),
        BotCommand(command="dice", description="تاس انداختن"),
        BotCommand(command="coin", description="شیر یا خط"),
        BotCommand(command="joke", description="گفتن جوک"),
        BotCommand(command="password", description="ساخت رمز تصادفی"),
        BotCommand(command="profile", description="نمایش پروفایل"),
        BotCommand(command="reminders", description="فهرست یادآوری‌ها"),
        BotCommand(command="calc", description="ماشین‌حساب"),
        BotCommand(command="poll", description="ساخت نظرسنجی"),
        BotCommand(command="ask", description="پرسش از پاسخ‌های ذخیره‌شده"),
        BotCommand(command="faqs", description="فهرست پرسش‌های آماده"),
    ]
    await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())

@dp.message(CommandStart())
async def start(m):
    save(m)
    text = ("🛠 پنل مدیریت آماده است.\n🧰 ابزارهای جدید: /dice /coin /joke /password /profile /reminders /calc /poll\nبرای راهنما /help را بزن.") if is_global_admin(m.from_user.id) else "🤖 ربات به‌روزرسانی شد!\n🧰 ابزارها: /dice /coin /joke /password /profile /reminders /calc /poll\n⏰ یادآوری: «یادآوری 10 دقیقه بعد آب بخور»\nبرای راهنمای کامل /help را بزن."
    await m.answer(text, reply_markup=menu() if is_global_admin(m.from_user.id) else None)

@dp.message(Command("help"))
async def help_cmd(m):
    await m.answer("""🤖 ربات مدیریت جامع گروه

🛡️ مدیریت اعضا
/ban /unban /kick
/mute [minutes] /unmute
/warn /warnings /clearwarn
/promote /demote
/del /pin /unpin
/userinfo /admins

🔐 امنیت
/antilink on|off
/antispam on|off
/captcha on|off
/filter کلمه
/unfilter کلمه
/filters
/lock /unlock

👋 مدیریت گروه
/welcome on|off
/setwelcome متن
/rules
/setrules متن
/chatinfo /stats

🧰 ابزارها
/note نام متن
/getnote نام
/notes
/report
/id

🤖 هوش مصنوعی خودمونی
در پیوی به ربات پیام بده؛ در گروه روی پیام ربات Reply کن یا @نام‌ربات را صدا بزن.
 /ai on|off — روشن/خاموش کردن AI
/style — انتخاب لحن (خاکی، شوخ، ریلکس، حرفه‌ای، گیمر و ...)
 /clearchat — پاک کردن حافظه گفتگوی خودت

👑 مدیریت اصلی
/admin /broadcast /cancel

⏰ ابزارهای شخصی (بدون نیاز به مدیریت گروه)\nیادآوری 10 دقیقه بعد آب بخور\nیادآوری‌های من / آخرین یادآوری رو حذف کن\nحساب کن 12 * (4 + 3)\nنظرسنجی بساز | سؤال | گزینه اول | گزینه دوم\n/dice تاس /coin شیر یا خط /joke جوک /password رمز /profile پروفایل /reminders یادآوری‌ها /calc عبارت /poll سؤال | گزینه۱ | گزینه۲\n\n📚 پاسخ‌گویی بدون هوش مصنوعی\n/ask سؤال — جست‌وجو در پاسخ‌های ذخیره‌شده\n/faq سؤال | پاسخ — ثبت پاسخ (ادمین گروه)\n/faqs — فهرست سؤال‌ها\n/delfaq سؤال — حذف پاسخ (ادمین گروه)\n\n💡 دستورات مدیریتی را با Reply روی پیام کاربر اجرا کن.""")

@dp.message(Command("id"))
async def ident(m):
    await m.answer(f"🆔 User: {m.from_user.id}\n💬 Chat: {m.chat.id}")

@dp.message(Command("admin"))
async def admin_cmd(m):
    if not is_global_admin(m.from_user.id):
        return await m.answer("⛔ دسترسی ندارید.")
    await m.answer("🛠 پنل مدیریت ربات | برای کنترل قابلیت‌ها یکی از بخش‌ها را انتخاب کن.", reply_markup=menu())

@dp.message(Command("ai"))
async def ai_toggle_command(m):
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2 or parts[1].lower() not in ("on","off"):
        enabled, style = ai_settings(m.chat.id)
        return await m.answer(f"وضعیت هوش مصنوعی: {'روشن' if enabled else 'خاموش'}\nلحن: {AI_STYLES[style][0]}\nاستفاده: /ai on یا /ai off")
    if m.chat.type != "private" and not await group_admin(m): return
    enabled = parts[1].lower() == "on"
    db.execute("INSERT INTO ai_settings(chat,enabled,style) VALUES(?,?,?) ON CONFLICT(chat) DO UPDATE SET enabled=excluded.enabled", (m.chat.id,int(enabled),"khaki"))
    db.commit()
    await m.answer(("🤖 هوش مصنوعی روشن شد." if enabled else "🤐 هوش مصنوعی خاموش شد.") + ("\nبرای پاسخ هوشمند، کلید API باید تنظیم شده باشد." if enabled and not ai_client else ""))

@dp.message(Command("style"))
async def ai_style_command(m):
    await m.answer("🎭 لحن هوش مصنوعی رو انتخاب کن:", reply_markup=ai_keyboard())

@dp.message(Command("clearchat"))
async def clear_ai_history(m):
    db.execute("DELETE FROM ai_history WHERE chat=? AND user=?", (m.chat.id,m.from_user.id))
    db.commit()
    await m.answer("🧹 حافظه گفتگوی تو با ربات پاک شد.")


@dp.message(Command("stats"))
async def stats_cmd(m):
    users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    filters_n = db.execute("SELECT COUNT(*) FROM filters WHERE chat=?", (m.chat.id,)).fetchone()[0]
    warnings_n = db.execute("SELECT COALESCE(SUM(count),0) FROM warnings WHERE chat=?", (m.chat.id,)).fetchone()[0]
    notes_n = db.execute("SELECT COUNT(*) FROM notes WHERE chat=?", (m.chat.id,)).fetchone()[0]
    logs_n = db.execute("SELECT COUNT(*) FROM logs WHERE chat=?", (m.chat.id,)).fetchone()[0]
    await m.answer(f"📊 آمار گروه\n👥 کاربران ثبت‌شده: {users}\n⚠️ اخطارها: {warnings_n}\n🚫 فیلترها: {filters_n}\n📝 یادداشت‌ها: {notes_n}\n📜 لاگ‌ها: {logs_n}")

@dp.message(Command("userinfo"))
async def userinfo(m):
    u = target(m) or m.from_user
    member = None
    try:
        member = await bot.get_chat_member(m.chat.id, u.id)
    except Exception:
        pass
    status = member.status.value if member else "unknown"
    warns = db.execute("SELECT count FROM warnings WHERE chat=? AND user=?", (m.chat.id, u.id)).fetchone()
    await m.answer(f"👤 اطلاعات کاربر\nنام: {u.full_name}\nUsername: @{u.username or '-'}\nID: {u.id}\nوضعیت: {status}\n⚠️ اخطار: {warns[0] if warns else 0}/3")

@dp.message(Command("admins"))
async def admins(m):
    try:
        members = await bot.get_chat_administrators(m.chat.id)
        lines = []
        for x in members:
            user = x.user
            lines.append(f"• {user.full_name} — @{user.username or '-'}")
        await m.answer("👑 ادمین‌های گروه:\n" + "\n".join(lines))
    except Exception as e:
        await m.answer(f"❌ دریافت ادمین‌ها ممکن نشد: {e}")

@dp.message(Command("chatinfo"))
async def chatinfo(m):
    try:
        chat = await bot.get_chat(m.chat.id)
        count = await bot.get_chat_member_count(m.chat.id)
        await m.answer(f"💬 اطلاعات گروه\nنام: {chat.title or '-'}\nID: {chat.id}\nنوع: {chat.type}\nUsername: @{chat.username or '-'}\nتعداد اعضا: {count}")
    except Exception as e:
        await m.answer(f"❌ {e}")

@dp.message(Command("kick"))
async def kick(m):
    if not await group_admin(m): return
    u = target(m)
    if not u: return await m.answer("کاربر را ریپلای کن.")
    try:
        await bot.ban_chat_member(m.chat.id, u.id)
        await bot.unban_chat_member(m.chat.id, u.id, only_if_banned=True)
        log_action(m.chat.id, m.from_user.id, "kick", u.id)
        await m.answer(f"👢 {u.full_name} از گروه اخراج شد.")
    except Exception as e:
        await m.answer(f"❌ {e}")

@dp.message(Command("unpin"))
async def unpin(m):
    if not await group_admin(m): return
    try:
        if m.reply_to_message:
            await bot.unpin_chat_message(m.chat.id, m.reply_to_message.message_id)
        else:
            await bot.unpin_chat_message(m.chat.id)
        await m.answer("📌 سنجاق برداشته شد.")
    except Exception as e:
        await m.answer(f"❌ {e}")

@dp.message(Command("lock"))
async def lock_group(m):
    if not await group_admin(m): return
    try:
        await bot.set_chat_permissions(m.chat.id, ChatPermissions(can_send_messages=False))
        set_chat_text(m.chat.id, "locked", "1")
        log_action(m.chat.id, m.from_user.id, "lock")
        await m.answer("🔒 گروه قفل شد؛ اعضای عادی نمی‌توانند پیام ارسال کنند.")
    except Exception as e:
        await m.answer(f"❌ {e}")

@dp.message(Command("unlock"))
async def unlock_group(m):
    if not await group_admin(m): return
    try:
        await bot.set_chat_permissions(m.chat.id, ChatPermissions(
            can_send_messages=True,
            can_send_audios=True, can_send_documents=True, can_send_photos=True,
            can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True,
            can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True
        ))
        set_chat_text(m.chat.id, "locked", "0")
        log_action(m.chat.id, m.from_user.id, "unlock")
        await m.answer("🔓 گروه باز شد.")
    except Exception as e:
        await m.answer(f"❌ {e}")

@dp.message(Command("setwelcome"))
async def setwelcome(m):
    if not await group_admin(m): return
    p = (m.text or "").split(maxsplit=1)
    if len(p) < 2: return await m.answer("مثال: /setwelcome سلام {name}، خوش آمدی!")
    set_chat_text(m.chat.id, "welcome_text", p[1])
    await m.answer("✅ متن خوش‌آمدگویی ذخیره شد.")

@dp.message(Command("setrules"))
async def setrules(m):
    if not await group_admin(m): return
    p = (m.text or "").split(maxsplit=1)
    if len(p) < 2: return await m.answer("مثال: /setrules قوانین گروه...")
    set_chat_text(m.chat.id, "rules", p[1])
    await m.answer("✅ قوانین گروه ذخیره شد.")

@dp.message(Command("report"))
async def report(m):
    u = target(m)
    if not u: return await m.answer("برای گزارش، پیام کاربر را ریپلای کن.")
    p = (m.text or "").split(maxsplit=1)
    reason = p[1] if len(p) > 1 else "بدون توضیح"
    db.execute("INSERT INTO reports(chat,reporter,target,reason,created) VALUES(?,?,?,?,?)",
               (m.chat.id, m.from_user.id, u.id, reason, datetime.utcnow().isoformat()))
    db.commit()
    await m.answer("🚨 گزارش ثبت شد و برای بررسی ادمین‌ها ذخیره شد.")

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
    rules_text = get_chat_text(m.chat.id, "rules", "1) احترام متقابل\n2) بدون اسپم و فلود\n3) تبلیغ بدون اجازه ممنوع\n4) لینک مشکوک ممنوع")
    await m.answer("📜 قوانین گروه:\n" + rules_text)

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
            welcome_text = get_chat_text(m.chat.id, "welcome_text", "👋 خوش آمدی {name}!")
            await m.answer(welcome_text.replace("{name}", u.full_name).replace("{username}", "@" + (u.username or "")))
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

@dp.callback_query(F.data.in_({"stats","users","security","mod","group","tools","features","logs","home","ai_panel","aitoggle","aiclear","reports"}) | F.data.startswith("aistyle:"))
async def panel(c):
    if not is_global_admin(c.from_user.id):
        return await c.answer("⛔", show_alert=True)
    if c.data == "home":
        await c.message.edit_text("🛠 پنل مدیریت ربات", reply_markup=menu())
        return await c.answer()
    if c.data == "ai_panel":
        enabled, style = ai_settings(c.message.chat.id)
        t = ("🤖 پنل هوش مصنوعی\n" + f"وضعیت: {'روشن 🟢' if enabled else 'خاموش 🔴'}\n" + f"اتصال API: {'آماده' if ai_client else 'کلید API تنظیم نشده'}\n" + f"مدل: {AI_MODEL}\n" + f"لحن: {AI_STYLES[style][0]}\n\n" + "در گفتگوی خصوصی، ربات به پیام‌ها پاسخ می‌دهد. در گروه، به پیام ریپلای کن یا نام ربات را صدا بزن.")
        await c.message.edit_text(t, reply_markup=ai_keyboard())
        return await c.answer()
    if c.data == "aitoggle":
        enabled, style = ai_settings(c.message.chat.id)
        db.execute("UPDATE ai_settings SET enabled=? WHERE chat=?", (0 if enabled else 1,c.message.chat.id))
        db.commit()
        enabled, style = ai_settings(c.message.chat.id)
        t = f"🤖 هوش مصنوعی {'روشن 🟢' if enabled else 'خاموش 🔴'}\nAPI: {'وصل' if ai_client else 'نیازمند OPENAI_API_KEY'}\nلحن: {AI_STYLES[style][0]}"
        await c.message.edit_text(t, reply_markup=ai_keyboard())
        return await c.answer("انجام شد")
    if c.data == "aiclear":
        db.execute("DELETE FROM ai_history WHERE chat=?", (c.message.chat.id,))
        db.commit()
        await c.message.edit_text("🧹 حافظه هوش مصنوعی برای این گفتگو پاک شد.", reply_markup=ai_keyboard())
        return await c.answer()
    if c.data.startswith("aistyle:"):
        style = c.data.split(":",1)[1]
        if style not in AI_STYLES: return await c.answer("لحن ناشناخته", show_alert=True)
        enabled, _ = ai_settings(c.message.chat.id)
        db.execute("INSERT INTO ai_settings(chat,enabled,style) VALUES(?,?,?) ON CONFLICT(chat) DO UPDATE SET style=excluded.style", (c.message.chat.id,int(enabled),style))
        db.commit()
        try:
            await c.message.edit_text(f"🎭 لحن انتخاب شد: {AI_STYLES[style][0]}", reply_markup=ai_keyboard())
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                raise
        return await c.answer("این لحن همین الان فعاله.")
    if c.data == "reports":
        r = db.execute("SELECT chat,reporter,target,reason,created FROM reports ORDER BY id DESC LIMIT 10").fetchall()
        t = "🚨 آخرین گزارش‌ها:\n" + ("\n".join(f"گروه {ch} | گزارش‌دهنده {rep} | کاربر {target}\n{reason[:100]} | {created[:16]}" for ch,rep,target,reason,created in r) or "گزارشی ثبت نشده.")
        await c.message.edit_text(t, reply_markup=menu())
        return await c.answer()
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
            "🛡️ امنیت\n"
            "• Anti-Link\n• Anti-Spam + Auto-Mute\n• CAPTCHA\n"
            "• Word Filter\n• Lock / Unlock\n\n"
            "/antilink on|off\n/antispam on|off\n/captcha on|off\n/filter کلمه\n/unfilter کلمه\n/filters\n/lock\n/unlock"
        )
    elif c.data == "mod":
        t = (
            "🛡️ مدیریت اعضا\n"
            "/ban /unban /kick\n/mute [minutes] /unmute\n/warn /warnings /clearwarn\n"
            "/promote /demote\n/del /pin /unpin\n/userinfo /admins"
        )
    elif c.data == "group":
        t = (
            "👋 مدیریت گروه\n"
            "/welcome on|off\n/setwelcome متن\n/rules\n/setrules متن\n"
            "/chatinfo /stats"
        )
    elif c.data == "tools":
        t = (
            "🧰 ابزارها\n"
            "/note نام متن\n/getnote نام\n/notes\n/report\n/id"
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


def find_faq(chat_id, question):
    """Find a stored answer without calling any AI service."""
    query = normalize_text(question)
    if not query:
        return None
    rows = db.execute("SELECT question,answer FROM faq WHERE chat=?", (chat_id,)).fetchall()
    best_answer, best_score = None, 0.0
    query_words = set(query.split())
    for saved_question, answer in rows:
        saved = normalize_text(saved_question)
        if query == saved or query in saved or saved in query:
            return answer
        words = set(saved.split())
        overlap = len(query_words & words) / max(1, len(query_words | words))
        score = max(SequenceMatcher(None, query, saved).ratio(), overlap)
        if score > best_score:
            best_answer, best_score = answer, score
    return best_answer if best_score >= 0.72 else None


@dp.message(Command("ask"))
async def ask_faq_cmd(m):
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer("📚 سؤال را این‌طور بفرست: /ask ساعت کاری چطوره؟\nاین بخش فقط پاسخ‌های ذخیره‌شده را می‌گردد و از هوش مصنوعی استفاده نمی‌کند.")
    answer = find_faq(m.chat.id, parts[1])
    await m.answer("📚 پاسخ ذخیره‌شده:\n" + answer if answer else "🔎 پاسخ آماده‌ای برای این سؤال پیدا نکردم. از ادمین بخواه با دستور /faq سؤال | پاسخ آن را اضافه کند.")


@dp.message(Command("faq"))
async def add_faq_cmd(m):
    if m.chat.type != "private" and not await group_admin(m):
        return
    if m.chat.type == "private" and not is_global_admin(m.from_user.id):
        return await m.answer("⛔ افزودن پاسخ آماده فقط برای ادمین ربات مجاز است.")
    payload = (m.text or "").split(maxsplit=1)
    parts = [x.strip() for x in payload[1].split("|", 1)] if len(payload) > 1 else []
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return await m.answer("قالب: /faq سؤال | پاسخ\nمثال: /faq ساعت کاری چیه؟ | هر روز از ۹ تا ۵")
    question, answer = parts
    if len(question) > 200 or len(answer) > 3000:
        return await m.answer("سؤال حداکثر ۲۰۰ و پاسخ حداکثر ۳۰۰۰ کاراکتر باشد.")
    db.execute("INSERT OR REPLACE INTO faq(chat,question,answer) VALUES(?,?,?)", (m.chat.id, question, answer))
    db.commit()
    await m.answer("✅ پاسخ ذخیره شد. از این به بعد بدون هوش مصنوعی هم به سؤال‌های مشابه جواب می‌دهم.")


@dp.message(Command("faqs"))
async def list_faq_cmd(m):
    rows = db.execute("SELECT question FROM faq WHERE chat=? ORDER BY question LIMIT 50", (m.chat.id,)).fetchall()
    await m.answer("📚 سؤال‌های آماده:\n" + ("\n".join(f"• {q}" for (q,) in rows) if rows else "هنوز پاسخی ذخیره نشده. ادمین می‌تواند با /faq سؤال | پاسخ اضافه کند."))


@dp.message(Command("delfaq"))
async def delete_faq_cmd(m):
    if m.chat.type != "private" and not await group_admin(m):
        return
    if m.chat.type == "private" and not is_global_admin(m.from_user.id):
        return await m.answer("⛔ حذف پاسخ آماده فقط برای ادمین ربات مجاز است.")
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer("قالب: /delfaq متن سؤال")
    db.execute("DELETE FROM faq WHERE chat=? AND question=?", (m.chat.id, parts[1].strip()))
    deleted = db.execute("SELECT changes()").fetchone()[0]
    db.commit()
    await m.answer("🗑 پاسخ حذف شد." if deleted else "این سؤال دقیقاً در فهرست پیدا نشد. /faqs را ببین.")


@dp.message(Command("dice"))
async def dice_cmd(m):
    await m.answer(f"🎲 نتیجه تاس: {random.randint(1, 6)}")

@dp.message(Command("coin"))
async def coin_cmd(m):
    await m.answer("🪙 " + random.choice(["شیر", "خط"]))

@dp.message(Command("joke"))
async def joke_cmd(m):
    await m.answer(random.choice([
        "به کامپیوتر گفتم استراحت کن؛ گفت اول همه پنجره‌هامو ببند! 😄",
        "برنامه‌نویس چرا دیر خوابید؟ چون داشت باگ‌های خوابش رو دیباگ می‌کرد! 🐛",
        "اینترنت چرا کند بود؟ داشت با زندگی سینک می‌شد! 😂",
    ]))

@dp.message(Command("password"))
async def password_cmd(m):
    password = "".join(secrets.choice(string.ascii_letters + string.digits + "!@#$%_-+") for _ in range(16))
    await m.answer("🔐 رمز تصادفی ۱۶ کاراکتری:\n<code>" + password + "</code>", parse_mode="HTML")

@dp.message(Command("profile"))
async def profile_cmd(m):
    reminders_n = db.execute("SELECT COUNT(*) FROM reminders WHERE user=?", (m.from_user.id,)).fetchone()[0]
    await m.answer(
        f"👤 پروفایل تو\nنام: {m.from_user.full_name}\nشناسه: <code>{m.from_user.id}</code>\n"
        f"نام کاربری: @{m.from_user.username or 'ندارد'}\nیادآوری‌های فعال: {reminders_n}",
        parse_mode="HTML"
    )

@dp.message(Command("reminders"))
async def reminders_cmd(m):
    rows = db.execute("SELECT id,text,due FROM reminders WHERE user=? ORDER BY due LIMIT 10", (m.from_user.id,)).fetchall()
    if not rows:
        return await m.answer("⏰ یادآوری فعالی نداری.")
    await m.answer("⏰ یادآوری‌های تو:\n" + "\n".join(
        f"#{rid} — {txt} (حدود {max(0, int((due-time.time())/60))} دقیقه دیگه)" for rid,txt,due in rows
    ))

@dp.message(Command("calc"))
async def calc_cmd(m):
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer("مثال: /calc 12*(4+3)")
    try:
        result = safe_calculate(parts[1].replace("×", "*").replace("÷", "/").replace("^", "**"))
        await m.answer(f"🧮 نتیجه: <code>{result}</code>", parse_mode="HTML")
    except ZeroDivisionError:
        await m.answer("🧮 تقسیم بر صفر ممکن نیست.")
    except Exception:
        await m.answer("عبارت ریاضی ساده وارد کن؛ مثال: /calc 12*(4+3)")

@dp.message(Command("poll"))
async def poll_cmd(m):
    payload = (m.text or "").split(maxsplit=1)
    parts = [x.strip() for x in payload[1].split("|") if x.strip()] if len(payload) > 1 else []
    if len(parts) < 3 or len(parts) > 11:
        return await m.answer("قالب: /poll سؤال | گزینه اول | گزینه دوم")
    try:
        await bot.send_poll(m.chat.id, question=parts[0][:300], options=[x[:100] for x in parts[1:11]], is_anonymous=True)
    except Exception:
        await m.answer("❌ نظرسنجی ساخته نشد؛ قالب را بررسی کن.")

def safe_calculate(expression):
    """Evaluate basic arithmetic without eval or arbitrary Python execution."""
    tree = ast.parse(expression, mode="eval")
    binary = {
        ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod, ast.Pow: operator.pow,
    }
    unary = {ast.UAdd: operator.pos, ast.USub: operator.neg}
    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in binary:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 8:
                raise ValueError("توان خیلی بزرگه")
            result = binary[type(node.op)](left, right)
            if abs(result) > 10**15:
                raise ValueError("عدد خیلی بزرگه")
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in unary:
            return unary[type(node.op)](visit(node.operand))
        raise ValueError("فقط محاسبات ساده مجازه")
    return visit(tree)

def normalize_text(text):
    import re
    text = (text or "").lower().replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"[!?؟،,.؛:]+", " ", text)
    return " ".join(text.split())

async def natural_command(m):
    """Run common Persian natural-language aliases for the bot's slash commands."""
    if not m.text or m.text.startswith("/"):
        return False
    # Explicit non-AI FAQ lookup; runs before any conversational AI fallback.
    if t_for_faq := normalize_text(m.text):
        if t_for_faq.startswith(("سوال ", "سؤال ", "بپرس ", "جواب سوال ", "جواب سؤال ")):
            question = re.sub(r"^(?:سوال|سؤال|بپرس|جواب سوال|جواب سؤال)\s+", "", m.text.strip(), flags=re.IGNORECASE)
            answer = find_faq(m.chat.id, question)
            await m.answer("📚 پاسخ ذخیره‌شده:\n" + answer if answer else "🔎 جواب این سؤال در پاسخ‌های ذخیره‌شده نیست. ادمین می‌تواند با /faq سؤال | پاسخ آن را اضافه کند.")
            return True
    raw = m.text.strip()
    t = normalize_text(raw)
    is_private = m.chat.type == "private"

    # AI toggle / tone can be used in private chats or groups.
    if any(x in t for x in ("ربات روشن", "هوش مصنوعی روشن", "هوش مصنوعی رو روشن", "ربات رو روشن کن", "ai روشن")):
        if not is_private and not await group_admin(m):
            return True
        db.execute("INSERT INTO ai_settings(chat,enabled,style) VALUES(?,?,?) ON CONFLICT(chat) DO UPDATE SET enabled=1", (m.chat.id, 1, "khaki"))
        db.commit()
        await m.answer("🤖 چشم! هوش مصنوعی روشن شد." + ("\nبرای پاسخ هوشمند باید OPENAI_API_KEY تنظیم شده باشه." if not ai_client else ""))
        return True
    if any(x in t for x in ("ربات خاموش", "هوش مصنوعی خاموش", "هوش مصنوعی رو خاموش", "ربات رو خاموش کن", "ai خاموش")):
        if not is_private and not await group_admin(m):
            return True
        enabled, style = ai_settings(m.chat.id)
        db.execute("UPDATE ai_settings SET enabled=0 WHERE chat=?", (m.chat.id,))
        db.commit()
        await m.answer("🤐 باشه، هوش مصنوعی این گفتگو خاموش شد.")
        return True

    if any(x in t for x in ("پنل مدیریت", "منوی مدیریت", "پنل ربات", "مدیریت ربات")):
        if not is_global_admin(m.from_user.id):
            await m.answer("⛔ این پنل فقط برای مدیر اصلی رباته.")
        else:
            await m.answer("🛠 پنل مدیریت ربات", reply_markup=menu())
        return True

    # Read-only information commands.
    if any(x in t for x in ("آمار گروه", "آمار ربات", "وضعیت گروه", "آمار رو بگو")):
        users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        filters_n = db.execute("SELECT COUNT(*) FROM filters WHERE chat=?", (m.chat.id,)).fetchone()[0]
        warnings_n = db.execute("SELECT COALESCE(SUM(count),0) FROM warnings WHERE chat=?", (m.chat.id,)).fetchone()[0]
        notes_n = db.execute("SELECT COUNT(*) FROM notes WHERE chat=?", (m.chat.id,)).fetchone()[0]
        await m.answer(f"📊 آمار\n👥 کاربران ثبت‌شده: {users}\n⚠️ اخطارها: {warnings_n}\n🚫 فیلترها: {filters_n}\n📝 یادداشت‌ها: {notes_n}")
        return True
    if any(x in t for x in ("قوانین گروه", "قانون های گروه", "قانون‌های گروه", "قوانین چیه")):
        rules_text = get_chat_text(m.chat.id, "rules", "1) احترام متقابل\n2) بدون اسپم و فلود\n3) تبلیغ بدون اجازه ممنوع\n4) لینک مشکوک ممنوع")
        await m.answer("📜 قوانین گروه:\n" + rules_text)
        return True
    if any(x in t for x in ("لیست ادمین", "ادمین های گروه", "ادمین‌های گروه")):
        try:
            admins = await bot.get_chat_administrators(m.chat.id)
            await m.answer("👑 ادمین‌های گروه:\n" + "\n".join("• " + (a.user.full_name or str(a.user.id)) for a in admins))
        except Exception:
            await m.answer("نتونستم فهرست ادمین‌ها رو بگیرم؛ ربات رو بررسی کن.")
        return True
    if any(x in t for x in ("لیست فیلتر", "فیلترها رو نشون بده", "کلمه های فیلتر")):
        rows = db.execute("SELECT word FROM filters WHERE chat=? ORDER BY word", (m.chat.id,)).fetchall()
        await m.answer("🔎 فیلترهای گروه:\n" + ("\n".join("• " + x[0] for x in rows) or "هنوز فیلتری ثبت نشده."))
        return True

    # Group settings: only admins can change these.
    toggles = [
        (("ضدلینک روشن", "ضدلینک رو روشن", "ضد لینک روشن", "ضد لینک رو روشن", "لینک ممنوع رو روشن", "جلوگیری از لینک رو روشن"), "antilink", "🔗 ضدلینک"),
        (("ضدلینک خاموش", "ضدلینک رو خاموش", "ضد لینک خاموش", "ضد لینک رو خاموش", "لینک ممنوع رو خاموش", "جلوگیری از لینک رو خاموش"), "antilink", "🔗 ضدلینک"),
        (("ضداسپم روشن", "ضداسپم رو روشن", "ضد اسپم روشن", "ضد اسپم رو روشن", "اسپم رو روشن", "جلوگیری از اسپم رو روشن"), "antispam", "🛡 ضداسپم"),
        (("ضداسپم خاموش", "ضداسپم رو خاموش", "ضد اسپم خاموش", "ضد اسپم رو خاموش", "اسپم رو خاموش", "جلوگیری از اسپم رو خاموش"), "antispam", "🛡 ضداسپم"),
        (("کپچا روشن", "کپچا رو روشن کن", "تایید اعضای جدید روشن", "تأیید اعضای جدید روشن"), "captcha", "🧩 کپچا"),
        (("کپچا خاموش", "کپچا رو خاموش کن", "تایید اعضای جدید خاموش", "تأیید اعضای جدید خاموش"), "captcha", "🧩 کپچا"),
        (("خوشامد روشن", "خوشامدگویی روشن", "خوشامدگویی رو روشن کن", "پیام خوشامد روشن"), "welcome", "👋 خوشامدگویی"),
        (("خوشامد خاموش", "خوشامدگویی خاموش", "خوشامدگویی رو خاموش کن", "پیام خوشامد خاموش"), "welcome", "👋 خوشامدگویی"),
    ]
    for phrases, field, title in toggles:
        matched = next((p for p in phrases if p in t), None)
        if matched:
            if not await group_admin(m):
                return True
            value = not any(word in matched for word in ("خاموش",))
            ensure_settings(m.chat.id)
            db.execute(f"UPDATE settings SET {field}=? WHERE chat=?", (int(value), m.chat.id))
            db.commit()
            log_action(m.chat.id, m.from_user.id, f"{field} {'on' if value else 'off'}")
            await m.answer(f"{title} {'فعال شد ✅' if value else 'خاموش شد.'}")
            return True

    if any(x in t for x in ("قفل گروه", "گروه رو قفل کن", "ارسال پیام رو قفل کن")) and not any(x in t for x in ("باز کردن", "باز کن", "آزاد کن")):
        if not await group_admin(m):
            return True
        try:
            await bot.set_chat_permissions(m.chat.id, ChatPermissions(can_send_messages=False))
            await m.answer("🔒 ارسال پیام در گروه قفل شد.")
        except Exception as e:
            await m.answer(f"❌ نتونستم گروه رو قفل کنم: {e}")
        return True
    if any(x in t for x in ("باز کردن قفل گروه", "قفل گروه رو باز کن", "گروه رو باز کن", "ارسال پیام رو آزاد کن")):
        if not await group_admin(m):
            return True
        try:
            await bot.set_chat_permissions(m.chat.id, ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True))
            await m.answer("🔓 قفل ارسال پیام برداشته شد.")
        except Exception as e:
            await m.answer(f"❌ نتونستم قفل رو باز کنم: {e}")
        return True

    # Moderation actions require an explicit reply to the target message.
    moderation = [
        (("این کاربر رو بن کن", "کاربر رو بن کن", "مسدودش کن", "بنش کن"), "ban"),
        (("این کاربر رو اخراج کن", "کاربر رو اخراج کن", "اخراجش کن", "بندازش بیرون"), "kick"),
        (("این کاربر رو ساکت کن", "کاربر رو ساکت کن", "سکوتش کن", "میوتش کن"), "mute"),
        (("سکوت این کاربر رو بردار", "رفع سکوتش کن", "آزادش کن"), "unmute"),
        (("به این کاربر اخطار بده", "بهش اخطار بده", "اخطارش کن"), "warn"),
        (("اخطارهای این کاربر رو پاک کن", "اخطارهاش رو پاک کن"), "clearwarn"),
        (("این پیام رو پاک کن", "پیام رو حذف کن", "این پیامو پاک کن"), "delete"),
        (("این پیام رو سنجاق کن", "پیام رو پین کن", "سنجاقش کن"), "pin"),
        (("سنجاق این پیام رو بردار", "پیام رو از سنجاق دربیار", "آنپین کن"), "unpin"),
        (("این کاربر رو ادمین کن", "بهش دسترسی ادمین بده"), "promote"),
        (("ادمینیش رو بردار", "دسترسی ادمینش رو بگیر", "از ادمینی برش دار"), "demote"),
    ]
    for phrases, action in moderation:
        if any(p in t for p in phrases):
            if not await group_admin(m):
                return True
            target_user = m.reply_to_message.from_user if m.reply_to_message else None
            if action == "delete":
                if not m.reply_to_message:
                    await m.answer("برای حذف، روی پیام موردنظر Reply کن.")
                else:
                    try:
                        await m.reply_to_message.delete()
                        await m.delete()
                    except Exception:
                        await m.answer("❌ نتونستم پیام رو پاک کنم؛ دسترسی حذف پیام رو بررسی کن.")
                return True
            if not target_user:
                await m.answer("اول روی پیام همون کاربر Reply کن، بعد جمله رو بفرست.")
                return True
            try:
                if action == "ban":
                    await bot.ban_chat_member(m.chat.id, target_user.id)
                    log_action(m.chat.id, m.from_user.id, "ban", target_user.id)
                    await m.answer(f"🚫 {target_user.full_name} مسدود شد.")
                elif action == "kick":
                    await bot.ban_chat_member(m.chat.id, target_user.id)
                    await bot.unban_chat_member(m.chat.id, target_user.id)
                    log_action(m.chat.id, m.from_user.id, "kick", target_user.id)
                    await m.answer(f"👋 {target_user.full_name} از گروه اخراج شد.")
                elif action == "mute":
                    await mute_user(m.chat.id, target_user.id, 60)
                    log_action(m.chat.id, m.from_user.id, "mute", target_user.id)
                    await m.answer(f"🔇 {target_user.full_name} برای یک ساعت ساکت شد.")
                elif action == "unmute":
                    await bot.restrict_chat_member(m.chat.id, target_user.id, permissions=ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True))
                    db.execute("DELETE FROM mutes WHERE chat=? AND user=?", (m.chat.id, target_user.id))
                    db.commit()
                    await m.answer(f"🔊 سکوت {target_user.full_name} برداشته شد.")
                elif action == "warn":
                    row = db.execute("SELECT count FROM warnings WHERE chat=? AND user=?", (m.chat.id, target_user.id)).fetchone()
                    count = (row[0] if row else 0) + 1
                    db.execute("INSERT OR REPLACE INTO warnings VALUES(?,?,?)", (m.chat.id, target_user.id, count))
                    db.commit()
                    log_action(m.chat.id, m.from_user.id, f"warn {count}", target_user.id)
                    if count >= 3:
                        try:
                            await mute_user(m.chat.id, target_user.id, 60)
                        except Exception:
                            pass
                        await m.answer(f"⚠️ {target_user.full_name}: اخطار {count}/3؛ برای یک ساعت محدود شد.")
                    else:
                        await m.answer(f"⚠️ به {target_user.full_name} اخطار داده شد ({count}/3).")
                elif action == "clearwarn":
                    db.execute("DELETE FROM warnings WHERE chat=? AND user=?", (m.chat.id, target_user.id))
                    db.commit()
                    await m.answer("✅ اخطارهای کاربر پاک شد.")
                elif action == "pin":
                    await m.reply_to_message.pin()
                    log_action(m.chat.id, m.from_user.id, "pin", target_user.id)
                    await m.answer("📌 پیام سنجاق شد.")
                elif action == "unpin":
                    await m.reply_to_message.unpin()
                    await m.answer("📌 سنجاق پیام برداشته شد.")
                elif action == "promote":
                    await bot.promote_chat_member(m.chat.id, target_user.id, can_manage_chat=True, can_delete_messages=True, can_restrict_members=True, can_pin_messages=True)
                    log_action(m.chat.id, m.from_user.id, "promote", target_user.id)
                    await m.answer("👑 دسترسی مدیریتی داده شد.")
                elif action == "demote":
                    await bot.promote_chat_member(m.chat.id, target_user.id, can_manage_chat=False, can_delete_messages=False, can_restrict_members=False, can_pin_messages=False)
                    log_action(m.chat.id, m.from_user.id, "demote", target_user.id)
                    await m.answer("✅ دسترسی‌های مدیریتی حذف شد.")
            except Exception as e:
                await m.answer(f"❌ عملیات انجام نشد؛ دسترسی‌های ربات رو بررسی کن. ({e})")
            return True

    # More aliases with arguments.
    if t.startswith("فیلتر کلمه ") or t.startswith("این کلمه رو فیلتر کن "):
        if not await group_admin(m):
            return True
        word = raw.split(maxsplit=2)[-1].strip().lower()
        if word:
            db.execute("INSERT OR IGNORE INTO filters VALUES(?,?)", (m.chat.id, word))
            db.commit()
            await m.answer(f"✅ کلمه «{word}» فیلتر شد.")
        return True
    if t.startswith("فیلتر رو حذف کن ") or t.startswith("فیلتر کلمه رو بردار "):
        if not await group_admin(m):
            return True
        word = raw.split(maxsplit=3)[-1].strip().lower()
        db.execute("DELETE FROM filters WHERE chat=? AND word=?", (m.chat.id, word))
        db.commit()
        await m.answer(f"✅ فیلتر «{word}» حذف شد.")
        return True
    if t.startswith("قوانین رو تنظیم کن ") or t.startswith("قوانین گروه رو بذار "):
        if not await group_admin(m):
            return True
        new_rules = raw.split(maxsplit=3)[-1].strip()
        set_chat_text(m.chat.id, "rules", new_rules)
        await m.answer("📜 قوانین گروه ذخیره شد.")
        return True
    if t.startswith("خوشامد رو تنظیم کن ") or t.startswith("متن خوشامد رو بذار "):
        if not await group_admin(m):
            return True
        welcome_text = raw.split(maxsplit=4)[-1].strip()
        set_chat_text(m.chat.id, "welcome_text", welcome_text)
        await m.answer("👋 متن خوشامد ذخیره شد.")
        return True

    # Additional conversational aliases for utility commands.
    if any(x in t for x in ("شناسه من چیه", "آیدی من", "شناسه گروه", "آیدی گروه")):
        await m.answer(f"🆔 شناسه کاربر: {m.from_user.id}\n💬 شناسه گفتگو: {m.chat.id}")
        return True
    if any(x in t for x in ("اطلاعات گروه", "مشخصات گروه", "درباره این گروه")):
        await m.answer(f"💬 نام گفتگو: {m.chat.title or 'گفتگوی خصوصی'}\n🆔 شناسه: {m.chat.id}\nنوع: {m.chat.type}")
        return True
    if any(x in t for x in ("حافظه چت رو پاک کن", "حافظه گفتگو رو پاک کن", "حافظه هوش مصنوعی رو پاک کن")):
        db.execute("DELETE FROM ai_history WHERE chat=? AND user=?", (m.chat.id, m.from_user.id))
        db.commit()
        await m.answer("🧹 حافظه گفتگوی خودت پاک شد.")
        return True
    if any(x in t for x in ("لحن رو خاکی کن", "با لحن خاکی حرف بزن", "خودمونی حرف بزن")):
        style = "khaki"
    elif any(x in t for x in ("لحن رو شوخ کن", "بامزه حرف بزن", "شوخ حرف بزن")):
        style = "funny"
    elif any(x in t for x in ("لحن رو ریلکس کن", "آروم حرف بزن")):
        style = "chill"
    elif any(x in t for x in ("لحن رو حرفه ای کن", "حرفه ای حرف بزن")):
        style = "pro"
    elif any(x in t for x in ("لحن رو انگیزشی کن", "انگیزشی حرف بزن")):
        style = "coach"
    elif any(x in t for x in ("لحن رو گیمر کن", "مثل گیمر حرف بزن")):
        style = "gamer"
    elif any(x in t for x in ("کوتاه جواب بده", "مختصر جواب بده")):
        style = "short"
    else:
        style = None
    if style:
        enabled, _ = ai_settings(m.chat.id)
        db.execute("INSERT INTO ai_settings(chat,enabled,style) VALUES(?,?,?) ON CONFLICT(chat) DO UPDATE SET style=excluded.style", (m.chat.id, int(enabled), style))
        db.commit()
        await m.answer(f"🎭 باشه، از این به بعد با لحن «{AI_STYLES[style][0]}» جواب می‌دم.")
        return True
    if any(x in t for x in ("یادداشت ها رو نشون بده", "یادداشت‌ها رو نشون بده", "فهرست یادداشت ها", "یادداشت‌های ذخیره شده")):
        rows = db.execute("SELECT name FROM notes WHERE chat=? ORDER BY name", (m.chat.id,)).fetchall()
        await m.answer("📝 یادداشت‌های ذخیره‌شده:\n" + ("\n".join("• " + row[0] for row in rows) or "هنوز یادداشتی ذخیره نشده."))
        return True
    if (t.startswith("یادداشت ") and not any(x in t for x in (" رو بیار ", " رو نشون بده "))) or t.startswith("یه یادداشت ذخیره کن "):
        if not await group_admin(m):
            return True
        parts = raw.split(maxsplit=2)
        if len(parts) < 3:
            await m.answer("برای ذخیره یادداشت بگو: «یادداشت نام متن یادداشت»")
            return True
        db.execute("INSERT OR REPLACE INTO notes VALUES(?,?,?)", (m.chat.id, parts[1].lower(), parts[2]))
        db.commit()
        await m.answer("📝 یادداشت ذخیره شد.")
        return True
    if t.startswith("یادداشت رو بیار ") or t.startswith("یادداشت ") and " رو نشون بده" in t:
        name = raw.split()[-1].lower()
        row = db.execute("SELECT text FROM notes WHERE chat=? AND name=?", (m.chat.id, name)).fetchone()
        await m.answer(row[0] if row else "❌ این یادداشت رو پیدا نکردم.")
        return True
    if any(x in t for x in ("این کاربر رو از بن دربیار", "رفع مسدودی این کاربر", "بن این کاربر رو بردار")):
        if not await group_admin(m):
            return True
        target_user = m.reply_to_message.from_user if m.reply_to_message else None
        if not target_user:
            await m.answer("روی پیام کاربر Reply کن و دوباره بگو.")
            return True
        try:
            await bot.unban_chat_member(m.chat.id, target_user.id)
            log_action(m.chat.id, m.from_user.id, "unban", target_user.id)
            await m.answer(f"✅ مسدودی {target_user.full_name} برداشته شد.")
        except Exception as e:
            await m.answer(f"❌ رفع مسدودی انجام نشد: {e}")
        return True
    if any(x in t for x in ("این کاربر رو گزارش کن", "از این کاربر شکایت دارم", "گزارش تخلف این کاربر")):
        target_user = m.reply_to_message.from_user if m.reply_to_message else None
        reason = raw
        db.execute("INSERT INTO reports(chat,reporter,target,reason,created) VALUES(?,?,?,?,?)",
                   (m.chat.id, m.from_user.id, target_user.id if target_user else 0, reason[:1000], datetime.utcnow().isoformat()))
        db.commit()
        await m.answer("🚨 گزارشت ثبت شد؛ ادمین‌ها می‌تونن بررسیش کنن.")
        return True

    # Personal utilities — independent of group moderation.
    if any(x in t for x in ("تاس بنداز", "یه تاس بنداز", "تاس بریز")):
        await m.answer(f"🎲 نتیجه تاس: {random.randint(1, 6)}")
        return True
    if any(x in t for x in ("شیر یا خط", "سکه بنداز", "شیرخط")):
        await m.answer("🪙 " + random.choice(["شیر", "خط"]))
        return True
    if any(x in t for x in ("جوک بگو", "یه جوک بگو", "جوک تعریف کن")):
        jokes = [
            "به کامپیوتر گفتم یه کم استراحت کن؛ گفت اول همه پنجره‌هامو ببند! 😄",
            "برنامه‌نویس چرا دیر خوابید؟ چون داشت باگ‌های خوابش رو دیباگ می‌کرد! 🐛",
            "گفتم اینترنت چرا کندی؟ گفت دارم با زندگی سینک می‌شم! 😂",
        ]
        await m.answer(random.choice(jokes))
        return True
    if any(x in t for x in ("رمز بساز", "یه رمز بساز", "رمز تصادفی")):
        alphabet = string.ascii_letters + string.digits + "!@#$%_-+"
        password = "".join(secrets.choice(alphabet) for _ in range(16))
        await m.answer("🔐 رمز تصادفی ۱۶ کاراکتری:\n<code>" + password + "</code>", parse_mode="HTML")
        return True
    if any(x in t for x in ("پروفایل من", "اطلاعات من", "حساب کاربری من")):
        row = db.execute("SELECT joined FROM users WHERE id=?", (m.from_user.id,)).fetchone()
        reminders_n = db.execute("SELECT COUNT(*) FROM reminders WHERE user=?", (m.from_user.id,)).fetchone()[0]
        ai_n = db.execute("SELECT COUNT(*) FROM ai_history WHERE user=? AND role='user'", (m.from_user.id,)).fetchone()[0]
        await m.answer(
            f"👤 پروفایل تو\nنام: {m.from_user.full_name}\n"
            f"شناسه: <code>{m.from_user.id}</code>\n"
            f"نام کاربری: @{m.from_user.username or 'ندارد'}\n"
            f"یادآوری‌های فعال: {reminders_n}\nپیام‌های گفتگوی AI ذخیره‌شده: {ai_n}",
            parse_mode="HTML"
        )
        return True
    if any(x in t for x in ("یادآوری‌هام", "یادآوری های من", "یادآوری‌های من", "یادآوری هام رو نشون بده")):
        rows = db.execute("SELECT id,text,due FROM reminders WHERE user=? ORDER BY due LIMIT 10", (m.from_user.id,)).fetchall()
        if not rows:
            answer = "⏰ یادآوری فعالی نداری."
        else:
            answer = "⏰ یادآوری‌های بعدی تو:\n" + "\n".join(
                f"#{rid} — {txt} (حدود {max(0, int((due-time.time())/60))} دقیقه دیگه)"
                for rid, txt, due in rows
            )
        await m.answer(answer)
        return True
    if any(x in t for x in ("آخرین یادآوری رو حذف کن", "آخرین یادآوری رو پاک کن", "یادآوری آخر رو حذف کن")):
        row = db.execute("SELECT id FROM reminders WHERE user=? ORDER BY due DESC LIMIT 1", (m.from_user.id,)).fetchone()
        if row:
            db.execute("DELETE FROM reminders WHERE id=?", (row[0],))
            db.commit()
            await m.answer("🗑 آخرین یادآوری‌ات حذف شد.")
        else:
            await m.answer("یادآوری‌ای برای حذف نداری.")
        return True
    if t.startswith("یادآوری ") or t.startswith("یادم بنداز "):
        match = re.match(r"^(?:یادآوری|یادم بنداز)\s+(\d+)\s*(دقیقه|ساعت)\s*(?:بعد|دیگه)?\s+(.+)$", raw.strip())
        if not match:
            await m.answer("⏰ این‌طوری بگو: «یادآوری 10 دقیقه بعد آب بخور» یا «یادم بنداز 2 ساعت دیگه درس بخون»")
            return True
        amount, unit, reminder_text = match.groups()
        amount = int(amount)
        if amount < 1 or amount > 10080:
            await m.answer("⏰ زمان باید بین ۱ دقیقه تا ۷ روز باشه.")
            return True
        delay = amount * (3600 if unit == "ساعت" else 60)
        due = time.time() + delay
        db.execute("INSERT INTO reminders(chat,user,text,due,created) VALUES(?,?,?,?,?)",
                   (m.chat.id, m.from_user.id, reminder_text[:500], due, time.time()))
        db.commit()
        await m.answer(f"⏰ یادآوری ثبت شد؛ حدود {amount} {unit} دیگه بهت پیام می‌دم.\nمتن: {reminder_text[:300]}")
        return True
    if any(x in t for x in ("نظرسنجی بساز", "نظرسنجی ایجاد کن")):
        payload = raw.split(maxsplit=1)[1] if len(raw.split(maxsplit=1)) > 1 else ""
        parts = [x.strip() for x in payload.split("|") if x.strip()]
        if len(parts) < 3 or len(parts) > 11:
            await m.answer("📊 قالب: «نظرسنجی بساز | سؤال | گزینه اول | گزینه دوم» (حداقل دو گزینه، حداکثر ده گزینه)")
            return True
        question, options = parts[0], parts[1:]
        try:
            await bot.send_poll(m.chat.id, question=question[:300], options=[x[:100] for x in options[:10]], is_anonymous=True)
        except Exception:
            await m.answer("❌ ساخت نظرسنجی انجام نشد؛ دوباره با قالب نمونه امتحان کن.")
        return True
    if t.startswith("حساب کن ") or t.startswith("محاسبه کن ") or t.startswith("حسابش کن "):
        expression = raw.split(maxsplit=1)[1].replace(",", ".").replace("×", "*").replace("÷", "/").replace("^", "**")
        try:
            result = safe_calculate(expression)
            await m.answer(f"🧮 نتیجه: <code>{result}</code>", parse_mode="HTML")
        except ZeroDivisionError:
            await m.answer("🧮 تقسیم بر صفر ممکن نیست.")
        except Exception:
            await m.answer("🧮 عبارت رو ساده و عددی بنویس؛ مثلاً «حساب کن 12 * (4 + 3)».")
        return True

    # Help is always available.
    if any(x in t for x in ("راهنمای ربات", "چه کارهایی بلدی", "چطور باهات کار کنم", "کمک میخوام")):
        await m.answer("🙂 لازم نیست دستورها رو حفظ کنی! مثلاً بگو:\n• ربات روشن / ربات خاموش\n• ضدلینک رو روشن کن\n• ضداسپم رو خاموش کن\n• آمار گروه رو بگو\n• قوانین گروه چیه؟\n• «سؤال ساعت کاری چیه؟» برای پاسخ آماده (بدون AI)\n• پنل مدیریت رو باز کن\n• روی پیام کاربر Reply کن و بگو «این کاربر رو اخراج کن» یا «بهش اخطار بده»\n\nبرای بقیه گفتگوها هم عادی باهام حرف بزن.")
        return True
    return False


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

    if not m.text:
        return
    if await natural_command(m):
        return

    if m.chat.type == "private":
        if m.text.startswith("/"):
            return
        enabled, _style = ai_settings(m.chat.id)
        if enabled:
            answer = await ai_reply(m.chat.id, m.from_user.id, m.text, m.from_user.full_name)
            if answer:
                await m.answer(answer)
        return

    me = await bot.get_me()
    addressed = (m.reply_to_message and m.reply_to_message.from_user and m.reply_to_message.from_user.id == me.id) or (me.username and f"@{me.username.lower()}" in m.text.lower())
    if addressed and not m.text.startswith("/"):
        cleaned = m.text.replace(f"@{me.username}", "").strip() if me.username else m.text
        enabled, _style = ai_settings(m.chat.id)
        if enabled:
            answer = await ai_reply(m.chat.id, m.from_user.id, cleaned, m.from_user.full_name)
            if answer:
                await m.reply(answer)
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
            due_reminders = db.execute("SELECT id,chat,user,text FROM reminders WHERE due<=? ORDER BY due LIMIT 50", (now,)).fetchall()
            for reminder_id, chat_id, user_id, reminder_text in due_reminders:
                try:
                    await bot.send_message(chat_id, f"⏰ یادآوری تو:\n{reminder_text}")
                except Exception:
                    # If the original chat is unavailable, try sending privately.
                    try:
                        await bot.send_message(user_id, f"⏰ یادآوری تو:\n{reminder_text}")
                    except Exception:
                        pass
                db.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
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

    await set_bot_commands()
    maintenance_task = asyncio.create_task(maintenance())
    try:
        await dp.start_polling(bot)
    finally:
        maintenance_task.cancel()
        await bot.session.close()
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
