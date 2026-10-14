"""Telegram-native interface for browsing Hamyar educational indexes.
Shows navigable titles and short excerpts, not full copyrighted pages or external links.
"""
import asyncio
import logging
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import aiohttp
from aiogram import F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, BufferedInputFile

log = logging.getLogger(__name__)
BASE = "https://hamyar.me"
HOME = BASE + "/"
CACHE_TTL = 900
CHAT_CACHE = {}
GRADE_WORDS = {
    1: "اول", 2: "دوم", 3: "سوم", 4: "چهارم", 5: "پنجم", 6: "ششم",
    7: "هفتم", 8: "هشتم", 9: "نهم", 10: "دهم", 11: "یازدهم", 12: "دوازدهم",
}


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.current_link = None
        self.title_parts = []
        self.text_parts = []
        self.capture_title = False
        self.capture_text = False
        self.skip_depth = 0
        self.in_heading = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.capture_title = True
        if tag in ("script", "style", "nav", "footer", "header", "noscript"):
            self.skip_depth += 1
        if tag in ("iframe", "video", "source", "embed") and not self.skip_depth:
            src = attrs.get("src") or attrs.get("data-src") or attrs.get("data-video-src")
            if src:
                self.links.append({"title": attrs.get("title") or attrs.get("aria-label") or tag, "url": urljoin(BASE, src)})
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
            href = self.current_link["url"]
            if title and href and not href.startswith(("#", "javascript:", "mailto:")):
                self.links.append({"title": title, "url": urljoin(BASE, href)})
            self.current_link = None
        if tag in ("h1", "h2", "h3", "h4"):
            self.in_heading = False
        if tag in ("p", "li", "h1", "h2", "h3", "h4"):
            self.capture_text = False
        if tag in ("script", "style", "nav", "footer", "header", "noscript") and self.skip_depth:
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


async def fetch_page(url):
    if urlparse(url).netloc not in ("hamyar.me", "www.hamyar.me"):
        raise RuntimeError("آدرس خارج از دامنهٔ مجاز است.")
    timeout = aiohttp.ClientTimeout(total=20, connect=8)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; HamyarDarsBot/1.0; educational navigation)"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url, allow_redirects=True) as response:
            if response.status >= 400:
                raise RuntimeError(f"صفحه آموزشی فعلاً پاسخ‌گو نیست (HTTP {response.status}).")
            body = await response.text(errors="replace")
            parser = PageParser()
            parser.feed(body)
            return parser


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def home_keyboard():
    rows = []
    for start in (1, 5, 9):
        row = []
        for grade in range(start, min(start + 4, 13)):
            row.append(InlineKeyboardButton(
                text=f"پایه {GRADE_WORDS[grade]}",
                callback_data=f"hd:grade:{grade}"
            ))
        rows.append(row)
    rows.extend([
        [InlineKeyboardButton(text="🆕 تازه‌های آموزشی", callback_data="hd:latest")],
        [InlineKeyboardButton(text="🔎 جست‌وجو در مطالب", callback_data="hd:search")],
    ])
    return keyboard(rows)


def kind_keyboard(grade):
    return keyboard([
        [InlineKeyboardButton(text="📘 گام‌به‌گام و پاسخ تمرین‌ها", callback_data=f"hd:kind:{grade}:گام")],
        [InlineKeyboardButton(text="📝 نمونه‌سؤال‌های امتحانی", callback_data=f"hd:kind:{grade}:نمونه")],
        [InlineKeyboardButton(text="📒 جزوه و درسنامه", callback_data=f"hd:kind:{grade}:جزوه")],
        [InlineKeyboardButton(text="📥 فایل‌های PDF و جزوه‌های دانلودی", callback_data=f"hd:kind:{grade}:PDF")],
        [InlineKeyboardButton(text="🎬 آموزش ویدئویی", callback_data=f"hd:kind:{grade}:ویدیو")],
        [InlineKeyboardButton(text="🧪 آزمون و تمرین", callback_data=f"hd:kind:{grade}:آزمون")],
        [InlineKeyboardButton(text="📚 همهٔ مطالب این پایه", callback_data=f"hd:all:{grade}")],
        [InlineKeyboardButton(text="⬅️ انتخاب پایه", callback_data="hd:home")],
    ])


