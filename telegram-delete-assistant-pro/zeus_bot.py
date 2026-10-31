import asyncio
import logging
import os
from collections import defaultdict

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("fxi-multi-ai-chat")

BOT_TOKEN = os.getenv("ZEUS_BOT_TOKEN", "").strip()
SYSTEM_PROMPT = os.getenv(
    "AI_SYSTEM_PROMPT",
    "تو یک دستیار هوش مصنوعی فارسی‌زبان، دقیق، مفید و صمیمی هستی. "
    "به زبان کاربر پاسخ بده؛ پاسخ‌ها را روشن و کاربردی بنویس. "
    "اگر چیزی را نمی‌دانی، صادقانه بگو و اطلاعات یا منبع جعلی نساز. "
    "برای درخواست‌های برنامه‌نویسی، راهکار قابل اجرا و کد خوانا ارائه کن.",
)
MAX_HISTORY_MESSAGES = 16
MAX_MESSAGE_CHARS = 12000
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=75, connect=15)

# Provider credentials and model names are configured in Render Environment.
PROVIDERS = {
    "openai": {
        "label": "🔵 OpenAI (ChatGPT)",
        "key": os.getenv("OPENAI_API_KEY", "").strip(),
        "model": os.getenv("OPENAI_MODEL", "gpt-5.5").strip(),
    },
    "gemini": {
        "label": "🟢 Google Gemini",
        "key": os.getenv("GEMINI_API_KEY", "").strip(),
        "model": os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip(),
    },
    "claude": {
        "label": "🟣 Claude (Anthropic)",
        "key": os.getenv("ANTHROPIC_API_KEY", "").strip(),
        "model": os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5").strip(),
    },
    "deepseek": {
        "label": "⚫ DeepSeek",
        "key": os.getenv("DEEPSEEK_API_KEY", "").strip(),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
    },
    "grok": {
        "label": "⚡ Grok (xAI)",
        "key": os.getenv("XAI_API_KEY", "").strip(),
        "model": os.getenv("XAI_MODEL", "grok-3-mini").strip(),
    },
    "groq": {
        "label": "🟠 Groq",
        "key": os.getenv("GROQ_API_KEY", "").strip(),
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
    },
    "mistral": {
        "label": "🟡 Mistral",
        "key": os.getenv("MISTRAL_API_KEY", "").strip(),
        "model": os.getenv("MISTRAL_MODEL", "mistral-small-latest").strip(),
    },
    "openrouter": {
        "label": "🌐 OpenRouter",
        "key": os.getenv("OPENROUTER_API_KEY", "").strip(),
        "model": os.getenv("OPENROUTER_MODEL", "openrouter/free").strip(),
    },
    "cloudflare": {
        "label": "☁️ Cloudflare Workers AI",
        "key": os.getenv("CLOUDFLARE_API_TOKEN", "").strip(),
        "account_id": os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip(),
        "model": os.getenv("CLOUDFLARE_MODEL", "@cf/meta/llama-3.1-8b-instruct").strip(),
    },
}

# Runtime state: histories are isolated by both user and provider.
histories = defaultdict(list)
history_locks = defaultdict(asyncio.Lock)
selected_provider = defaultdict(lambda: next((name for name in PROVIDERS if provider_ready(name)), "gemini"))
bot = None
dp = Dispatcher()
polling_task = None


def provider_ready(provider: str) -> bool:
    if provider not in PROVIDERS or not PROVIDERS[provider]["key"]:
        return False
    if provider == "cloudflare":
        return bool(PROVIDERS[provider].get("account_id"))
    return True


