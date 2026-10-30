import asyncio
import logging
import os
from contextlib import asynccontextmanager

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from fastapi import FastAPI
from fastapi.responses import JSONResponse

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("zeus-independent-bot")

BOT_TOKEN = os.getenv("ZEUS_BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ZEUS_ADMIN_ID", "0") or "0")
CF_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
bot = None
dp = Dispatcher()
polling_task = None


def is_admin(user_id: int) -> bool:
    return ADMIN_ID > 0 and user_id == ADMIN_ID


def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔐 بررسی توکن Cloudflare", callback_data="cf:verify")],
        [InlineKeyboardButton(text="👤 اطلاعات حساب", callback_data="cf:account"),
         InlineKeyboardButton(text="🌐 فهرست دامنه‌ها", callback_data="cf:zones")],
        [InlineKeyboardButton(text="⚙️ فهرست Workerها", callback_data="cf:workers")],
        [InlineKeyboardButton(text="ℹ️ راهنما", callback_data="help")]
    ])


async def cf_get(path: str):
    if not CF_TOKEN:
        return None, "توکن Cloudflare تنظیم نشده است. مقدار CLOUDFLARE_API_TOKEN را در Environment سرویس Render ثبت کن."
    timeout = aiohttp.ClientTimeout(total=15)
    headers = {"Authorization": f"Bearer {CF_TOKEN}", "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get("https://api.cloudflare.com/client/v4" + path) as response:
                data = await response.json(content_type=None)
                if response.status >= 400 or not data.get("success", False):
                    errors = data.get("errors") or []
                    msg = "; ".join(str(e.get("message", "خطای ناشناخته")) for e in errors[:3])
                    return None, f"درخواست Cloudflare ناموفق بود (HTTP {response.status}). {msg}".strip()
                return data, None
    except asyncio.TimeoutError:
        return None, "اتصال به Cloudflare بیش از حد طول کشید؛ دوباره تلاش کن."
    except Exception:
        log.exception("Cloudflare request failed")
        return None, "خطا هنگام اتصال به Cloudflare؛ جزئیات حساس در پاسخ نمایش داده نمی‌شود."


@dp.message(CommandStart())
async def start(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("⛔ دسترسی مجاز نیست. این ربات فقط برای مدیر تنظیم‌شده فعال است.")
        return
    await message.answer(
        "سلام! 👋\n\nبه دستیار مستقل مدیریت Cloudflare خوش آمدی. "
        "این نسخه از ابتدا ساخته شده و کد ZEUS را کپی نمی‌کند.\n\n"
        "از منو برای بررسی دسترسی API و مشاهده اطلاعات حساب، دامنه‌ها و Workerها استفاده کن.",
        reply_markup=main_keyboard()
    )


@dp.message()
async def deny_messages(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("⛔ دسترسی مجاز نیست.")
        return
    await message.answer("از دکمه‌های منو استفاده کن.", reply_markup=main_keyboard())


@dp.callback_query()
async def callbacks(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("دسترسی مجاز نیست.", show_alert=True)
        return
    action = callback.data or ""
    await callback.answer()
    if action == "help":
        await callback.message.answer(
            "راهنما:\n• توکن را فقط در Environment سرویس Render قرار بده.\n"
            "• برای این قابلیت‌ها توکن Cloudflare باید دسترسی Read مناسب داشته باشد.\n"
            "• این نسخه فقط اطلاعات را می‌خواند؛ ساخت یا حذف منابع هنوز فعال نیست.",
            reply_markup=main_keyboard()
        )
        return
    if action == "cf:verify":
        data, error = await cf_get("/user/tokens/verify")
        if error:
            await callback.message.answer("⚠️ " + error, reply_markup=main_keyboard())
        else:
            result = data.get("result") or {}
            await callback.message.answer(
                "✅ توکن Cloudflare معتبر است.\n"
                f"وضعیت: {result.get('status', 'نامشخص')}",
                reply_markup=main_keyboard()
            )
        return
    if action == "cf:account":
        data, error = await cf_get("/user")
        if error:
            await callback.message.answer("⚠️ " + error, reply_markup=main_keyboard())
        else:
            user = data.get("result") or {}
            await callback.message.answer(
                "👤 اطلاعات حساب Cloudflare\n"
                f"نام: {user.get('first_name', '')} {user.get('last_name', '')}\n"
                f"ایمیل: {user.get('email', 'نامشخص')}\n"
                f"شناسه: {user.get('id', 'نامشخص')}",
                reply_markup=main_keyboard()
            )
        return
    if action == "cf:zones":
        data, error = await cf_get("/zones?per_page=50&order=name")
        if error:
            await callback.message.answer("⚠️ " + error, reply_markup=main_keyboard())
        else:
            zones = data.get("result") or []
            if not zones:
                text = "دامنه‌ای پیدا نشد یا توکن اجازه مشاهده دامنه‌ها را ندارد."
            else:
                lines = ["🌐 دامنه‌ها (حداکثر ۵۰ مورد):"]
                for zone in zones[:50]:
                    lines.append(f"• {zone.get('name', 'بدون نام')} — {zone.get('status', 'نامشخص')}")
                text = "\n".join(lines)
            await callback.message.answer(text[:4000], reply_markup=main_keyboard())
        return
    if action == "cf:workers":
        data, error = await cf_get("/accounts?per_page=50")
        if error:
            await callback.message.answer("⚠️ " + error, reply_markup=main_keyboard())
            return
        accounts = data.get("result") or []
        if not accounts:
            await callback.message.answer("حسابی پیدا نشد یا توکن اجازه مشاهده حساب‌ها را ندارد.", reply_markup=main_keyboard())
            return
        lines = ["⚙️ فهرست Workerها:"]
        total = 0
        for account in accounts[:20]:
            account_id = account.get("id")
            if not account_id:
                continue
            workers, worker_error = await cf_get(f"/accounts/{account_id}/workers/scripts")
            if worker_error:
                lines.append(f"• {account.get('name', account_id)}: دسترسی خواندن Workerها موجود نیست.")
                continue
            scripts = workers.get("result") or []
            lines.append(f"• {account.get('name', account_id)}: {len(scripts)} مورد")
            for script in scripts[:10]:
                lines.append(f"   - {script.get('id', script.get('tag', 'بدون نام'))}")
                total += 1
        if len(lines) == 1:
            lines.append("Worker قابل نمایشی پیدا نشد.")
        await callback.message.answer("\n".join(lines)[:4000], reply_markup=main_keyboard())
        return
    await callback.message.answer("این گزینه شناخته نشد.", reply_markup=main_keyboard())


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot, polling_task
    if BOT_TOKEN and ADMIN_ID > 0:
        bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
        log.info("Telegram polling started")
    else:
        log.warning("Telegram bot is not active: set ZEUS_BOT_TOKEN and ZEUS_ADMIN_ID in Render environment")
    yield
    if polling_task:
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
    if bot:
        await bot.session.close()


app = FastAPI(title="Independent Cloudflare Telegram Assistant", version="1.0.0", lifespan=lifespan)


@app.get("/")
async def root():
    return {"service": "independent-cloudflare-telegram-assistant", "status": "ok", "telegram_configured": bool(BOT_TOKEN and ADMIN_ID > 0)}


@app.get("/health")
async def health():
    configured = bool(BOT_TOKEN and ADMIN_ID > 0)
    return JSONResponse(
        status_code=200 if configured else 503,
        content={"status": "ok" if configured else "needs_configuration",
                 "telegram_configured": configured,
                 "cloudflare_token_configured": bool(CF_TOKEN)}
    )
