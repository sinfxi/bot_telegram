import asyncio, logging, os, secrets, sqlite3, time
from contextlib import closing, asynccontextmanager
from pathlib import Path
from html import escape
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
DB_PATH = Path(os.getenv("DB_PATH", "/data/bot.sqlite3"))
PORT = int(os.getenv("PORT", "8000"))
DELETE_URL = "https://my.telegram.org/auth?to=delete"
if not BOT_TOKEN: raise RuntimeError("Set BOT_TOKEN in environment variables.")
if not ADMIN_PASSWORD: raise RuntimeError("Set a strong ADMIN_PASSWORD in environment variables.")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("delete-assistant")

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH, timeout=15)
def init_db():
    with closing(connect()) as db:
        db.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,event_type TEXT NOT NULL,created_at INTEGER NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at)")
        db.commit()
def register(uid):
    now = int(time.time())
    with closing(connect()) as db:
        db.execute("INSERT INTO users VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET last_seen=excluded.last_seen",(uid,now,now)); db.commit()
def event(uid, kind):
    if kind not in {"start","guide_started","guide_confirmed","cancelled","help","security"}: return
    with closing(connect()) as db:
        db.execute("INSERT INTO events(user_id,event_type,created_at) VALUES(?,?,?)",(uid,kind,int(time.time()))); db.commit()
def stats():
    today = int(time.time()) // 86400 * 86400
    with closing(connect()) as db:
        users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active = db.execute("SELECT COUNT(*) FROM users WHERE last_seen>=?",(today,)).fetchone()[0]
        counts = dict(db.execute("SELECT event_type,COUNT(*) FROM events GROUP BY event_type").fetchall())
        recent = db.execute("SELECT event_type,created_at FROM events ORDER BY id DESC LIMIT 12").fetchall()
    return users, active, counts, recent

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
def keyboard(rows): return InlineKeyboardMarkup(inline_keyboard=rows)
def home_kb(): return keyboard([[InlineKeyboardButton(text="🗑 راهنمای حذف حساب",callback_data="delete:start")],[InlineKeyboardButton(text="🔐 امنیت",callback_data="security"),InlineKeyboardButton(text="❓ راهنما",callback_data="help")]])
def confirm_kb(): return keyboard([[InlineKeyboardButton(text="✅ بله، ادامه راهنما",callback_data="delete:confirm")],[InlineKeyboardButton(text="❌ خیر، انصراف",callback_data="delete:cancel")],[InlineKeyboardButton(text="🏠 منوی اصلی",callback_data="home")]])
def official_kb(): return keyboard([[InlineKeyboardButton(text="🌐 صفحه رسمی تلگرام",url=DELETE_URL)],[InlineKeyboardButton(text="🏠 منوی اصلی",callback_data="home")]])
def back_kb(): return keyboard([[InlineKeyboardButton(text="🏠 منوی اصلی",callback_data="home")]])
HOME = """<b>🛡 دستیار راهنمای حذف حساب تلگرام</b>

• راهنمای مرحله‌به‌مرحله
• نکات امنیتی
• امکان لغو و بازگشت

<b>⚠️ مهم:</b> حذف حساب ممکن است غیرقابل‌بازگشت باشد. این ربات حساب را حذف نمی‌کند و هرگز نباید کد ورود یا رمز دومرحله‌ای را از تو بخواهد."""
async def screen(target, text, kb):
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text,reply_markup=kb); return
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower(): return
        await target.message.answer(text,reply_markup=kb)
    else: await target.answer(text,reply_markup=kb)

@dp.message(CommandStart())
async def start(m: Message):
    register(m.from_user.id); event(m.from_user.id,"start")
    await m.answer(HOME,reply_markup=home_kb())
@dp.message(Command("cancel"))
async def cancel_cmd(m: Message):
    register(m.from_user.id); event(m.from_user.id,"cancelled")
    await m.answer("عملیات لغو شد؛ هیچ حسابی از طریق ربات حذف نشده است.",reply_markup=home_kb())
@dp.message(Command("help"))
async def help_cmd(m: Message):
    await m.answer("از منوی ربات استفاده کن. /start منوی اصلی است.",reply_markup=home_kb())
@dp.message(Command("stats"))
async def stats_cmd(m: Message):
    if not ADMIN_ID or m.from_user.id != ADMIN_ID:
        await m.answer("⛔ اجازه دسترسی نداری."); return
    u,a,c,_ = stats()
    await m.answer(f"<b>آمار</b>\nکاربران: {u}\nفعال امروز: {a}\nشروع راهنما: {c.get('guide_started',0)}\nتأیید ادامه: {c.get('guide_confirmed',0)}\nانصراف: {c.get('cancelled',0)}\n\nاین آمار به معنی حذف واقعی حساب نیست.")
@dp.callback_query(F.data=="home")
async def home(c: CallbackQuery):
    register(c.from_user.id); await c.answer(); await screen(c,HOME,home_kb())
