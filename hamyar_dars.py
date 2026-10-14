"""Telegram-native study browser for Hamyar's grade-10 index.
Only short excerpts and summaries are displayed; the bot does not mirror full pages.
"""
import asyncio
import logging
from html.parser import HTMLParser
from urllib.parse import urljoin

import aiohttp
from aiogram import F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message

log = logging.getLogger(__name__)
BASE = "https://hamyar.me"
INDEX = BASE + "/topics/%D9%BE%D8%A7%DB%8C%D9%87-%D8%AF%D9%87%D9%85/"
CACHE = {"at": 0, "items": [], "text": ""}
CACHE_TTL = 900


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.current_link = None
        self.in_title = False
        self.title_parts = []
        self.in_heading = False
        self.in_main = False
        self.depth = 0
        self.text_parts = []
        self.heading_parts = []
        self.capture_title = False
        self.capture_text = False
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.capture_title = True
        if tag in ("script", "style", "nav", "footer", "header"):
            self.skip_depth += 1
        if tag == "a" and not self.skip_depth:
            self.current_link = {"title": "", "url": attrs.get("href", "")}
        if tag in ("h1", "h2", "h3", "h4"):
            self.in_heading = True
        if tag in ("p", "li", "h1", "h2", "h3", "h4"):
            self.capture_text = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.capture_title = False
        if tag == "a" and self.current_link is not None:
            title = " ".join(self.current_link["title"].split())
            url = self.current_link["url"]
            if title and url and not url.startswith(("#", "javascript:")):
                self.links.append({"title": title, "url": urljoin(BASE, url)})
            self.current_link = None
        if tag in ("h1", "h2", "h3", "h4"):
            self.in_heading = False
        if tag in ("p", "li", "h1", "h2", "h3", "h4"):
            self.capture_text = False
        if tag in ("script", "style", "nav", "footer", "header") and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if self.skip_depth:
            return
        value = " ".join(data.split())
        if not value:
            return
        if self.capture_title:
            self.title_parts.append(value)
        if self.current_link is not None:
            self.current_link["title"] += " " + value
        if self.capture_text:
            self.text_parts.append(value)
            if self.in_heading:
                self.heading_parts.append(value)


async def fetch_page(url):
    timeout = aiohttp.ClientTimeout(total=18, connect=7)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; HamyarDarsBot/1.0; educational navigation)"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url, allow_redirects=True) as response:
            if response.status >= 400:
                raise RuntimeError(f"صفحه آموزشی فعلاً پاسخ‌گو نیست (HTTP {response.status}).")
            body = await response.text(errors="replace")
            parser = PageParser()
            parser.feed(body)
            return parser


async def get_index():
    now = asyncio.get_running_loop().time()
    if CACHE["items"] and now - CACHE["at"] < CACHE_TTL:
        return CACHE["items"]
    parser = await fetch_page(INDEX)
    # Keep only real content links and discard navigation, duplicate links, and external domains.
    items, seen = [], set()
    for item in parser.links:
        if not item["url"].startswith(BASE + "/"):
            continue
        title = item["title"].strip()
        if len(title) < 4 or title in seen:
            continue
        if any(x in title.lower() for x in ("قبلی", "بعدی", "برنامه همیار", "پایه دوم", "پایه سوم", "پایه یازدهم", "پایه دوازدهم")):
            continue
        seen.add(title)
        items.append(item)
    CACHE.update({"at": now, "items": items, "text": " ".join(parser.text_parts)})
    return items


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def home_keyboard():
    return keyboard([
        [InlineKeyboardButton(text="📘 گام‌به‌گام و پاسخ تمرین‌ها", callback_data="hd:type:گام")],
        [InlineKeyboardButton(text="📝 نمونه‌سؤال‌های امتحانی", callback_data="hd:type:نمونه سوال")],
        [InlineKeyboardButton(text="📒 جزوه و درسنامه", callback_data="hd:type:جزوه")],
        [InlineKeyboardButton(text="🎬 آموزش تصویری و ویدیو", callback_data="hd:type:آموزش")],
        [InlineKeyboardButton(text="🔎 جست‌وجوی درس یا صفحه", callback_data="hd:search")],
    ])


def kind_matches(title, kind):
    t = title.replace("‌", " ").lower()
    if kind == "گام":
        return any(x in t for x in ("گام به گام", "جواب", "پاسخ", "سوالات متن", "سوال متن"))
    if kind == "نمونه سوال":
        return "نمونه سوال" in t or "نمونه‌سوال" in t
    if kind == "جزوه":
        return "جزوه" in t or "درسنامه" in t or "خلاصه" in t
    if kind == "آموزش":
        return any(x in t for x in ("ویدیو", "ویدئو", "آموزش تصویری"))
    return True


def search_keyboard(items, page=0):
    page_size = 8
    subset = items[page * page_size:(page + 1) * page_size]
    rows = [[InlineKeyboardButton(text=("📄 " + x["title"])[:62], callback_data=f"hd:item:{items.index(x)}")] for x in subset]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"hd:page:{page-1}"))
    if (page + 1) * page_size < len(items):
        nav.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"hd:page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 منوی همیار درس", callback_data="hd:home")])
    return keyboard(rows)