async def get_grade_links():
    now = asyncio.get_running_loop().time()
    cached = CHAT_CACHE.get("_grades")
    if cached and now - cached["at"] < CACHE_TTL:
        return cached["items"]
    parser = await fetch_page(HOME)
    items, seen = [], set()
    for link in parser.links:
        title = link["title"].replace("‌", " ")
        match = re.search(r"پایه\s*(اول|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم|یازدهم|دوازدهم)", title)
        if not match:
            continue
        word = match.group(1)
        grade = next((n for n, w in GRADE_WORDS.items() if w == word), None)
        if not grade or grade in seen or not link["url"].startswith(BASE + "/"):
            continue
        seen.add(grade)
        items.append({"grade": grade, "title": f"پایه {word}", "url": link["url"]})
    if len(items) < 8:
        # Reliable fallback for the public grade-topic routes.
        items = [{"grade": n, "title": f"پایه {GRADE_WORDS[n]}", "url": f"{BASE}/topics/{['','پایه-اول','پایه-دوم','پایه-سوم','پایه-چهارم','پایه-پنجم','پایه-ششم','پایه-هفتم','پایه-هشتم','پایه-نهم','پایه-دهم','پایه-یازدهم','پایه-دوازدهم'][n]}/"} for n in range(1, 13)]
    CHAT_CACHE["_grades"] = {"at": now, "items": items}
    return items


async def get_grade_items(grade):
    now = asyncio.get_running_loop().time()
    key = f"_grade_{grade}"
    cached = CHAT_CACHE.get(key)
    if cached and now - cached["at"] < CACHE_TTL:
        return cached["items"]
    grades = await get_grade_links()
    target = next((x for x in grades if x["grade"] == grade), None)
    if not target:
        raise RuntimeError("پایهٔ انتخاب‌شده در فهرست موجود نیست.")
    parser = await fetch_page(target["url"])
    items, seen = [], set()
    for link in parser.links:
        title = " ".join(link["title"].replace("‌", " ").split())
        url = link["url"]
        media_kind = resource_type(url, title)
        if not title or url in seen:
            continue
        if not url.startswith(BASE + "/") and media_kind not in ("pdf", "video", "link"):
            continue
        if url.rstrip("/") == target["url"].rstrip("/"):
            continue
        if title in ("قبلی", "بعدی", "صفحه بعد", "صفحه قبل") or len(title) < 5:
            continue
        seen.add(url)
        items.append({"title": title[:180], "url": url, "grade": grade})
    CHAT_CACHE[key] = {"at": now, "items": items}
    return items


def classify(title, kind, url=""):
    t = title.replace("‌", " ").lower()
    parsed_path = urlparse(url).path.lower()
    if kind == "PDF":
        return parsed_path.endswith(".pdf") or any(x in t for x in ("pdf", "پی دی اف", "دانلود فایل", "فایل pdf", "جزوه دانلود"))
    if kind == "گام":
        return any(x in t for x in ("گام به گام", "گام‌به‌گام", "حل تمرین", "پاسخ تمرین", "جواب", "پاسخ", "فعالیت", "تمرین", "کار در کلاس", "معنی "))
    if kind == "نمونه":
        return "نمونه سوال" in t or "نمونه‌سوال" in t or "نمونه سؤال" in t
    if kind == "جزوه":
        return any(x in t for x in ("جزوه", "درسنامه", "خلاصه"))
    if kind == "ویدیو":
        host = (urlparse(url).hostname or "").lower()
        return (
            parsed_path.endswith((".mp4", ".m4v", ".webm", ".mov", ".m3u8"))
            or any(x in t for x in ("ویدیو", "ویدئو", "فیلم آموزشی", "آموزش تصویری", "ویدئویی"))
            or any(x in host for x in ("youtube.com", "youtu.be", "aparat.com", "namasha.com", "vidio.com"))
        )
    if kind == "آزمون":
        return any(x in t for x in ("آزمون", "تست", "امتحان"))
    return True


