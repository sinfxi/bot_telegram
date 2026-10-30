import asyncio
import html
import logging
import os
from collections import defaultdict
from contextlib import asynccontextmanager

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from fastapi import FastAPI
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("fxi-ai-chat")

BOT_TOKEN = os.getenv("ZEUS_BOT_TOKEN", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "llama-3.3-70b-versatile").strip()
ADMIN_ID = int(os.getenv("ZEUS_ADMIN_ID", "0") or "0")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
SYSTEM_PROMPT = os.getenv(
    "AI_SYSTEM_PROMPT",
    "تو یک دستیار هوش مصنوعی فارسی‌زبان، دقیق، مفید و صمیمی هستی. "
    "به زبان کاربر پاسخ بده؛ پاسخ‌ها را روشن و کاربردی بنویس. "
    "اگر چیزی را نمی‌دانی، صادقانه بگو و اطلاعات یا منبع جعلی نساز. "
    "برای درخواست‌های برنامه‌نویسی، راهکار قابل اجرا و کد خوانا ارائه کن.",
)
MAX_HISTORY_MESSAGES = 16
MAX_MESSAGE_CHARS = 12000
histories = defaultdict(list)
history_locks = defaultdict(asyncio.Lock)
bot = None
dp = Dispatcher()
polling_task = None


def main_keyboard_text() -> str:
    return (
        "💬 فقط کافیه پیام بدی تا با هم گفتگو کنیم.\n\n"
        "دستورها:\n"
        "/new — شروع گفت‌وگوی تازه\n"
        "/help — راهنما"
    )


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "سلام! 👋 من دستیار هوش مصنوعی‌ات هستم.\n\n"
        "می‌تونی درباره برنامه‌نویسی، درس، فناوری، نوشتن، ایده‌پردازی یا هر موضوع مجاز دیگه‌ای باهام گفتگو کنی. "
        "پیام‌هات رو همین‌جا بفرست و برای پاک‌کردن سابقه گفت‌وگو /new رو بزن.\n\n"
        + main_keyboard_text()
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "راهنمای استفاده 🤖\n\n"
        "• پیام متنی بفرست و پاسخ هوش مصنوعی را دریافت کن.\n"
        "• برای شروع از صفر، /new را بزن.\n"
        "• هر گفت‌وگو سابقه جداگانه دارد.\n"
        "• ممکن است پاسخ‌ها اشتباه باشند؛ اطلاعات مهم را بررسی کن.\n\n"
        "این ربات از API مدل زبانی استفاده می‌کند و برای پاسخ‌گویی به اتصال اینترنت و کلید API نیاز دارد."
    )


@dp.message(Command("new"))
@dp.message(Command("reset"))
async def reset_chat(message: Message):
    if not message.from_user:
        return
    histories[message.from_user.id].clear()
    await message.answer("🧹 گفت‌وگوی قبلی پاک شد. از اینجا به بعد از نو شروع می‌کنیم!")


