from __future__ import annotations

import asyncio
import logging
import os
import json
import secrets
import io
import base64
import hashlib
import hmac
import time
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi import Request
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from pydantic import BaseModel, Field

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
SUPPORT_CARD = '5859831211613988'
SUPPORT_CARDHOLDER = 'سینا نوبخت'
ADMIN_REQUEST_MIN_TOMAN = 100_000
pending_receipts = set()
ADMIN_IDS = {int(value) for value in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if value.isdigit()}
ADMIN_PANEL_USERNAME = os.getenv("ADMIN_PANEL_USERNAME", "fxi-admin").strip()
ADMIN_PANEL_PASSWORD = os.getenv("ADMIN_PANEL_PASSWORD", "").strip()
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "The_fxi_bot").strip().lstrip("@")
SESSION_SERIALIZER = URLSafeTimedSerializer(BOT_TOKEN, salt="fxi-web-session") if BOT_TOKEN else None
STATIC_DIR = Path(__file__).parent / "static"
ADMIN_DATA_FILE = Path(os.getenv("ADMIN_DATA_FILE", "/tmp/fxi_admin_data.json"))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
admin_security = HTTPBasic()
admin_data_lock = asyncio.Lock()
bot_enabled = True


def _db_connect():
    if not DATABASE_URL:
        return None
    import psycopg
    return psycopg.connect(DATABASE_URL, connect_timeout=8)


def _ensure_db_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS fxi_bot_state (
                id SMALLINT PRIMARY KEY CHECK (id = 1),
                data JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
    conn.commit()


def load_admin_data() -> dict:
    defaults = {"admins": [], "users": [], "bot_enabled": True,
                "system_prompt": SYSTEM_PROMPT, "payments": {}, "receipt_hashes": []}
    if DATABASE_URL:
        try:
            with _db_connect() as conn:
                _ensure_db_table(conn)
                with conn.cursor() as cur:
                    cur.execute("SELECT data FROM fxi_bot_state WHERE id = 1")
                    row = cur.fetchone()
                if row and isinstance(row[0], dict):
                    data = row[0]
                    for key, value in defaults.items():
                        data.setdefault(key, value)
                    log.info("Loaded FXI bot state from PostgreSQL")
                    return data
        except Exception:
            log.exception("PostgreSQL load failed; falling back to local JSON")
    try:
        data = json.loads(ADMIN_DATA_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key, value in defaults.items():
                data.setdefault(key, value)
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return defaults


def save_admin_data() -> None:
    if DATABASE_URL:
        try:
            with _db_connect() as conn:
                _ensure_db_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO fxi_bot_state (id, data, updated_at)
                           VALUES (1, %s, NOW())
                           ON CONFLICT (id) DO UPDATE
                           SET data = EXCLUDED.data, updated_at = NOW()""",
                        (json.dumps(admin_data, ensure_ascii=False),),
                    )
                conn.commit()
            return
        except Exception:
            log.exception("PostgreSQL save failed; writing local fallback")
    ADMIN_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = ADMIN_DATA_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps(admin_data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_file.replace(ADMIN_DATA_FILE)




CHAT_HISTORY_LIMIT = 500


def _ensure_chat_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS fxi_chat_messages (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                provider_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_fxi_chat_user_provider_id
            ON fxi_chat_messages (user_id, provider_id, id DESC)
        """)
    conn.commit()


def _load_chat_history_sync(user_id: int, provider_id: str, limit: int = MAX_HISTORY_MESSAGES) -> list:
    with _db_connect() as conn:
        _ensure_chat_table(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT role, content FROM (
                    SELECT id, role, content FROM fxi_chat_messages
                    WHERE user_id = %s AND provider_id = %s
                    ORDER BY id DESC LIMIT %s
                ) recent ORDER BY id ASC
            """, (user_id, provider_id, limit))
            return [{"role": row[0], "content": row[1]} for row in cur.fetchall()]


def _save_chat_turn_sync(user_id: int, provider_id: str, user_text: str, answer: str) -> None:
    with _db_connect() as conn:
        _ensure_chat_table(conn)
        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO fxi_chat_messages (user_id, provider_id, role, content)
                VALUES (%s, %s, %s, %s)
            """, [
                (user_id, provider_id, "user", user_text),
                (user_id, provider_id, "assistant", answer),
            ])
            cur.execute("""
                DELETE FROM fxi_chat_messages
                WHERE id IN (
                    SELECT id FROM fxi_chat_messages
                    WHERE user_id = %s AND provider_id = %s
                    ORDER BY id DESC OFFSET %s
                )
            """, (user_id, provider_id, CHAT_HISTORY_LIMIT))
        conn.commit()


def _clear_chat_history_sync(user_id: int, provider_id: str) -> None:
    with _db_connect() as conn:
        _ensure_chat_table(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM fxi_chat_messages WHERE user_id = %s AND provider_id = %s",
                        (user_id, provider_id))
        conn.commit()


def _admin_conversation_list_sync(limit: int = 100) -> list:
    with _db_connect() as conn:
        _ensure_chat_table(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, COUNT(*) AS message_count, MAX(created_at) AS last_message,
                       (ARRAY_AGG(content ORDER BY id DESC))[1] AS preview
                FROM fxi_chat_messages
                GROUP BY user_id ORDER BY MAX(created_at) DESC LIMIT %s
            """, (limit,))
            return [{"user_id": row[0], "message_count": row[1],
                     "last_message": row[2].isoformat() if row[2] else None,
                     "preview": row[3][:180] if row[3] else ""}
                    for row in cur.fetchall()]


def _admin_conversation_sync(user_id: int, limit: int = 100) -> list:
    with _db_connect() as conn:
        _ensure_chat_table(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT provider_id, role, content, created_at
                FROM fxi_chat_messages WHERE user_id = %s
                ORDER BY id DESC LIMIT %s
            """, (user_id, limit))
            rows = cur.fetchall()
            rows.reverse()
            return [{"provider_id": row[0], "role": row[1], "content": row[2],
                     "created_at": row[3].isoformat() if row[3] else None}
                    for row in rows]



admin_data = load_admin_data()
for _admin_id in ADMIN_IDS:
    if _admin_id not in admin_data["admins"]:
        admin_data["admins"].append(_admin_id)
bot_enabled = bool(admin_data.get("bot_enabled", True))


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS or user_id in admin_data.get("admins", [])


def verify_telegram_login(payload: TelegramAuthPayload) -> bool:
    if not BOT_TOKEN:
        return False
    values = payload.model_dump(exclude={"hash"}, exclude_none=True)
    check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hashlib.sha256(BOT_TOKEN.encode("utf-8")).digest()
    expected = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, payload.hash):
        return False
    now = int(time.time())
    return payload.auth_date <= now + 60 and now - payload.auth_date <= 86400


