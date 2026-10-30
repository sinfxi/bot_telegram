import asyncio
import logging
import os
from collections import defaultdict
from contextlib import asynccontextmanager

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from fastapi import FastAPI
from fastapi.responses import JSONResponse

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fxi-gemini-chat")

BOT_TOKEN = os.getenv("ZEUS_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
AI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"
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


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "سلام! 👋 من دستیار هوش مصنوعی‌ات هستم.\n\n"
        "می‌تونی درباره برنامه‌نویسی، درس، فناوری، نوشتن، ایده‌پردازی و موضوع‌های مختلف باهام گفتگو کنی. "
        "پیامت رو همین‌جا بفرست و برای شروع گفت‌وگوی تازه /new رو بزن.\n\n"
        "/help — راهنما"
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "راهنمای استفاده 🤖\n\n"
        "• هر پیام متنی بفرستی، به آن پاسخ می‌دهم.\n"
        "• /new — پاک‌کردن سابقه و شروع دوباره\n"
        "• /help — راهنما\n\n"
        "من ممکن است اشتباه کنم؛ اطلاعات مهم را بررسی کن."
    )


@dp.message(Command("new"))
@dp.message(Command("reset"))
async def reset_chat(message: Message):
    if message.from_user:
        histories[message.from_user.id].clear()
    await message.answer("🧹 سابقهٔ گفت‌وگو پاک شد؛ از نو شروع کنیم!")


async def ask_ai(user_id: int, user_text: str) -> str:
    if not GEMINI_API_KEY:
        return "⚠️ کلید هوش مصنوعی تنظیم نشده است. مدیر باید GEMINI_API_KEY را در Environment سرویس Render اضافه کند."

    async with history_locks[user_id]:
        history = histories[user_id]
        contents = []
        for item in history[-MAX_HISTORY_MESSAGES:]:
            contents.append({
                "role": "user" if item["role"] == "user" else "model",
                "parts": [{"text": item["content"]}],
            })
        contents.append({"role": "user", "parts": [{"text": user_text}]})

        timeout = aiohttp.ClientTimeout(total=75, connect=15)
        headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1800},
        }
        url = f"{GEMINI_URL}/{AI_MODEL}:generateContent"

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    data = await response.json(content_type=None)
                    if response.status in (401, 403):
                        log.error("Gemini API authentication/permission failure: HTTP %s", response.status)
                        return "⚠️ کلید Gemini معتبر نیست یا دسترسی API فعال نیست. مدیر باید GEMINI_API_KEY و تنظیمات Google AI Studio را بررسی کند."
                    if response.status == 429:
                        log.warning("Gemini API quota/rate limit reached")
                        return "⏳ سهمیه یا محدودیت درخواست Gemini فعلاً پر شده؛ کمی بعد دوباره تلاش کن."
                    if response.status >= 400:
                        error = data.get("error", {}) if isinstance(data, dict) else {}
                        detail = error.get("message", "") if isinstance(error, dict) else ""
                        log.error("Gemini API returned HTTP %s: %s", response.status, detail[:300])
                        return f"⚠️ سرویس Gemini خطا داد (کد {response.status}). مدل یا تنظیمات API را بررسی کن."
                    candidates = data.get("candidates") or []
                    parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
                    answer = "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()
                    if not answer:
                        log.warning("Gemini returned no text; response keys=%s", list(data.keys()) if isinstance(data, dict) else [])
                        return "پاسخی دریافت نکردم؛ لطفاً سؤال را دوباره بفرست."
                    history.extend([
                        {"role": "user", "content": user_text},
                        {"role": "assistant", "content": answer},
                    ])
                    del history[:-MAX_HISTORY_MESSAGES]
                    return answer
        except asyncio.TimeoutError:
            return "⏳ پاسخ‌گویی طول کشید؛ دوباره تلاش کن."
        except aiohttp.ClientError:
            log.exception("Network error calling Gemini API")
            return "⚠️ اتصال به سرویس Gemini مشکل دارد؛ کمی بعد دوباره تلاش کن."
        except Exception:
            log.exception("Unexpected error handling Gemini request")
            return "⚠️ خطای پیش‌بینی‌نشده رخ داد. دوباره تلاش کن."


async def send_long_message(message: Message, text: str):
    for i in range(0, len(text), 3900):
        await message.answer(text[i:i + 3900])


@dp.message()
async def chat(message: Message):
    if not message.from_user or not message.text:
        await message.answer("فعلاً فقط پیام متنی را پشتیبانی می‌کنم. 🙂")
        return
    user_text = message.text.strip()
    if not user_text:
        return
    if len(user_text) > MAX_MESSAGE_CHARS:
        await message.answer("پیامت خیلی طولانیه؛ لطفاً کوتاه‌ترش کن.")
        return
    if not GEMINI_API_KEY:
        await message.answer("⚠️ ربات فعال است، اما GEMINI_API_KEY در Environment سرویس Render تنظیم نشده.")
        return
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await send_long_message(message, await ask_ai(message.from_user.id, user_text))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot, polling_task
    if BOT_TOKEN:
        bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=None))
        polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
        log.info("Gemini AI chat Telegram polling started; model=%s", AI_MODEL)
    else:
        log.error("Telegram bot is inactive: ZEUS_BOT_TOKEN is missing")
    if not GEMINI_API_KEY:
        log.warning("Gemini AI chat has no GEMINI_API_KEY; AI replies are disabled")
    yield
    if polling_task:
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Error stopping Telegram polling")
    if bot:
        await bot.session.close()


app = FastAPI(title="FXI Gemini AI Chat Bot", version="3.0.0", lifespan=lifespan)


@app.get("/")
async def root():
    return {"service": "fxi-gemini-ai-chat-bot", "status": "ok",
            "telegram_configured": bool(BOT_TOKEN), "ai_configured": bool(GEMINI_API_KEY),
            "provider": "Google Gemini", "model": AI_MODEL}


@app.get("/health")
async def health():
    configured = bool(BOT_TOKEN and GEMINI_API_KEY)
    return JSONResponse(status_code=200 if configured else 503, content={
        "status": "ok" if configured else "needs_configuration",
        "telegram_configured": bool(BOT_TOKEN), "ai_configured": bool(GEMINI_API_KEY),
        "provider": "Google Gemini", "model": AI_MODEL,
    })