async def collect_grade_resources(grade, kind, limit=16):
    """Inspect a bounded set of lesson pages for downloadable PDFs and playable video links."""
    items = await get_grade_items(grade)
    wanted = {"pdf"} if kind == "PDF" else {"video", "link"}
    collected, seen = [], set()
    for item in items:
        direct = resource_type(item.get("url", ""), item.get("title", ""))
        if direct in wanted and item.get("url") not in seen:
            seen.add(item["url"])
            collected.append({"title": item.get("title", "فایل آموزشی")[:160], "url": item["url"], "grade": grade})

    semaphore = asyncio.Semaphore(4)

    async def inspect(item):
        async with semaphore:
            try:
                parser = await fetch_page(item["url"])
            except Exception:
                return []
            found = []
            for link in parser.links:
                url = link.get("url", "")
                title = " ".join((link.get("title") or "").split()) or item.get("title", "منبع آموزشی")
                if urlparse(url).scheme not in ("http", "https"):
                    continue
                media = resource_type(url, title)
                if media in wanted:
                    found.append({"title": (item.get("title", "") + " — " + title)[:180], "url": url, "grade": grade})
            return found

    inspected = await asyncio.gather(*(inspect(item) for item in items[:limit]), return_exceptions=True)
    for result in inspected:
        if isinstance(result, list):
            for item in result:
                if item["url"] not in seen:
                    seen.add(item["url"])
                    collected.append(item)
    return collected[:80]


def set_visible(chat_id, items):
    CHAT_CACHE[f"_visible_{chat_id}"] = items


def get_visible(chat_id):
    return CHAT_CACHE.get(f"_visible_{chat_id}", [])


def results_keyboard(chat_id, page=0):
    items = get_visible(chat_id)
    size = 8
    rows = []
    for i in range(page * size, min((page + 1) * size, len(items))):
        item = items[i]
        url = item.get("url", "")
        path = urlparse(url).path.lower()
        media = resource_type(url, item.get("title", ""))
        icon = "📥" if media == "pdf" else ("🎬" if media in ("video", "link") else "📘")
        rows.append([InlineKeyboardButton(text=(icon + " " + item["title"])[:62], callback_data=f"hd:item:{i}")])
    nav = []
    if page:
        nav.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"hd:page:{page-1}"))
    if (page + 1) * size < len(items):
        nav.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"hd:page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 منوی همیار درس", callback_data="hd:home")])
    return keyboard(rows)


def short_summary(parser):
    chunks, total = [], 0
    for part in parser.text_parts:
        part = " ".join(part.split())
        if len(part) >= 35 and part not in chunks:
            chunks.append(part)
            total += len(part)
        if total >= 1000:
            break
    summary = "\n\n".join(chunks)
    if len(summary) > 950:
        summary = summary[:950].rsplit(" ", 1)[0] + "…"
    return summary or "خلاصهٔ متنی در این صفحه پیدا نشد؛ ممکن است محتوا به شکل تصویر یا فایل باشد."