def get_web_user(request: Request) -> dict:
    token = request.cookies.get("fxi_session", "")
    if not token or not SESSION_SERIALIZER:
        raise HTTPException(status_code=401, detail="برای ادامه ابتدا با تلگرام وارد شو.")
    try:
        user = SESSION_SERIALIZER.loads(token, max_age=7 * 24 * 60 * 60)
        if not isinstance(user, dict) or not user.get("id"):
            raise BadSignature("invalid session")
        return user
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=401, detail="نشست شما منقضی شده؛ دوباره وارد شو.")


def remember_user(user_id: int) -> None:
    users = admin_data.setdefault("users", [])
    if user_id not in users:
        users.append(user_id)
        try:
            save_admin_data()
        except OSError:
            log.exception("Could not persist Telegram user registry")


def require_admin(credentials: HTTPBasicCredentials = Depends(admin_security)):
    valid_user = secrets.compare_digest(credentials.username, ADMIN_PANEL_USERNAME)
    valid_password = bool(ADMIN_PANEL_PASSWORD) and secrets.compare_digest(
        credentials.password, ADMIN_PANEL_PASSWORD
    )
    if not (valid_user and valid_password):
        raise HTTPException(status_code=401, detail="ورود نامعتبر است",
                            headers={"WWW-Authenticate": "Basic"})
    return credentials.username


class AdminIdPayload(BaseModel):
    user_id: int


class BroadcastPayload(BaseModel):
    text: str = Field(min_length=1, max_length=3900)


class BotStatePayload(BaseModel):
    enabled: bool


class PromptPayload(BaseModel):
    prompt: str = Field(min_length=10, max_length=8000)


class TelegramAuthPayload(BaseModel):
    id: int
    auth_date: int
    hash: str
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None


class ProviderPayload(BaseModel):
    provider_id: str