def provider_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for provider_id, config in PROVIDERS.items():
        status = "✅" if provider_ready(provider_id) else "🔒"
        rows.append([InlineKeyboardButton(
            text=f"{status} {config['label']}",
            callback_data=f"provider:{provider_id}",
        )])
    rows.append([InlineKeyboardButton(text="ℹ️ وضعیت سرویس‌ها", callback_data="providers:status")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def provider_menu_text(user_id: int) -> str:
    current = selected_provider[user_id]
    current_label = PROVIDERS[current]["label"]
    return (
        "🤖 انتخاب هوش مصنوعی\n\n"
        f"مدل فعلی: {current_label}\n\n"
        "سرویس دلخواهت رو انتخاب کن. گزینه‌های قفل‌شده هنوز کلید API ندارن؛ "
        "بعد از تنظیم کلید در Render فعال می‌شن."
    )


@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id if message.from_user else 0
    await message.answer(
        "سلام! 👋 به دستیار هوش مصنوعی FXI خوش اومدی.\n"
        "از منو سرویس موردنظرت رو انتخاب کن، بعد پیام بفرست.\n\n"
        "برای شروع گفت‌وگوی تازه /new رو بزن.",
        reply_markup=provider_keyboard(),
    )


@dp.message(Command("ai"))
@dp.message(Command("models"))
async def choose_ai(message: Message):
    user_id = message.from_user.id if message.from_user else 0
    await message.answer(provider_menu_text(user_id), reply_markup=provider_keyboard())


@dp.callback_query(F.data.startswith("provider:"))
async def choose_provider(callback: CallbackQuery):
    if not callback.from_user:
        await callback.answer()
        return
    provider_id = callback.data.split(":", 1)[1]
    if provider_id not in PROVIDERS:
        await callback.answer("این گزینه شناخته‌شده نیست.", show_alert=True)
        return
    if not provider_ready(provider_id):
        env_name = {
            "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "claude": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "grok": "XAI_API_KEY",
            "groq": "GROQ_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "cloudflare": "CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID",
        }[provider_id]
        await callback.answer("این سرویس هنوز فعال نشده؛ مدیر باید کلید API را در Render تنظیم کند.", show_alert=True)
        if callback.message:
            await callback.message.answer(
                f"🔒 {PROVIDERS[provider_id]['label']} هنوز پیکربندی نشده.\n"
                f"نام متغیر موردنیاز در Render: {env_name}"
            )
        return
    selected_provider[callback.from_user.id] = provider_id
    await callback.answer("انتخاب شد ✅")
    if callback.message:
        await callback.message.answer(
            f"✅ هوش مصنوعی فعال شد: {PROVIDERS[provider_id]['label']}\n"
            "حالا پیامت رو بفرست. برای تغییر سرویس /ai رو بزن."
        )


@dp.callback_query(F.data == "providers:status")
async def providers_status(callback: CallbackQuery):
    lines = ["📡 وضعیت سرویس‌های هوش مصنوعی:"]
    for provider_id, config in PROVIDERS.items():
        state = "فعال ✅" if provider_ready(provider_id) else "نیازمند API Key 🔒"
        lines.append(f"• {config['label']}: {state}")
    if callback.message:
        await callback.message.answer("\n".join(lines))
    await callback.answer()


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "راهنمای استفاده 🤖\n\n"
        "• پیام متنی بفرست تا هوش مصنوعی انتخاب‌شده پاسخ بدهد.\n"
        "• /ai یا /models — انتخاب هوش مصنوعی\n"
        "• /new — پاک‌کردن سابقهٔ سرویس فعلی\n"
        "• /help — راهنما\n\n"
        "تاریخچهٔ هر سرویس برای هر کاربر جدا نگه داشته می‌شود. "
        "ممکن است پاسخ هوش مصنوعی اشتباه باشد؛ اطلاعات مهم را بررسی کن."
    )


@dp.message(Command("new"))
@dp.message(Command("reset"))
async def reset_chat(message: Message):
    if message.from_user:
        user_id = message.from_user.id
        provider_id = selected_provider[user_id]
        histories[(user_id, provider_id)].clear()
    await message.answer("🧹 سابقهٔ گفت‌وگوی سرویس فعلی پاک شد؛ از نو شروع کنیم!")


async def post_json(url: str, headers: dict, payload: dict) -> tuple[int, dict]:
    async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
        async with session.post(url, headers=headers, json=payload) as response:
            data = await response.json(content_type=None)
            if not isinstance(data, dict):
                data = {"raw": str(data)}
            return response.status, data


def api_error(provider_id: str, status: int, data: dict) -> str:
    error = data.get("error", {})
    if isinstance(error, dict):
        detail = str(error.get("message") or error.get("type") or "")
    else:
        detail = str(error or "")
    log.error("%s API returned HTTP %s: %s", provider_id, status, detail[:300])
    if status in (401, 403):
        return f"⚠️ کلید یا دسترسی {PROVIDERS[provider_id]['label']} معتبر نیست؛ مدیر باید تنظیمات API را بررسی کند."
    if status == 429:
        return f"⏳ محدودیت درخواست یا سهمیهٔ {PROVIDERS[provider_id]['label']} پر شده؛ کمی بعد دوباره تلاش کن."
    if status >= 500:
        return f"⚠️ سرویس {PROVIDERS[provider_id]['label']} فعلاً مشکل دارد (کد {status}). کمی بعد دوباره تلاش کن."
    return f"⚠️ درخواست به {PROVIDERS[provider_id]['label']} ناموفق بود (کد {status}). مدل یا تنظیمات API را بررسی کن."


async def ask_openai(history: list, user_text: str) -> tuple[int, dict]:
    input_messages = []
    for item in history[-MAX_HISTORY_MESSAGES:]:
        input_messages.append({"role": item["role"], "content": item["content"]})
    input_messages.append({"role": "user", "content": user_text})
    return await post_json(
        "https://api.openai.com/v1/responses",
        {"Authorization": f"Bearer {PROVIDERS['openai']['key']}", "Content-Type": "application/json"},
        {"model": PROVIDERS["openai"]["model"], "instructions": SYSTEM_PROMPT,
         "input": input_messages, "max_output_tokens": 1800, "store": False},
    )


async def ask_gemini(history: list, user_text: str) -> tuple[int, dict]:
    contents = []
    for item in history[-MAX_HISTORY_MESSAGES:]:
        contents.append({
            "role": "user" if item["role"] == "user" else "model",
            "parts": [{"text": item["content"]}],
        })
    contents.append({"role": "user", "parts": [{"text": user_text}]})
    return await post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{PROVIDERS['gemini']['model']}:generateContent",
        {"x-goog-api-key": PROVIDERS["gemini"]["key"], "Content-Type": "application/json"},
        {"system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]}, "contents": contents,
         "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1800}},
    )


async def ask_claude(history: list, user_text: str) -> tuple[int, dict]:
    messages = []
    for item in history[-MAX_HISTORY_MESSAGES:]:
        messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": user_text})
    return await post_json(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": PROVIDERS["claude"]["key"], "anthropic-version": "2023-06-01",
         "Content-Type": "application/json"},
        {"model": PROVIDERS["claude"]["model"], "system": SYSTEM_PROMPT,
         "messages": messages, "max_tokens": 1800},
    )


