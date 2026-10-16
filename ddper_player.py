"""DDPER player profile lookup for the main Telegram bot.

Fetches the public player page, extracts server-rendered text/metadata, and
offers a direct link to the GoRes section. It never requires DDPER credentials.
"""
import asyncio
import html
import json
import logging
import re
from html.parser import HTMLParser
from urllib.parse import quote

import aiohttp
from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

log = logging.getLogger(__name__)
BASE_URL = "https://ddper.ir/players/"


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0
        self.title = []
        self.in_title = False
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag == "meta" and attrs.get("name") in ("description", "og:description", "og:title"):
            self.meta[attrs["name"]] = attrs.get("content", "")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self.skip:
            self.skip -= 1
        if tag == "title":
            self.in_title = False
        if tag in ("p", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "br"):
            self.parts.append("\n")

    def handle_data(self, data):
        value = " ".join(data.split())
        if not value:
            return
        if self.in_title:
            self.title.append(value)
        if not self.skip:
            self.parts.append(value)


def _clean(value):
    value = html.unescape(value or "")
    value = re.sub(r"[ \t\xa0]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


async def _fetch_profile(player):
    url = BASE_URL + quote(player, safe="")
    timeout = aiohttp.ClientTimeout(total=18, connect=7)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; DDPERTelegramBot/1.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "fa,en;q=0.8",
    }
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url, allow_redirects=True) as response:
            if response.status == 404:
                return None, url, "بازیکن یا صفحه‌ای با این نام پیدا نشد."
            if response.status >= 400:
                return None, url, f"سایت DDPER پاسخ HTTP {response.status} داد."
            raw = await response.text(errors="replace")

    parser = _PageText()
    try:
        parser.feed(raw)
    except Exception:
        log.debug("DDPER HTML parsing failed", exc_info=True)
    title = _clean(" ".join(parser.title))
    visible = _clean("\n".join(parser.parts))
    # Some SPA pages expose their initial profile data in JSON script tags.
    # Only use compact, relevant values if visible text is nearly empty.
    if len(visible) < 80:
        candidates = []
        for pattern in (
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
        ):
            for match in re.finditer(pattern, raw, flags=re.I | re.S):
                try:
                    data = json.loads(html.unescape(match.group(1)))
                    candidates.append(json.dumps(data, ensure_ascii=False))
                except Exception:
                    continue
        if candidates:
            visible = _clean(" ".join(candidates))
    if len(visible) < 40:
        description = parser.meta.get("description") or parser.meta.get("og:description", "")
        visible = _clean((title + "\n" + description).strip())
    if not visible:
        return None, url, "صفحه باز شد، اما اطلاعات قابل‌خواندن از پاسخ سایت دریافت نشد."
    # Drop repeated blank/boilerplate whitespace; Telegram has a 4096-char limit.
    visible = visible[:3650]
    return visible, url, None


def register_ddper_handlers(dp):
    @dp.message(Command("ddper"))
    async def ddper_command(message: Message):
        parts = (message.text or "").split(maxsplit=1)
        player = parts[1].strip().lstrip("@") if len(parts) > 1 else ""
        if not player:
            return await message.answer(
                "🎮 جست‌وجوی بازیکن DDPER\n\n"
                "نام بازیکن را بعد از دستور بفرست؛ مثلاً:\n"
                "/ddper fxi"
            )
        if len(player) > 64 or not re.fullmatch(r"[\w.-]+", player, flags=re.UNICODE):
            return await message.answer("نام بازیکن نامعتبر است. فقط نام کاربری را بفرست.")
        status = await message.answer("🔎 دارم اطلاعات عمومی بازیکن را از DDPER می‌گیرم…")
        try:
            text, url, error = await _fetch_profile(player)
            if error:
                await status.edit_text(
                    f"⚠️ {error}\n\n"
                    f"صفحه بازیکن: {url}\n"
                    "اگر اطلاعات صفحه با JavaScript بارگذاری شود، ممکن است سایت اجازه استخراج مستقیم ندهد."
                )
                return
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎯 مشاهده بخش GoRes", url=url + "#gores")],
                [InlineKeyboardButton(text="🌐 باز کردن پروفایل DDPER", url=url)],
            ])
            await status.edit_text(
                f"🎮 اطلاعات عمومی DDPER — {player}\n"
                f"منبع: {url}\n\n{text}",
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
        except asyncio.TimeoutError:
            await status.edit_text(f"⏳ سایت DDPER دیر پاسخ داد. دوباره امتحان کن.\n{BASE_URL + quote(player, safe='')}")
        except aiohttp.ClientError:
            await status.edit_text("❌ اتصال به DDPER برقرار نشد. بعداً دوباره امتحان کن.")
        except Exception:
            log.exception("DDPER profile lookup failed")
            await status.edit_text("❌ هنگام خواندن پروفایل خطایی رخ داد. لطفاً کمی بعد دوباره تلاش کن.")

    @dp.message(F.text.regexp(re.compile(r"(?i)^ddper\s+([\w.-]+)\s*$")))
    async def ddper_natural_text(message: Message):
        match = re.fullmatch(r"(?i)ddper\s+([\w.-]+)", (message.text or "").strip())
        if not match:
            return
        # Delegate through the same public command behavior without fabricating a Message object.
        player = match.group(1)
        status = await message.answer("🔎 دارم اطلاعات عمومی بازیکن را از DDPER می‌گیرم…")
        try:
            text, url, error = await _fetch_profile(player)
            if error:
                return await status.edit_text(f"⚠️ {error}\n\n{url}")
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎯 مشاهده بخش GoRes", url=url + "#gores")],
                [InlineKeyboardButton(text="🌐 باز کردن پروفایل DDPER", url=url)],
            ])
            await status.edit_text(f"🎮 اطلاعات عمومی DDPER — {player}\nمنبع: {url}\n\n{text}",
                                   reply_markup=keyboard, disable_web_page_preview=True)
        except Exception:
            log.exception("DDPER natural lookup failed")
            await status.edit_text("❌ دریافت اطلاعات DDPER ناموفق بود؛ کمی بعد دوباره تلاش کن.")