class ChatPayload(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


ADMIN_PANEL_HTML = (Path(__file__).parent / "static" / "admin.html").read_text(encoding="utf-8")
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
    rows.append([InlineKeyboardButton(text="🌐 ورود به پنل وب FXI", url="https://telegram-delete-assistant-pro.onrender.com/app")])
    rows.append([InlineKeyboardButton(text="❤️ حمایت / درخواست ادمینی", callback_data="support:start")])
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
    remember_user(user_id)
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


async def analyze_receipt_image(image_bytes: bytes, mime_type: str) -> dict:
    if not provider_ready("gemini"):
        raise RuntimeError("برای تحلیل رسید باید GEMINI_API_KEY تنظیم شده باشد.")
    prompt = ("از تصویر رسید مبلغ را استخراج کن. مبلغ را به تومان برگردان؛ اگر مبلغ ریالی است بر ۱۰ تقسیم کن. "
              "اگر مبلغ یا واحد پول نامشخص است amount_toman را null بگذار. فقط JSON معتبر با کلیدهای "
              "amount_toman عدد یا null، transaction_reference رشته یا null، confidence عدد بین صفر و یک، "
              "currency_seen رشته و notes رشته برگردان. این فقط OCR است و اعتبار پرداخت را تأیید نمی‌کند.")
    payload = {"contents":[{"role":"user","parts":[{"text":prompt},{"inline_data":{"mime_type":mime_type,"data":base64.b64encode(image_bytes).decode("ascii")}}]}],
               "generationConfig":{"temperature":0,"maxOutputTokens":350}}
    status, data = await post_json(f"https://generativelanguage.googleapis.com/v1beta/models/{PROVIDERS['gemini']['model']}:generateContent",
        {"x-goog-api-key":PROVIDERS["gemini"]["key"],"Content-Type":"application/json"}, payload)
    if status >= 400: raise RuntimeError(f"خطای تحلیل تصویر: HTTP {status}")
    candidates=data.get("candidates") or []; parts=((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
    raw="\n".join(p.get("text","") for p in parts if p.get("text")).strip()
    raw=raw.replace("```json","").replace("```","").strip()
    try: result=json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc: raise RuntimeError("مبلغ از تصویر قابل استخراج نیست.") from exc
    amount=result.get("amount_toman")
    result["amount_toman"]=int(amount) if isinstance(amount,(int,float)) and not isinstance(amount,bool) and amount>0 else None
    try: result["confidence"]=max(0.0,min(1.0,float(result.get("confidence") or 0)))
    except (TypeError,ValueError): result["confidence"]=0.0
    return result

def payment_review_keyboard(pid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ تأیید و ادمین کردن",callback_data=f"pay:approve:{pid}"),InlineKeyboardButton(text="❌ رد درخواست",callback_data=f"pay:reject:{pid}")]])

@dp.message(Command("support"))
async def support_command(message: Message):
    if message.from_user: pending_receipts.add(message.from_user.id)
    await message.answer(f"❤️ حمایت از FXI و درخواست ادمینی\n\nشماره کارت: {SUPPORT_CARD}\nبه نام: {SUPPORT_CARDHOLDER}\n\nحداقل مبلغ برای درخواست ادمینی: ۱۰۰٬۰۰۰ تومان. پس از واریز تصویر رسید را همین‌جا بفرست. تحلیل تصویر تأیید نهایی پرداخت نیست.")

@dp.callback_query(F.data == "support:start")
async def support_callback(callback: CallbackQuery):
    if callback.from_user: pending_receipts.add(callback.from_user.id)
    await callback.answer()
    if callback.message: await callback.message.answer(f"❤️ حمایت از FXI / درخواست ادمینی\nشماره کارت: {SUPPORT_CARD}\nبه نام: {SUPPORT_CARDHOLDER}\nحداقل مبلغ: ۱۰۰٬۰۰۰ تومان\nپس از واریز، تصویر رسید را ارسال کن. تأیید نهایی با ادمین اصلی است.")

@dp.message(F.photo)
async def receive_payment_receipt(message: Message):
    if not message.from_user or not bot: return
    uid=message.from_user.id
    if uid not in pending_receipts:
        await message.answer("برای ارسال رسید ابتدا /support را بزن.")
        return
    pending_receipts.discard(uid)
    try:
        buff=io.BytesIO(); await bot.download(message.photo[-1].file_id,destination=buff); raw=buff.getvalue()
        digest=hashlib.sha256(raw).hexdigest()
        if digest in admin_data.get("receipt_hashes",[]):
            await message.answer("این تصویر رسید قبلاً ارسال شده است."); return
        await message.answer("🔎 رسید دریافت شد؛ در حال استخراج مبلغ…")
        info=await analyze_receipt_image(raw,message.photo[-1].mime_type or "image/jpeg")
        amount=info.get("amount_toman")
        if not amount:
            await message.answer("مبلغ از تصویر واضح نیست. لطفاً تصویر کامل‌تر و واضح‌تری بفرست و دوباره /support را بزن."); return
        if amount < ADMIN_REQUEST_MIN_TOMAN:
            await message.answer(f"مبلغ خوانده‌شده {amount:,} تومان است و به حداقل ۱۰۰٬۰۰۰ تومان نمی‌رسد. اگر اشتباه خوانده شده، تصویر واضح‌تری ارسال کن."); return
        pid=secrets.token_hex(5)
        record={"user_id":uid,"username":message.from_user.username,"full_name":message.from_user.full_name,"amount_toman":amount,"analysis":info,"receipt_hash":digest,"status":"pending_review","created_at":datetime.now(timezone.utc).isoformat()}
        admin_data.setdefault("payments",{})[pid]=record; admin_data.setdefault("receipt_hashes",[]).append(digest); save_admin_data()
        await message.answer("✅ مبلغ حداقل ۱۰۰ هزار تومان از تصویر خوانده شد. درخواستت برای بررسی ادمین اصلی ارسال شد؛ هنوز دسترسی ادمینی فعال نشده است.")
        caption=(f"🧾 درخواست حمایت / ادمینی\nکد: {pid}\nکاربر: {record['full_name']} (@{record['username'] or 'ندارد'})\nشناسه: {uid}\nمبلغ OCR: {amount:,} تومان\nاطمینان OCR: {info.get('confidence',0):.0%}\nشناسه تراکنش: {info.get('transaction_reference') or 'نامشخص'}\n\nلطفاً واریز را در حساب بررسی کنید. آیا اجازه ادمینی می‌دهید؟")
        for aid in sorted(set(ADMIN_IDS)|set(admin_data.get("admins",[]))):
            try: await bot.send_photo(aid,message.photo[-1].file_id,caption=caption,reply_markup=payment_review_keyboard(pid))
            except Exception: log.exception("Could not send receipt to admin %s",aid)
    except Exception:
        log.exception("Receipt processing failed")
        await message.answer("⚠️ تحلیل رسید ناموفق بود. بعداً دوباره تلاش کن.")

@dp.callback_query(F.data.startswith("pay:"))
async def review_payment(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("فقط ادمین می‌تواند بررسی کند.",show_alert=True); return
    try: _,action,pid=callback.data.split(":",2)
    except ValueError: await callback.answer("درخواست نامعتبر است.",show_alert=True); return
    payment=admin_data.get("payments",{}).get(pid)
    if not payment or payment.get("status")!="pending_review":
        await callback.answer("این درخواست وجود ندارد یا قبلاً بررسی شده.",show_alert=True); return
    uid=int(payment["user_id"]); payment["reviewed_by"]=callback.from_user.id; payment["reviewed_at"]=datetime.now(timezone.utc).isoformat()
    if action=="approve":
        if uid not in admin_data.setdefault("admins",[]): admin_data["admins"].append(uid)
        payment["status"]="approved_admin"; save_admin_data(); await callback.answer("تأیید شد؛ کاربر ادمین شد.")
        if bot: await bot.send_message(uid,"🌹 حمایتت پس از بررسی ادمین اصلی تأیید شد و دسترسی ادمینی برایت فعال شد. خوش اومدی به تیم FXI! ❤️")
        if callback.message: await callback.message.edit_reply_markup(reply_markup=None); await callback.message.answer(f"✅ درخواست {pid} تأیید شد؛ کاربر ادمین شد.")
    elif action=="reject":
        payment["status"]="rejected"; save_admin_data(); await callback.answer("درخواست رد شد.")
        if bot:
            try: await bot.send_message(uid,"سلام دوست عزیز 🌹\n\nاز حمایت ارزشمندت واقعاً ممنونیم. ❤️\nدرخواست ادمینی شما بررسی شد، اما متأسفانه در حال حاضر امکان پذیرش آن وجود ندارد. این موضوع از ارزش حمایت و همراهی شما کم نمی‌کند. از اعتمادت سپاسگزاریم. 🙏")
            except Exception: log.exception("Could not notify rejected user %s",uid)
        if callback.message: await callback.message.edit_reply_markup(reply_markup=None); await callback.message.answer(f"❌ درخواست {pid} رد شد.")
    else: await callback.answer("عملیات نامعتبر است.",show_alert=True)

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("⛔ دسترسی مدیران لازم است.")
        return
    panel_url = os.getenv("ADMIN_PANEL_URL", "https://telegram-delete-assistant-pro.onrender.com/admin")
    await message.answer(
        "🛠 پنل مدیریت FXI\n"
        f"پنل تحت وب: {panel_url}\n\n"
        "برای مدیریت کامل از پنل وب وارد شو."
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "راهنمای استفاده 🤖\n\n"
        "• پیام متنی بفرست تا هوش مصنوعی انتخاب‌شده پاسخ بدهد.\n"
        "• /ai یا /models — انتخاب هوش مصنوعی\n"
        "• /new — پاک‌کردن سابقهٔ سرویس فعلی\n"
        "• /help — راهنما\n• /support — حمایت و ارسال رسید برای درخواست ادمینی\n\n"
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
    """Send a message only to the provider explicitly selected by this user.

    Deliberately do not fail over to another AI: silent provider switching makes
    the model selector misleading and causes users to receive answers from the
    wrong service.
    """
    if provider_id not in PROVIDERS:
        return "⚠️ سرویس انتخاب‌شده معتبر نیست. با /ai دوباره انتخابش کن."
    if not provider_ready(provider_id):
        return f"🔒 {PROVIDERS[provider_id]['label']} هنوز فعال نشده؛ مدیر باید کلید API مربوطه را در Render تنظیم کند."

    key = (user_id, provider_id)
    async with history_locks[key]:
        history = histories[key]
        if DATABASE_URL:
            try:
                history[:] = await asyncio.to_thread(_load_chat_history_sync, user_id, provider_id)
            except Exception:
                log.exception("Could not load persistent chat history for user=%s", user_id)
        try:
            if provider_id == "openai":
                status, data = await ask_openai(history, user_text)
            elif provider_id == "gemini":
                status, data = await ask_gemini(history, user_text)
            elif provider_id == "claude":
                status, data = await ask_claude(history, user_text)
            elif provider_id == "deepseek":
                status, data = await ask_deepseek(history, user_text)
            elif provider_id == "grok":
                status, data = await ask_grok(history, user_text)
            else:
                status, data = await ask_compatible(provider_id, history, user_text)

            if status >= 400:
                return api_error(provider_id, status, data)

            answer = extract_answer(provider_id, data)
            if not answer:
                log.error("%s returned an empty response: %s", provider_id, str(data)[:500])
                return f"⚠️ سرویس {PROVIDERS[provider_id]['label']} پاسخ خالی برگرداند؛ مدل و تنظیمات API را بررسی کن."

            if DATABASE_URL:
                try:
                    await asyncio.to_thread(_save_chat_turn_sync, user_id, provider_id, user_text, answer)
                except Exception:
                    log.exception("Could not persist chat turn for user=%s provider=%s", user_id, provider_id)
            history.extend([
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": answer},
            ])
            del history[:-MAX_HISTORY_MESSAGES]
            log.info("AI response served by selected provider=%s user_id=%s", provider_id, user_id)
            return f"🤖 پاسخ از {PROVIDERS[provider_id]['label']}\n\n{answer}"

        except asyncio.TimeoutError:
            log.warning("Selected provider %s timed out", provider_id)
            return f"⏳ سرویس انتخاب‌شده ({PROVIDERS[provider_id]['label']}) پاسخ نداد؛ دوباره تلاش کن."
        except aiohttp.ClientError:
            log.exception("Network error calling selected provider %s", provider_id)
            return f"⚠️ اتصال به سرویس انتخاب‌شده ({PROVIDERS[provider_id]['label']}) مشکل دارد."
        except Exception:
            log.exception("Unexpected error handling selected provider %s", provider_id)
            return f"⚠️ هنگام استفاده از {PROVIDERS[provider_id]['label']} خطای پیش‌بینی‌نشده رخ داد."


async def send_long_message(message: Message, text: str):
    for i in range(0, len(text), 3900):
        await message.answer(text[i:i + 3900])


@dp.message()
async def chat(message: Message):
    if not message.from_user or not message.text:
        await message.answer("فعلاً فقط پیام متنی رو پشتیبانی می‌کنم. 🙂")
        return
    remember_user(message.from_user.id)
    if not bot_enabled:
        await message.answer('⛔ ربات موقتاً توسط مدیریت غیرفعال شده است.')
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


app = FastAPI(title="FXI Multi-AI Chat Bot", version="6.0.0", lifespan=lifespan)


@app.post("/auth/telegram")
async def telegram_web_login(payload: TelegramAuthPayload):
    if not verify_telegram_login(payload):
        raise HTTPException(status_code=401, detail="ورود تلگرام معتبر نیست یا منقضی شده است.")
    user = {
        "id": payload.id,
        "first_name": payload.first_name or "",
        "last_name": payload.last_name or "",
        "username": payload.username or "",
        "photo_url": payload.photo_url or "",
    }
    remember_user(payload.id)
    token = SESSION_SERIALIZER.dumps(user)
    result = JSONResponse({"ok": True, "user": user})
    result.set_cookie("fxi_session", token, max_age=7 * 24 * 60 * 60,
                      httponly=True, secure=True, samesite="lax", path="/")
    return result


@app.post("/auth/logout")
async def web_logout():
    result = JSONResponse({"ok": True})
    result.delete_cookie("fxi_session", path="/")
    return result


@app.get("/api/me")
async def web_me(user: dict = Depends(get_web_user)):
    user_id = int(user["id"])
    selected = selected_provider[user_id]
    return {
        **user,
        "selected_provider": selected,
        "providers": [{"id": name, "label": config["label"], "ready": provider_ready(name)}
                      for name, config in PROVIDERS.items()],
    }


@app.post("/api/provider")
async def web_select_provider(payload: ProviderPayload, user: dict = Depends(get_web_user)):
    provider_id = payload.provider_id
    if provider_id not in PROVIDERS:
        raise HTTPException(status_code=404, detail="این سرویس شناخته‌شده نیست.")
    if not provider_ready(provider_id):
        raise HTTPException(status_code=409, detail="این سرویس هنوز توسط مدیر پیکربندی نشده است.")
    selected_provider[int(user["id"])] = provider_id
    return {"selected_provider": provider_id, "label": PROVIDERS[provider_id]["label"]}


@app.get("/api/history")
async def web_history(user: dict = Depends(get_web_user)):
    user_id = int(user["id"])
    provider_id = selected_provider[user_id]
    if DATABASE_URL:
        try:
            messages = await asyncio.to_thread(_load_chat_history_sync, user_id, provider_id, 40)
            histories[(user_id, provider_id)][:] = messages[-MAX_HISTORY_MESSAGES:]
            return {"provider_id": provider_id, "messages": messages}
        except Exception:
            log.exception("Persistent history read failed for user=%s", user_id)
            raise HTTPException(status_code=503, detail="بازیابی تاریخچه از پایگاه داده ممکن نشد.")
    return {"provider_id": provider_id, "messages": histories[(user_id, provider_id)][-40:]}


@app.post("/api/reset")
async def web_reset(user: dict = Depends(get_web_user)):
    user_id = int(user["id"])
    provider_id = selected_provider[user_id]
    if DATABASE_URL:
        try:
            await asyncio.to_thread(_clear_chat_history_sync, user_id, provider_id)
        except Exception:
            log.exception("Persistent history reset failed for user=%s", user_id)
            raise HTTPException(status_code=503, detail="پاک‌کردن تاریخچه از پایگاه داده ممکن نشد.")
    histories[(user_id, provider_id)].clear()
    return {"ok": True}


@app.post("/api/chat")
async def web_chat(payload: ChatPayload, user: dict = Depends(get_web_user)):
    if not bot_enabled:
        raise HTTPException(status_code=503, detail="ربات موقتاً غیرفعال است.")
    user_id = int(user["id"])
    provider_id = selected_provider[user_id]
    if not provider_ready(provider_id):
        raise HTTPException(status_code=409, detail="مدل فعلی فعال نیست؛ یک مدل آماده انتخاب کن.")
    answer = await ask_ai(user_id, provider_id, payload.message.strip())
    return {"answer": answer, "provider_id": provider_id,
            "provider_label": PROVIDERS[provider_id]["label"]}


@app.get("/")
@app.get("/app")
async def user_web_app():
    return FileResponse(STATIC_DIR / "user.html")




@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(_: str = Depends(require_admin)):
    return HTMLResponse(ADMIN_PANEL_HTML)


@app.get("/admin/api/status")
async def admin_status(_: str = Depends(require_admin)):
    return {
        "bot_enabled": bot_enabled,
        "users_count": len(admin_data.get("users", [])),
        "admins": sorted(set(ADMIN_IDS) | set(admin_data.get("admins", []))),
        "primary_admins": sorted(ADMIN_IDS),
        "recent_users": admin_data.get("users", [])[-50:],
        "providers": [name for name in PROVIDERS if provider_ready(name)],
        "system_prompt": admin_data.get("system_prompt", SYSTEM_PROMPT),
    }



@app.get("/admin/api/conversations")
async def admin_conversations(_: str = Depends(require_admin)):
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="برای مشاهده تاریخچه دائمی، DATABASE_URL را در Render تنظیم کن.")
    try:
        items = await asyncio.to_thread(_admin_conversation_list_sync, 100)
        return {"items": items, "storage": "postgresql"}
    except Exception:
        log.exception("Admin conversation index failed")
        raise HTTPException(status_code=503, detail="خواندن فهرست مکالمات از پایگاه داده ممکن نشد.")


@app.get("/admin/api/conversations/{user_id}")
async def admin_conversation(user_id: int, _: str = Depends(require_admin)):
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="برای مشاهده تاریخچه دائمی، DATABASE_URL را در Render تنظیم کن.")
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="شناسه کاربر نامعتبر است.")
    try:
        messages = await asyncio.to_thread(_admin_conversation_sync, user_id, 100)
        return {"user_id": user_id, "messages": messages}
    except Exception:
        log.exception("Admin conversation read failed for user=%s", user_id)
        raise HTTPException(status_code=503, detail="خواندن مکالمه ممکن نشد.")


@app.post("/admin/api/admins")
async def add_admin(payload: AdminIdPayload, _: str = Depends(require_admin)):
    if payload.user_id <= 0:
        raise HTTPException(status_code=400, detail="شناسه کاربر نامعتبر است")
    if payload.user_id in ADMIN_IDS or payload.user_id in admin_data["admins"]:
        return {"message": "این کاربر از قبل مدیر است"}
    admin_data["admins"].append(payload.user_id)
    save_admin_data()
    return {"message": f"مدیر {payload.user_id} اضافه شد"}


@app.delete("/admin/api/admins/{user_id}")
async def remove_admin(user_id: int, _: str = Depends(require_admin)):
    if user_id in ADMIN_IDS:
        raise HTTPException(status_code=400, detail="مدیر اصلی از ADMIN_IDS حذف می‌شود")
    if user_id not in admin_data["admins"]:
        raise HTTPException(status_code=404, detail="این مدیر پیدا نشد")
    admin_data["admins"].remove(user_id)
    save_admin_data()
    return {"message": f"مدیر {user_id} حذف شد"}


@app.post("/admin/api/bot-state")
async def set_bot_state(payload: BotStatePayload, _: str = Depends(require_admin)):
    global bot_enabled
    bot_enabled = payload.enabled
    admin_data["bot_enabled"] = bot_enabled
    save_admin_data()
    return {"message": "ربات روشن شد" if bot_enabled else "ربات خاموش شد"}


@app.post("/admin/api/broadcast")
async def broadcast(payload: BroadcastPayload, _: str = Depends(require_admin)):
    if not bot:
        raise HTTPException(status_code=503, detail="اتصال ربات تلگرام فعال نیست")
    sent = failed = 0
    for user_id in list(admin_data.get("users", [])):
        try:
            await bot.send_message(user_id, payload.text)
            sent += 1
        except Exception as exc:
            failed += 1
            log.warning("Broadcast failed for user %s: %s", user_id, type(exc).__name__)
        await asyncio.sleep(0.04)
    return {"sent": sent, "failed": failed}


@app.post("/admin/api/prompt")
async def update_prompt(payload: PromptPayload, _: str = Depends(require_admin)):
    global SYSTEM_PROMPT
    SYSTEM_PROMPT = payload.prompt.strip()
    admin_data["system_prompt"] = SYSTEM_PROMPT
    save_admin_data()
    return {"message": "دستورالعمل هوش مصنوعی ذخیره شد"}


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