async def ask_grok(history: list, user_text: str) -> tuple[int, dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend({"role": item["role"], "content": item["content"]}
                    for item in history[-MAX_HISTORY_MESSAGES:])
    messages.append({"role": "user", "content": user_text})
    return await post_json(
        "https://api.x.ai/v1/chat/completions",
        {"Authorization": f"Bearer {PROVIDERS['grok']['key']}", "Content-Type": "application/json"},
        {"model": PROVIDERS["grok"]["model"], "messages": messages,
         "temperature": 0.7, "max_tokens": 1800},
    )


async def ask_compatible(provider_id: str, history: list, user_text: str) -> tuple[int, dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend({"role": item["role"], "content": item["content"]}
                    for item in history[-MAX_HISTORY_MESSAGES:])
    messages.append({"role": "user", "content": user_text})
    config = PROVIDERS[provider_id]
    if provider_id == "groq":
        url = "https://api.groq.com/openai/v1/chat/completions"
    elif provider_id == "mistral":
        url = "https://api.mistral.ai/v1/chat/completions"
    elif provider_id == "openrouter":
        url = "https://openrouter.ai/api/v1/chat/completions"
    elif provider_id == "cloudflare":
        url = f"https://api.cloudflare.com/client/v4/accounts/{config['account_id']}/ai/v1/chat/completions"
    else:
        raise ValueError("Unsupported compatible provider")
    headers = {"Authorization": f"Bearer {config['key']}", "Content-Type": "application/json"}
    if provider_id == "openrouter":
        headers["HTTP-Referer"] = os.getenv("OPENROUTER_SITE_URL", "https://telegram-delete-assistant-pro.onrender.com")
        headers["X-Title"] = "FXI Telegram AI"
    return await post_json(url, headers, {
        "model": config["model"], "messages": messages,
        "temperature": 0.7, "max_tokens": 1800,
    })


async def ask_deepseek(history: list, user_text: str) -> tuple[int, dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend({"role": item["role"], "content": item["content"]}
                    for item in history[-MAX_HISTORY_MESSAGES:])
    messages.append({"role": "user", "content": user_text})
    return await post_json(
        "https://api.deepseek.com/chat/completions",
        {"Authorization": f"Bearer {PROVIDERS['deepseek']['key']}", "Content-Type": "application/json"},
        {"model": PROVIDERS["deepseek"]["model"], "messages": messages,
         "temperature": 0.7, "max_tokens": 1800},
    )


def extract_answer(provider_id: str, data: dict) -> str:
    if provider_id == "openai":
        # Responses API returns text in output message content blocks.
        output = data.get("output") or []
        parts = []
        for item in output:
            if item.get("type") == "message":
                for block in item.get("content") or []:
                    if block.get("type") == "output_text" and block.get("text"):
                        parts.append(block["text"])
        return "\n".join(parts).strip()
    if provider_id == "gemini":
        candidates = data.get("candidates") or []
        parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
        return "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()
    if provider_id == "claude":
        return "\n".join(block.get("text", "") for block in data.get("content", [])
                         if block.get("type") == "text").strip()
    choices = data.get("choices") or []
    return str(((choices[0].get("message") or {}).get("content") or "")).strip() if choices else ""


async def ask_ai(user_id: int, provider_id: str, user_text: str) -> str:
    if not provider_ready(provider_id):
        return f"🔒 {PROVIDERS[provider_id]['label']} هنوز فعال نشده؛ مدیر باید کلید API مربوطه را در Render تنظیم کند."
    key = (user_id, provider_id)
    async with history_locks[key]:
        history = histories[key]
        try:
            # Try the selected provider first, then other configured providers.
            # A failed/limited provider must not block the user's message.
            order = [provider_id] + [name for name in PROVIDERS
                                     if name != provider_id and provider_ready(name)]
            failures = []
            for candidate in order:
                if not provider_ready(candidate):
                    continue
                try:
                    if candidate == "openai":
                        status, data = await ask_openai(history, user_text)
                    elif candidate == "gemini":
                        status, data = await ask_gemini(history, user_text)
                    elif candidate == "claude":
                        status, data = await ask_claude(history, user_text)
                    elif candidate == "deepseek":
                        status, data = await ask_deepseek(history, user_text)
                    elif candidate == "grok":
                        status, data = await ask_grok(history, user_text)
                    else:
                        status, data = await ask_compatible(candidate, history, user_text)
                    if status >= 400:
                        failures.append(f"{candidate}: HTTP {status}")
                        api_error(candidate, status, data)
                        continue
                    answer = extract_answer(candidate, data)
                    if not answer:
                        failures.append(f"{candidate}: empty response")
                        continue
                    if candidate != provider_id:
                        log.warning("AI failover: selected=%s fallback=%s", provider_id, candidate)
                    history.extend([
                        {"role": "user", "content": user_text},
                        {"role": "assistant", "content": answer},
                    ])
                    del history[:-MAX_HISTORY_MESSAGES]
                    if candidate != provider_id:
                        return f"↪️ پاسخ از {PROVIDERS[candidate]['label']}\n\n{answer}"
                    return answer
                except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
                    log.warning("Provider %s unavailable: %s", candidate, type(exc).__name__)
                    failures.append(f"{candidate}: connection/timeout")
                    continue
            log.error("All configured AI providers failed: %s", ", ".join(failures))
            return "⚠️ در حال حاضر هیچ‌کدام از سرویس‌های هوش مصنوعی پاسخ ندادند. کمی بعد دوباره تلاش کن."
        except asyncio.TimeoutError:
            return f"⏳ پاسخ‌گویی {PROVIDERS[provider_id]['label']} طول کشید؛ دوباره تلاش کن."
        except aiohttp.ClientError:
            log.exception("Network error calling %s", provider_id)
            return f"⚠️ اتصال به {PROVIDERS[provider_id]['label']} مشکل دارد؛ کمی بعد دوباره تلاش کن."
        except Exception:
            log.exception("Unexpected error handling %s request", provider_id)
            return "⚠️ خطای پیش‌بینی‌نشده رخ داد. دوباره تلاش کن."


async def send_long_message(message: Message, text: str):
    for i in range(0, len(text), 3900):
        await message.answer(text[i:i + 3900])


@dp.message()
async def chat(message: Message):
    if not message.from_user or not message.text:
        await message.answer("فعلاً فقط پیام متنی رو پشتیبانی می‌کنم. 🙂")
        return
    user_text = message.text.strip()
    if not user_text:
        return
    if len(user_text) > MAX_MESSAGE_CHARS:
        await message.answer("پیامت خیلی طولانیه؛ لطفاً کوتاه‌ترش کن.")
        return
    provider_id = selected_provider[message.from_user.id]
    if not provider_ready(provider_id):
        await message.answer(
            f"🔒 سرویس فعلی ({PROVIDERS[provider_id]['label']}) هنوز فعال نشده. "
            "با /ai سرویس دیگری انتخاب کن."
        )
        return
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await send_long_message(message, await ask_ai(message.from_user.id, provider_id, user_text))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot, polling_task
    if BOT_TOKEN:
        bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=None))
        polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
        log.info("FXI multi-provider AI Telegram polling started; configured providers=%s",
                 [name for name in PROVIDERS if provider_ready(name)])
    else:
        log.error("Telegram bot is inactive: ZEUS_BOT_TOKEN is missing")
    if not any(provider_ready(name) for name in PROVIDERS):
        log.warning("No AI provider API keys are configured; AI replies are disabled")
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


app = FastAPI(title="FXI Multi-AI Chat Bot", version="4.0.0", lifespan=lifespan)


@app.get("/")
async def root():
    configured = [name for name in PROVIDERS if provider_ready(name)]
    return {
        "service": "fxi-multi-ai-chat-bot",
        "status": "ok",
        "telegram_configured": bool(BOT_TOKEN),
        "ai_configured": bool(configured),
        "configured_providers": configured,
    }


@app.get("/health")
async def health():
    configured = [name for name in PROVIDERS if provider_ready(name)]
    healthy_config = bool(BOT_TOKEN and configured)
    return JSONResponse(status_code=200 if healthy_config else 503, content={
        "status": "ok" if healthy_config else "needs_configuration",
        "telegram_configured": bool(BOT_TOKEN),
        "ai_configured": bool(configured),
        "configured_providers": configured,
    })