async def ask_ai(user_id: int, user_text: str) -> str:
    if not GROQ_API_KEY:
        return (
            "⚠️ اتصال هوش مصنوعی هنوز تنظیم نشده است. مدیر ربات باید متغیر "
            "GROQ_API_KEY را در Environment سرویس Render قرار دهد."
        )

    async with history_locks[user_id]:
        history = histories[user_id]
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history[-MAX_HISTORY_MESSAGES:])
        messages.append({"role": "user", "content": user_text})

        timeout = aiohttp.ClientTimeout(total=75, connect=15)
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": AI_MODEL,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1800,
        }

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(GROQ_URL, headers=headers, json=payload) as response:
                    data = await response.json(content_type=None)
                    if response.status == 401:
                        log.error("Groq API authentication failed (401)")
                        return "⚠️ کلید API هوش مصنوعی معتبر نیست. مدیر باید مقدار GROQ_API_KEY را بررسی کند."
                    if response.status == 429:
                        log.warning("Groq API rate limit reached")
                        return "⏳ تعداد درخواست‌ها فعلاً زیاد شده؛ کمی بعد دوباره امتحان کن."
                    if response.status >= 400:
                        error = data.get("error", {}) if isinstance(data, dict) else {}
                        message_text = error.get("message", "") if isinstance(error, dict) else ""
                        log.error("Groq API returned HTTP %s: %s", response.status, message_text[:300])
                        return f"⚠️ سرویس هوش مصنوعی پاسخ نداد (کد {response.status}). کمی بعد دوباره امتحان کن."

                    choices = data.get("choices") or []
                    answer = (choices[0].get("message") or {}).get("content", "").strip() if choices else ""
                    if not answer:
                        return "پاسخی دریافت نکردم؛ لطفاً دوباره سؤال را بفرست."

                    history.extend([
                        {"role": "user", "content": user_text},
                        {"role": "assistant", "content": answer},
                    ])
                    del history[:-MAX_HISTORY_MESSAGES]
                    return answer
        except asyncio.TimeoutError:
            log.warning("Groq API request timed out")
            return "⏳ پاسخ‌گویی بیش از حد طول کشید؛ دوباره تلاش کن."
        except aiohttp.ClientError:
            log.exception("Network error while calling Groq API")
            return "⚠️ در اتصال به سرویس هوش مصنوعی مشکلی پیش آمد؛ کمی بعد دوباره امتحان کن."
        except Exception:
            log.exception("Unexpected error while handling AI request")
            return "⚠️ یک خطای پیش‌بینی‌نشده رخ داد. لطفاً دوباره تلاش کن."


async def send_long_message(message: Message, text: str):
    # Telegram messages have a 4096-character limit; plain text avoids HTML parsing issues.
    for start_index in range(0, len(text), 3900):
        await message.answer(text[start_index:start_index + 3900])


@dp.message()
async def chat(message: Message):
    if not message.from_user or not message.text:
        await message.answer("فعلاً فقط پیام متنی را پشتیبانی می‌کنم. 🙂")
        return
    text = message.text.strip()
    if not text:
        return
    if len(text) > MAX_MESSAGE_CHARS:
        await message.answer("پیامت خیلی طولانیه؛ لطفاً آن را کوتاه‌تر کن.")
        return

    if not GROQ_API_KEY:
        await message.answer(
            "⚠️ ربات اجرا شده، اما API هوش مصنوعی هنوز تنظیم نشده است. "
            "مدیر باید GROQ_API_KEY را در Environment سرویس Render اضافه کند."
        )
        return

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    answer = await ask_ai(message.from_user.id, text)
    await send_long_message(message, answer)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot, polling_task
    if BOT_TOKEN:
        bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        # This bot sends model output as escaped plain text, avoiding accidental HTML markup.
        bot.default.parse_mode = None
        polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
        log.info("AI chat Telegram polling started")
    else:
        log.error("Telegram bot is inactive: ZEUS_BOT_TOKEN is missing")
    if not GROQ_API_KEY:
        log.warning("AI chat is running without GROQ_API_KEY; messages will receive setup guidance")
    yield
    if polling_task:
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Error while stopping Telegram polling")
    if bot:
        await bot.session.close()


app = FastAPI(title="FXI AI Chat Bot", version="2.0.0", lifespan=lifespan)


@app.get("/")
async def root():
    return {
        "service": "fxi-ai-chat-bot",
        "status": "ok",
        "telegram_configured": bool(BOT_TOKEN),
        "ai_configured": bool(GROQ_API_KEY),
        "model": AI_MODEL,
    }


@app.get("/health")
async def health():
    configured = bool(BOT_TOKEN and GROQ_API_KEY)
    return JSONResponse(
        status_code=200 if configured else 503,
        content={
            "status": "ok" if configured else "needs_configuration",
            "telegram_configured": bool(BOT_TOKEN),
            "ai_configured": bool(GROQ_API_KEY),
            "model": AI_MODEL,
        },
    )