def clean_summary(parser):
    # Short, useful snippet only; do not mirror complete third-party articles.
    chunks = []
    for part in parser.text_parts:
        part = " ".join(part.split())
        if len(part) >= 35 and part not in chunks:
            chunks.append(part)
        if sum(map(len, chunks)) > 1200:
            break
    summary = "\n\n".join(chunks)
    if len(summary) > 1100:
        summary = summary[:1100].rsplit(" ", 1)[0] + "…"
    return summary or "خلاصهٔ متنی در این صفحه پیدا نشد. این مطلب ممکن است به شکل تصویر یا فایل ارائه شده باشد."


def register_hamyar_handlers(dp):
    @dp.callback_query(F.data == "hd:home")
    async def hd_home(c: CallbackQuery):
        await c.answer()
        await c.message.answer(
            "📚 همیار درس | پایه دهم\n\n"
            "مطالب آموزشی پایه دهم را همین‌جا در تلگرام جست‌وجو و مرور کن؛ نیازی به باز کردن سایت نیست.\n"
            "از بخش موردنیازت انتخاب کن:",
            reply_markup=home_keyboard()
        )

    @dp.callback_query(F.data.startswith("hd:type:"))
    async def hd_type(c: CallbackQuery):
        await c.answer("در حال آماده‌سازی فهرست…")
        kind = c.data.split(":", 2)[2]
        try:
            items = await get_index()
            found = [x for x in items if kind_matches(x["title"], kind)]
            if not found:
                return await c.message.answer("برای این دسته فعلاً موردی در فهرست پیدا نشد. از جست‌وجو استفاده کن.")
            await c.message.answer(
                f"📚 همیار درس — {kind}\n"
                f"{len(found)} عنوان مرتبط پیدا شد. برای دیدن خلاصه، یک مورد را انتخاب کن:",
                reply_markup=search_keyboard(found[:80])
            )
        except Exception:
            log.exception("Hamyar index fetch failed")
            await c.message.answer("فعلاً نتونستم فهرست درس‌ها رو دریافت کنم. چند دقیقه بعد دوباره امتحان کن.")

    @dp.callback_query(F.data == "hd:search")
    async def hd_search(c: CallbackQuery):
        await c.answer()
        await c.message.answer(
            "🔎 نام درس، نوع مطلب یا شماره صفحه را در همین گفتگو بفرست؛ مثلاً:\n"
            "• فیزیک دهم نمونه سوال\n• گام به گام ریاضی\n• صفحه ۴۲ هندسه"
        )

    @dp.callback_query(F.data.startswith("hd:page:"))
    async def hd_page(c: CallbackQuery):
        await c.answer()
        try:
            items = await get_index()
            page = max(0, int(c.data.rsplit(":", 1)[1]))
            await c.message.answer("📚 ادامهٔ فهرست:", reply_markup=search_keyboard(items[:80], page))
        except Exception:
            await c.message.answer("فهرست فعلاً در دسترس نیست.")

    @dp.callback_query(F.data.startswith("hd:item:"))
    async def hd_item(c: CallbackQuery):
        await c.answer("در حال دریافت مطلب…")
        try:
            items = await get_index()
            index = int(c.data.rsplit(":", 1)[1])
            if index < 0 or index >= len(items):
                return await c.message.answer("این مورد دیگر در فهرست موجود نیست؛ منو را دوباره باز کن.")
            item = items[index]
            parser = await fetch_page(item["url"])
            title = " ".join(parser.title_parts).strip() or item["title"]
            excerpt = clean_summary(parser)
            # Do not expose a site-entry link or direct users out of Telegram.
            await c.message.answer(
                f"📘 {item['title']}\n\n{excerpt}\n\n"
                "ℹ️ این نمایش، خلاصه‌ای کوتاه از مطلب آموزشی است؛ برای حفظ حقوق ناشر، متن کامل صفحه در ربات بازنشر نمی‌شود.",
                reply_markup=keyboard([[InlineKeyboardButton(text="⬅️ بازگشت به فهرست", callback_data="hd:home")]])
            )
        except Exception:
            log.exception("Hamyar article fetch failed")
            await c.message.answer("این مطلب فعلاً دریافت نشد. کمی بعد دوباره تلاش کن.")

    @dp.message(F.text & ~F.text.startswith("/"))
    async def hd_search_text(m: Message):
        text = " ".join((m.text or "").replace("‌", " ").lower().split())
        triggers = ("همیار درس", "گام به گام", "گام‌به‌گام", "نمونه سوال", "نمونه‌سوال", "جزوه", "درسنامه", "صفحه ")
        if not any(x in text for x in triggers):
            return
        try:
            items = await get_index()
            terms = [x for x in text.split() if len(x) > 2 and x not in {"همیار", "درس", "دهم", "برای", "صفحه", "جواب", "سوال", "نمونه"}]
            found = [x for x in items if all(term in x["title"].replace("‌", " ").lower() for term in terms[:3])] if terms else items
            if not found:
                found = [x for x in items if any(term in x["title"].replace("‌", " ").lower() for term in terms[:3])]
            if not found:
                return await m.answer("چیزی با این عبارت در فهرست پایه دهم پیدا نکردم. نام درس را کوتاه‌تر بنویس.")
            await m.answer(
                f"🔎 همیار درس — {len(found)} نتیجه برای «{m.text[:80]}»",
                reply_markup=search_keyboard(found[:80])
            )
        except Exception:
            log.exception("Hamyar search failed")
            await m.answer("جست‌وجوی همیار درس فعلاً در دسترس نیست؛ کمی بعد دوباره امتحان کن.")