def resource_type(url, title=""):
    parsed = urlparse(url)
    path = parsed.path.lower()
    host = (parsed.hostname or "").lower()
    label = (title or "").replace("‌", " ").lower()
    if path.endswith(".pdf") or "application/pdf" in label or "فایل pdf" in label or "پی دی اف" in label:
        return "pdf"
    if "pdf" in label and any(word in label for word in ("دانلود", "دریافت", "فایل", "جزوه", "کتاب")):
        return "pdf"
    if path.endswith((".mp4", ".m4v", ".webm", ".mov")):
        return "video"
    if any(x in host for x in ("youtube.com", "youtu.be", "aparat.com", "namasha.com", "vidio.com")):
        return "link"
    if host not in ("hamyar.me", "www.hamyar.me") and any(x in label for x in ("ویدیو", "ویدئو", "فیلم آموزشی", "پخش ویدئو")):
        return "link"
    return None


async def send_resource(callback, url, title, kind):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.hostname.lower() in ("localhost", "127.0.0.1"):
        return await callback.message.answer("آدرس فایل معتبر نیست.")
    try:
        await callback.answer("در حال دریافت فایل…")
    except Exception:
        pass
    try:
        timeout = aiohttp.ClientTimeout(total=45, connect=10)
        headers = {"User-Agent": "Mozilla/5.0 (compatible; HamyarDarsBot/1.1)"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as response:
                if response.status >= 400:
                    return await callback.message.answer("فایل فعلاً از میزبان دریافت نشد؛ کمی بعد دوباره امتحان کن.")
                data = await response.content.read(45 * 1024 * 1024 + 1)
                if len(data) > 45 * 1024 * 1024:
                    if (parsed.hostname or "").lower() in ("hamyar.me", "www.hamyar.me"):
                        return await callback.message.answer("حجم این فایل از سقف ارسال مستقیم ربات بیشتر است؛ برای اینکه به سایت هدایت نشوی، لینک سایت نمایش داده نمی‌شود.")
                    return await callback.message.answer(
                        "حجم فایل برای ارسال مستقیم از ربات زیاد است.",
                        reply_markup=keyboard([[InlineKeyboardButton(text="باز کردن فایل", url=url)]])
                    )
                content_type = (response.headers.get("Content-Type") or "").lower()
                if kind == "pdf" and "pdf" not in content_type and not parsed.path.lower().endswith(".pdf"):
                    return await callback.message.answer("میزبان به‌جای PDF فایل دیگری برگرداند؛ ارسال لغو شد.")
                filename = parsed.path.rsplit("/", 1)[-1] or ("video.mp4" if kind == "video" else "lesson.pdf")
                filename = filename.split("?")[0][:120]
                file = BufferedInputFile(data, filename=filename)
                if kind == "pdf":
                    await callback.message.answer_document(file, caption=("📄 " + (title or filename))[:900])
                elif kind == "video":
                    await callback.message.answer_video(file, caption=("🎬 " + (title or filename))[:900])
                else:
                    await callback.message.answer(
                        "🎬 برای پخش این آموزش از دکمهٔ زیر استفاده کن.",
                        reply_markup=keyboard([[InlineKeyboardButton(text="▶️ پخش آموزش", url=url)]])
                    )
    except Exception:
        log.exception("Hamyar resource download failed")
        await callback.message.answer("دریافت فایل ناموفق بود؛ احتمالاً میزبان دسترسی مستقیم نمی‌دهد.")



def register_hamyar_handlers(dp):
    @dp.callback_query(F.data == "hd:home")
    async def hd_home(c: CallbackQuery):
        await c.answer()
        await c.message.answer(
            "🎓 همیار درس\n\n"
            "کتاب‌ها و مطالب آموزشی پایه‌های اول تا دوازدهم را از داخل تلگرام پیدا کن. "
            "مطالب در دسته‌های گام‌به‌گام، نمونه‌سؤال، جزوه، ویدیو و آزمون مرتب شده‌اند.\n\n"
            "اول پایهٔ تحصیلی‌ات را انتخاب کن:",
            reply_markup=home_keyboard()
        )

    @dp.callback_query(F.data.startswith("hd:grade:"))
    async def hd_grade(c: CallbackQuery):
        await c.answer("در حال دریافت فهرست…")
        grade = int(c.data.rsplit(":", 1)[1])
        try:
            items = await get_grade_items(grade)
            await c.message.answer(
                f"🎓 همیار درس | پایه {GRADE_WORDS[grade]}\n"
                f"در این پایه {len(items)} عنوان آموزشی پیدا شد. دستهٔ موردنظرت را انتخاب کن:",
                reply_markup=kind_keyboard(grade)
            )
        except Exception:
            log.exception("Hamyar grade fetch failed")
            await c.message.answer("فعلاً دریافت فهرست این پایه ممکن نشد. کمی بعد دوباره امتحان کن.")

    @dp.callback_query(F.data.startswith("hd:all:"))
    async def hd_all(c: CallbackQuery):
        await c.answer()
        grade = int(c.data.rsplit(":", 1)[1])
        try:
            items = await get_grade_items(grade)
            set_visible(c.message.chat.id, items)
            if not items:
                return await c.message.answer(
                    "برای این پایه فعلاً عنوانی دریافت نشد. می‌توانی دوباره تلاش کنی یا پایه‌ای دیگر را انتخاب کنی.",
                    reply_markup=keyboard([
                        [InlineKeyboardButton(text="🔄 تلاش دوباره", callback_data=f"hd:all:{grade}")],
                        [InlineKeyboardButton(text="🎓 انتخاب پایه", callback_data="hd:home")]
                    ])
                )
            await c.message.answer(f"📚 همهٔ مطالب پایه {GRADE_WORDS[grade]}:", reply_markup=results_keyboard(c.message.chat.id))
        except Exception:
            log.exception("Hamyar all items failed")
            await c.message.answer("فهرست این پایه فعلاً در دسترس نیست.")

    @dp.callback_query(F.data.startswith("hd:kind:"))
    async def hd_kind(c: CallbackQuery):
        await c.answer("در حال مرتب‌سازی مطالب…")
        try:
            _, _, grade_s, kind = c.data.split(":", 3)
            grade = int(grade_s)
            items = await get_grade_items(grade)
            found = [x for x in items if classify(x["title"], kind, x.get("url", ""))]
            if kind in ("PDF", "ویدیو"):
                discovered = await collect_grade_resources(grade, kind)
                by_url = {x.get("url"): x for x in found}
                for resource in discovered:
                    by_url.setdefault(resource.get("url"), resource)
                found = list(by_url.values())
            set_visible(c.message.chat.id, found)
            if not found:
                return await c.message.answer(
                    f"در این پایه فعلاً مورد مستقیمی برای «{kind}» پیدا نشد. می‌توانی همهٔ مطالب پایه را ببینی یا پایه دیگری را انتخاب کنی.",
                    reply_markup=keyboard([
                        [InlineKeyboardButton(text="📚 همهٔ مطالب این پایه", callback_data=f"hd:all:{grade}")],
                        [InlineKeyboardButton(text="⬅️ بازگشت به دسته‌ها", callback_data=f"hd:grade:{grade}")],
                        [InlineKeyboardButton(text="🎓 انتخاب پایه", callback_data="hd:home")]
                    ])
                )
            await c.message.answer(
                f"📚 همیار درس — {kind}\n{len(found)} عنوان پیدا شد. یک مورد را انتخاب کن:",
                reply_markup=results_keyboard(c.message.chat.id)
            )
        except Exception:
            log.exception("Hamyar category failed")
            await c.message.answer("دسته‌بندی مطالب فعلاً در دسترس نیست.")

    @dp.callback_query(F.data == "hd:latest")
    async def hd_latest(c: CallbackQuery):
        await c.answer("در حال دریافت تازه‌ها…")
        try:
            parser = await fetch_page(HOME)
            items, seen = [], set()
            for x in parser.links:
                if x["url"].startswith(BASE + "/") and x["url"] not in seen and len(x["title"]) >= 8:
                    seen.add(x["url"])
                    items.append({"title": x["title"][:180], "url": x["url"], "grade": 0})
            set_visible(c.message.chat.id, items[:60])
            await c.message.answer("🆕 تازه‌های آموزشی:", reply_markup=results_keyboard(c.message.chat.id))
        except Exception:
            log.exception("Hamyar latest failed")
            await c.message.answer("تازه‌های آموزشی فعلاً دریافت نشد.")

    @dp.callback_query(F.data == "hd:search")
    async def hd_search(c: CallbackQuery):
        await c.answer()
        await c.message.answer(
            "🔎 برای جست‌وجو، عبارتت را همین‌جا بفرست؛ بهتر است پایه و نام درس را هم بنویسی.\n"
            "مثال: «پایه دهم فیزیک نمونه سوال»، «گام به گام ریاضی هشتم»، «جزوه شیمی دهم».\n"
            "برای جست‌وجوی گسترده‌تر، اول پایه را انتخاب کن تا نتایج دقیق‌تر شوند."
        )

    @dp.callback_query(F.data.startswith("hd:page:"))
    async def hd_page(c: CallbackQuery):
        await c.answer()
        page = max(0, int(c.data.rsplit(":", 1)[1]))
        await c.message.answer("📚 ادامهٔ فهرست:", reply_markup=results_keyboard(c.message.chat.id, page))

    @dp.callback_query(F.data.startswith("hd:item:"))
    async def hd_item(c: CallbackQuery):
        await c.answer("در حال دریافت خلاصه…")
        try:
            index = int(c.data.rsplit(":", 1)[1])
            items = get_visible(c.message.chat.id)
            if index < 0 or index >= len(items):
                return await c.message.answer("این فهرست قدیمی شده؛ دوباره بخش را باز کن.")
            item = items[index]
            direct_kind = resource_type(item["url"], item["title"])
            if direct_kind in ("pdf", "video"):
                return await send_resource(c, item["url"], item["title"], direct_kind)
            if direct_kind == "link":
                return await c.message.answer(
                    "🎬 آموزش ویدئویی در میزبان پخش قرار دارد.",
                    reply_markup=keyboard([[InlineKeyboardButton(text="▶️ پخش آموزش", url=item["url"])],
                                           [InlineKeyboardButton(text="⬅️ بازگشت به فهرست", callback_data="hd:page:0")]])
                )
            parser = await fetch_page(item["url"])
            excerpt = short_summary(parser)
            resources, seen = [], set()
            for link in parser.links:
                url = link.get("url", "")
                title = " ".join((link.get("title") or "").split()) or "فایل آموزشی"
                kind = resource_type(url, title)
                if kind and url not in seen and urlparse(url).scheme in ("http", "https"):
                    seen.add(url)
                    resources.append({"url": url, "title": title[:100], "kind": kind})
            CHAT_CACHE[f"_resources_{c.message.chat.id}_{index}"] = resources[:12]
            rows = []
            for ridx, resource in enumerate(resources[:8]):
                icon = "📥 PDF" if resource["kind"] == "pdf" else ("🎬 ویدئو" if resource["kind"] == "video" else "▶️ پخش")
                rows.append([InlineKeyboardButton(text=(icon + " | " + resource["title"])[:62], callback_data=f"hd:resource:{index}:{ridx}")])
            rows.extend([
                [InlineKeyboardButton(text="⬅️ بازگشت به فهرست", callback_data="hd:page:0")],
                [InlineKeyboardButton(text="🔎 جست‌وجوی دوباره", callback_data="hd:search")],
                [InlineKeyboardButton(text="🏠 منوی همیار درس", callback_data="hd:home")],
            ])
            detail_text = (
                f"📘 {item['title']}\n\n{excerpt}\n\n"
                + ("فایل‌ها و ویدئوهای عمومی پیدا شده‌اند؛ برای دریافت یا پخش، یکی را انتخاب کن."
                   if resources else "در این صفحه فایل مستقیم عمومی پیدا نشد. می‌توانی نتیجه‌های دیگر را ببینی.")
            )
            await c.message.answer(detail_text, reply_markup=keyboard(rows))
        except Exception:
            log.exception("Hamyar item fetch failed")
            await c.message.answer("این مطلب فعلاً دریافت نشد. کمی بعد دوباره تلاش کن.")


    @dp.callback_query(F.data.startswith("hd:resource:"))
    async def hd_resource(c: CallbackQuery):
        try:
            _, _, item_s, resource_s = c.data.split(":")
            item_index, resource_index = int(item_s), int(resource_s)
            resources = CHAT_CACHE.get(f"_resources_{c.message.chat.id}_{item_index}", [])
            if resource_index < 0 or resource_index >= len(resources):
                return await c.answer("فهرست فایل‌ها قدیمی شده؛ مطلب را دوباره باز کن.", show_alert=True)
            resource = resources[resource_index]
            if resource["kind"] in ("pdf", "video"):
                return await send_resource(c, resource["url"], resource["title"], resource["kind"])
            await c.answer()
            await c.message.answer(
                "🎬 این آموزش در یک پخش‌کنندهٔ خارجی قرار دارد.",
                reply_markup=keyboard([[InlineKeyboardButton(text="▶️ پخش آموزش", url=resource["url"])],
                                       [InlineKeyboardButton(text="⬅️ بازگشت", callback_data=f"hd:item:{item_index}")]])
            )
        except Exception:
            log.exception("Hamyar resource callback failed")
            await c.answer("دریافت فایل انجام نشد.", show_alert=True)

    @dp.message(F.text.regexp(r"(?i)(همیار درس|گام\s*به\s*گام|نمونه\s*سوال|نمونه\s*سؤال|جزوه|درسنامه|آزمون|امتحان|ویدیو|ویدئو|ریاضی|فیزیک|شیمی|زیست|فارسی|نگارش|عربی|انگلیسی|دینی|دین\s*و\s*زندگی|جغرافیا|تاریخ|جامعه\s*شناسی|منطق|اقتصاد|هندسه|آمادگی\s*دفاعی|پایه\s*(?:اول|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم|یازدهم|دوازدهم)|دهم|یازدهم|دوازدهم|نهم|هشتم|هفتم|ششم|پنجم|چهارم|سوم|دوم|اول)"))
    async def hd_text_search(m: Message):
        text = " ".join((m.text or "").replace("‌", " ").lower().split())
        try:
            grade = next((n for n, word in GRADE_WORDS.items() if f"پایه {word}" in text), None)
            if grade:
                items = await get_grade_items(grade)
            else:
                items = []
                for n in range(1, 13):
                    try:
                        items.extend(await get_grade_items(n))
                    except Exception:
                        continue
            terms = [x for x in re.findall(r"[\wآ-ی]+", text) if len(x) > 2 and x not in {"همیار", "درس", "پایه", "برای", "گام", "به", "سوال", "سؤال", "نمونه", "جواب"}]
            found = [x for x in items if all(term in x["title"].replace("‌", " ").lower() for term in terms[:4])] if terms else items
            if not found and terms:
                found = [x for x in items if any(term in x["title"].replace("‌", " ").lower() for term in terms[:4])]
            set_visible(m.chat.id, found[:80])
            if not found:
                return await m.answer("با این عبارت نتیجه‌ای پیدا نکردم. پایه و نام درس را کوتاه‌تر بنویس یا از منوی «همیار درس» پایه را انتخاب کن.")
            await m.answer(f"🔎 همیار درس | {len(found)} نتیجه", reply_markup=results_keyboard(m.chat.id))
        except Exception:
            log.exception("Hamyar text search failed")
            await m.answer("جست‌وجوی همیار درس فعلاً در دسترس نیست؛ کمی بعد دوباره امتحان کن.")