@dp.callback_query(F.data=="delete:start")
async def delete_start(c: CallbackQuery):
    register(c.from_user.id); event(c.from_user.id,"guide_started"); await c.answer()
    await screen(c,"""<b>🗑 پیش از ادامه</b>

۱. حذف ممکن است غیرقابل‌بازگشت باشد.
۲. اطلاعات و دسترسی‌های مرتبط ممکن است از دست بروند.
۳. فرایند نهایی فقط در سایت رسمی انجام می‌شود.
۴. کد ورود یا رمز دومرحله‌ای را در ربات وارد نکن.

می‌خواهی راهنمای ادامه را ببینی؟""",confirm_kb())
@dp.callback_query(F.data=="delete:confirm")
async def confirm(c: CallbackQuery):
    register(c.from_user.id); event(c.from_user.id,"guide_confirmed"); await c.answer()
    await screen(c,"""<b>🔐 ادامه در صفحه رسمی</b>

۱. صفحه رسمی تلگرام را باز کن.
۲. دستورالعمل ورود همان سایت را دنبال کن.
۳. کد را فقط در سایت رسمی وارد کن.
۴. پیامدها را بررسی و تصمیم نهایی را خودت تأیید کن.

ربات حذف را انجام نمی‌دهد و نمی‌تواند نتیجه حذف را تأیید کند.""",official_kb())
@dp.callback_query(F.data=="delete:cancel")
async def cancel(c: CallbackQuery):
    register(c.from_user.id); event(c.from_user.id,"cancelled"); await c.answer("لغو شد")
    await screen(c,"✅ عملیات لغو شد. به منوی اصلی برگشتی.",home_kb())
@dp.callback_query(F.data=="security")
async def security(c: CallbackQuery):
    register(c.from_user.id); event(c.from_user.id,"security"); await c.answer()
    await screen(c,"""<b>🔐 نکات امنیتی</b>

• کد ورود را برای هیچ ربات یا فردی نفرست.
• رمز دومرحله‌ای را محرمانه نگه دار.
• آدرس سایت را قبل از واردکردن اطلاعات بررسی کن.
• از لینک‌های ناشناس دوری کن.
• این ربات به کد ورود یا رمز عبور نیاز ندارد.""",back_kb())
@dp.callback_query(F.data=="help")
async def help_cb(c: CallbackQuery):
    register(c.from_user.id); event(c.from_user.id,"help"); await c.answer()
    await screen(c,"<b>❓ راهنما</b>\n/start — منوی اصلی\n/cancel — لغو\n/help — راهنما\n/stats — آمار مدیر\n\nحذف حساب در سایت رسمی و توسط خود کاربر انجام می‌شود.",back_kb())
@dp.message()
async def fallback(m: Message):
    register(m.from_user.id); await m.answer("برای ادامه از دکمه‌های منو استفاده کن.",reply_markup=home_kb())

auth = HTTPBasic()
def admin_auth(creds: HTTPBasicCredentials = Depends(auth)):
    if not (secrets.compare_digest(creds.username,ADMIN_USER) and secrets.compare_digest(creds.password,ADMIN_PASSWORD)):
        raise HTTPException(status_code=401,detail="Invalid credentials",headers={"WWW-Authenticate":"Basic"})
    return creds.username

async def bot_runner():
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
@asynccontextmanager
async def lifespan(app):
    init_db()
    task = asyncio.create_task(bot_runner())
    app.state.bot_task = task
    yield
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass
    await bot.session.close()
app = FastAPI(title="Telegram Delete Assistant",lifespan=lifespan)
@app.get("/health",response_class=PlainTextResponse)
async def health(): return "ok"
@app.get("/",response_class=HTMLResponse)
async def dashboard(_=Depends(admin_auth)):
    u,a,c,recent = stats()
    names={"start":"شروع ربات","guide_started":"شروع راهنما","guide_confirmed":"تأیید ادامه","cancelled":"انصراف","help":"راهنما","security":"نکات امنیتی"}
    rows="".join(f"<tr><td>{escape(names.get(k,k))}</td><td>{time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(ts))}</td></tr>" for k,ts in recent) or "<tr><td colspan=2>رویدادی ثبت نشده است</td></tr>"
    return HTMLResponse(f"""<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>پنل مدیریت</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#101510;color:#edf2e8;font-family:Tahoma,Arial}}main{{max-width:1000px;margin:36px auto;padding:0 18px}}header,.grid{{display:flex;gap:14px;flex-wrap:wrap}}header{{align-items:center;justify-content:space-between}}h1{{font-size:26px}}p,.muted{{color:#a9b6a4;line-height:1.8}}.grid{{margin:24px 0}}.card,section{{background:#1a211a;border:1px solid #303c30;border-radius:16px;padding:20px}}.card{{flex:1;min-width:160px}}.value{{font-size:30px;font-weight:bold;margin-top:12px;color:#b6d58b}}section{{margin-top:18px;overflow:auto}}table{{width:100%;border-collapse:collapse}}td,th{{padding:12px;text-align:right;border-bottom:1px solid #303c30}}th{{color:#b6d58b}}small{{color:#a9b6a4}}</style><main><header><div><h1>🛡 پنل مدیریت دستیار تلگرام</h1><p>آمار کلی و رویدادهای اخیر</p></div><span>● سرویس فعال</span></header><div class="grid">
    <div class="card">کاربران ثبت‌شده<div class="value">{u}</div></div><div class="card">فعال امروز<div class="value">{a}</div></div><div class="card">شروع راهنما<div class="value">{c.get('guide_started',0)}</div></div><div class="card">تأیید ادامه<div class="value">{c.get('guide_confirmed',0)}</div></div><div class="card">انصراف‌ها<div class="value">{c.get('cancelled',0)}</div></div></div>
    <section><h2>رویدادهای اخیر</h2><table><tr><th>رویداد</th><th>زمان</th></tr>{rows}</table></section><section><h2>حریم خصوصی</h2><p>آمار مربوط به تعامل با ربات است، نه حذف واقعی حساب‌ها. ربات شماره تلفن، کد ورود یا رمز دومرحله‌ای را ذخیره نمی‌کند. پنل را فقط با HTTPS و رمز قوی منتشر کن.</p></section><small>Telegram Account Deletion Assistant</small></main></html>""")
if __name__=="__main__":
    import uvicorn
    uvicorn.run("app:app",host="0.0.0.0",port=PORT,reload=False)
