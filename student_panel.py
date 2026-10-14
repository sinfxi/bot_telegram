"""Student panel, card-transfer receipt workflow, and university guidance for the Telegram bot."""
import logging
import os
import re
import sqlite3
import time
from datetime import datetime

from aiogram import F
from aiogram.types import (
    CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    Message, BufferedInputFile
)

log = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "bot.db")
CARD_NUMBER = "5859831211613988"
CARD_HOLDER = "سینا نوبخت"
PANEL_PRICE = 30000
CONSULT_PRICE = 20000

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("PRAGMA journal_mode=WAL")
db.executescript("""
CREATE TABLE IF NOT EXISTS student_access(
  user_id INTEGER PRIMARY KEY,
  panel_active INTEGER NOT NULL DEFAULT 0,
  consult_active INTEGER NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS student_payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  product TEXT NOT NULL,
  amount INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'awaiting_receipt',
  receipt_file_id TEXT,
  receipt_kind TEXT,
  created_at REAL NOT NULL,
  reviewed_by INTEGER,
  reviewed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_student_payments_user_status
ON student_payments(user_id,status);
""")
db.commit()

GRADE_NAMES = ["اول", "دوم", "سوم", "چهارم", "پنجم", "ششم", "هفتم", "هشتم", "نهم", "دهم", "یازدهم", "دوازدهم"]
FLASHCARDS = [
    ("یکای نیرو در SI چیست؟", "نیوتن (N)."),
    ("شتاب متوسط چگونه محاسبه می‌شود؟", "تغییر سرعت تقسیم بر بازهٔ زمانی: a = Δv / Δt."),
    ("یکای انرژی چیست؟", "ژول (J)."),
    ("سرعت متوسط چیست؟", "مسافت طی‌شده تقسیم بر زمان کل."),
    ("قانون دوم نیوتن چیست؟", "برآیند نیروها برابر جرم ضرب‌در شتاب است: F = ma."),
    ("مساحت مثلث چگونه محاسبه می‌شود؟", "قاعده × ارتفاع ÷ ۲."),
    ("شیب خط در نمودار چیست؟", "تغییرات y تقسیم بر تغییرات x."),
    ("عدد اتمی چه چیزی را نشان می‌دهد؟", "تعداد پروتون‌های هسته."),
]


def _keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _access(user_id):
    row = db.execute(
        "SELECT panel_active, consult_active FROM student_access WHERE user_id=?",
        (user_id,)
    ).fetchone()
    return (bool(row[0]), bool(row[1])) if row else (False, False)


def _panel_keyboard(user_id):
    panel, consult = _access(user_id)
    return _keyboard([
        [InlineKeyboardButton(
            text=("🟢 پنل دانش‌آموزی و دانشجویی | فعال" if panel else "🔴 🔒 پنل دانش‌آموزی و دانشجویی | ۳۰٬۰۰۰ تومان"),
            callback_data="sp:enter"
        )],
        [InlineKeyboardButton(
            text=("🟢 مشاوره انتخاب دانشگاه | فعال" if consult else "🔴 🔒 مشاوره انتخاب دانشگاه | ۲۰٬۰۰۰ تومان"),
            callback_data="sp:consult"
        )],
        [InlineKeyboardButton(text="📊 رتبه و تراز کنکور | رایگان", callback_data="sp:rank")],
        [InlineKeyboardButton(text="🧾 وضعیت خرید و اشتراک", callback_data="sp:status")],
        [InlineKeyboardButton(text="📚 همیار درس و گام‌به‌گام", callback_data="hd:home")],
        [InlineKeyboardButton(text="📄 راهنمای فایل‌ها و PDF", callback_data="sp:pdfhelp"),
         InlineKeyboardButton(text="🎬 آموزش ویدئویی", callback_data="sp:videohelp")],
        [InlineKeyboardButton(text="ℹ️ درباره ما", callback_data="sp:about")],
    ])


def _premium_keyboard():
    return _keyboard([
        [InlineKeyboardButton(text="📚 گام‌به‌گام و پاسخ تمرین‌ها", callback_data="hd:home")],
        [InlineKeyboardButton(text="📄 فایل‌ها و جزوه‌ها", callback_data="sp:pdfhelp"),
         InlineKeyboardButton(text="🎬 ویدئوها", callback_data="sp:videohelp")],
        [InlineKeyboardButton(text="🧠 فلش‌کارت و مرور", callback_data="sp:flashcards"),
         InlineKeyboardButton(text="📐 فرمول‌های درسی", callback_data="sp:formulas")],
        [InlineKeyboardButton(text="📝 نمونه‌سؤال و آزمون", callback_data="sp:examhelp")],
        [InlineKeyboardButton(text="🗓 برنامه‌ریزی درسی", callback_data="sp:planner")],
        [InlineKeyboardButton(text="🎓 مشاوره انتخاب دانشگاه", callback_data="sp:consult")],
        [InlineKeyboardButton(text="⬅️ منوی پنل", callback_data="sp:menu")],
    ])


def _request_payment(user_id, product):
    amount = PANEL_PRICE if product == "panel" else CONSULT_PRICE
    cur = db.execute(
        "INSERT INTO student_payments(user_id,product,amount,status,created_at) VALUES(?,?,?,?,?)",
        (user_id, product, amount, "awaiting_receipt", time.time())
    )
    db.commit()
    return cur.lastrowid, amount


def register_student_handlers(dp, bot, admin_ids):
    admins = set(admin_ids or [])
    try:
        configured_admin = int(os.getenv("ADMIN_ID", "0"))
        if configured_admin:
            admins.add(configured_admin)
    except ValueError:
        pass

    async def send_payment_instructions(message, product):
        payment_id, amount = _request_payment(message.from_user.id, product)
        title = "پنل دانش‌آموزی و دانشجویی" if product == "panel" else "مشاوره انتخاب دانشگاه"
        await message.answer(
            f"🧾 درخواست خرید ثبت شد | شماره پیگیری: {payment_id}\n\n"
            f"بخش انتخابی: {title}\nمبلغ: {amount:,} تومان\n\n"
            f"💳 شماره کارت: <code>{CARD_NUMBER}</code>\n"
            f"👤 به نام: {CARD_HOLDER}\n\n"
            "پس از کارت‌به‌کارت، تصویر رسید یا فایل رسید را همین‌جا ارسال کن. "
            "قابلیت فقط بعد از بررسی و تأیید مدیر فعال می‌شود.\n"
            "برای امنیت، رمز پویا، CVV2 یا اطلاعات کامل کارتت را ارسال نکن.",
            parse_mode="HTML",
            reply_markup=_keyboard([[InlineKeyboardButton(text="⬅️ بازگشت", callback_data="sp:menu")]])
        )

    @dp.callback_query(F.data == "sp:menu")
    async def student_menu(c: CallbackQuery):
        await c.answer()
        await c.message.answer(
            "🎓 مرکز دانش‌آموزی و دانشجویی\n\n"
            "از اینجا می‌توانی ابزارهای رایگان را ببینی، اشتراک بخری یا وضعیت دسترسی‌ها را بررسی کنی.\n"
            "🔴 قفل = اشتراک فعال نیست | 🟢 سبز = دسترسی تأیید شده",
            reply_markup=_panel_keyboard(c.from_user.id)
        )

    @dp.callback_query(F.data == "sp:about")
    async def about(c: CallbackQuery):
        await c.answer()
        await c.message.answer(
            "ℹ️ درباره ما\n\n"
            "همیار درس برای ساده‌تر کردن یادگیری ساخته شده است: دسترسی دسته‌بندی‌شده به مطالب درسی، "
            "گام‌به‌گام، فایل‌های آموزشی، تمرین و ابزارهای برنامه‌ریزی.\n\n"
            "پیشنهادها و گزارش خطاها را می‌توانی برای مدیر ربات بفرستی. "
            "نتیجه‌های رتبه و انتخاب دانشگاه تخمینی‌اند و جایگزین داده رسمی سازمان سنجش یا مشاور متخصص نیستند.",
            reply_markup=_keyboard([[InlineKeyboardButton(text="⬅️ برگشت", callback_data="sp:menu")]])
        )

    @dp.callback_query(F.data == "sp:enter")
    async def enter_panel(c: CallbackQuery):
        panel, _ = _access(c.from_user.id)
        await c.answer()
        if not panel:
            return await c.message.answer(
                "🔒 لطفاً اشتراک VIP پنل دانش‌آموزی و دانشجویی را بخرید تا این بخش باز شود.",
                reply_markup=_keyboard([
                    [InlineKeyboardButton(text="💳 خرید اشتراک | ۳۰٬۰۰۰ تومان", callback_data="sp:buy:panel")],
                    [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="sp:menu")],
                ])
            )
        await c.message.answer("🟢 پنل دانش‌آموزی و دانشجویی فعال است. یکی از بخش‌ها را انتخاب کن:", reply_markup=_premium_keyboard())

    @dp.callback_query(F.data == "sp:consult")
    async def consult_entry(c: CallbackQuery):
        _, consult = _access(c.from_user.id)
        await c.answer()
        if not consult:
            return await c.message.answer(
                "🔒 برای باز شدن مشاوره انتخاب دانشگاه، اشتراک ۲۰٬۰۰۰ تومانی این بخش را تهیه کن.",
                reply_markup=_keyboard([
                    [InlineKeyboardButton(text="💳 خرید مشاوره | ۲۰٬۰۰۰ تومان", callback_data="sp:buy:consult")],
                    [InlineKeyboardButton(text="📊 رتبه و تراز رایگان", callback_data="sp:rank")],
                    [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="sp:menu")],
                ])
            )
        await c.message.answer(
            "🎓 برای دریافت راهنمایی اولیه، اطلاعاتت را در یک پیام بفرست:\n"
            "رشته، رتبه، سهمیه/منطقه، تراز (اگر داری)، معدل و شهرهای موردنظرت.\n\n"
            "نمونه: تجربی | رتبه ۵۲۰۰ | منطقه ۲ | تراز ۸۷۰۰ | معدل ۱۸٫۵ | تهران و کرج\n"
            "پاسخ یک برآورد راهنماست؛ قبولی به ظرفیت و داده‌های همان سال بستگی دارد."
        )

    @dp.callback_query(F.data == "sp:buy:panel")
    async def buy_panel(c: CallbackQuery):
        await c.answer()
        await send_payment_instructions(c.message, "panel")

    @dp.callback_query(F.data == "sp:buy:consult")
    async def buy_consult(c: CallbackQuery):
        await c.answer()
        await send_payment_instructions(c.message, "consult")

    @dp.callback_query(F.data == "sp:rank")
    async def free_rank(c: CallbackQuery):
        await c.answer()
        await c.message.answer(
            "📊 رتبه و تراز کنکور | رایگان\n\n"
            "گروه آزمایشی را انتخاب کن، سپس رتبه/تراز، منطقه یا سهمیه و سال کنکور را وارد کن. "
            "اگر هنوز کارنامه نداری، راهنمای بدون کارنامه را انتخاب کن.\n\n"
            "⚠️ ربات به سامانهٔ رسمی سنجش وصل نیست و رتبه یا تراز رسمی را حدس نمی‌زند.",
            reply_markup=_keyboard([
                [InlineKeyboardButton(text="🧬 تجربی", callback_data="sp:rank:group:تجربی"),
                 InlineKeyboardButton(text="📐 ریاضی", callback_data="sp:rank:group:ریاضی")],
                [InlineKeyboardButton(text="📚 انسانی", callback_data="sp:rank:group:انسانی"),
                 InlineKeyboardButton(text="🎨 هنر", callback_data="sp:rank:group:هنر"),
                 InlineKeyboardButton(text="🌐 زبان", callback_data="sp:rank:group:زبان")],
                [InlineKeyboardButton(text="📝 راهنمای بدون کارنامه", callback_data="sp:rank:manual")],
                [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="sp:menu")]
            ])
        )

    @dp.callback_query(F.data.startswith("sp:rank:group:"))
    async def rank_group(c: CallbackQuery):
        group = c.data.rsplit(":", 1)[1]
        await c.answer()
        await c.message.answer(
            f"📊 راهنمای رتبه و تراز | گروه {group}\n\n"
            "اطلاعاتت را در یک پیام بفرست:\n"
            f"گروه: {group} | رتبه: ... | تراز: ... | منطقه/سهمیه: ... | سال کنکور: ...\n\n"
            "اگر رتبه یا تراز نداری، بنویس «تخمین ندارم». نتیجه‌ها رسمی نیستند و قبولی قطعی را تضمین نمی‌کنند.",
            reply_markup=_keyboard([
                [InlineKeyboardButton(text="📝 راهنمای بدون کارنامه", callback_data="sp:rank:manual")],
                [InlineKeyboardButton(text="⬅️ بازگشت به رتبه و تراز", callback_data="sp:rank")]
            ])
        )

    @dp.callback_query(F.data == "sp:rank:manual")
    async def rank_manual(c: CallbackQuery):
        await c.answer()
        await c.message.answer(
            "📝 اگر هنوز کارنامه نداری، گروه آزمایشی، پایه/سال تحصیل، درس‌های قوی و ضعیف و میانگین ساعت مطالعه را بنویس.\n\n"
            "در کارنامه، رتبه در سهمیه، رتبه کشوری، تراز، سهمیه و سال آزمون را از هم جدا کن. "
            "اطلاعات حساس مثل کد ملی، رمز یا تصویر کامل کارنامه را نفرست.",
            reply_markup=_keyboard([[InlineKeyboardButton(text="⬅️ بازگشت", callback_data="sp:rank")]])
        )

    @dp.callback_query(F.data == "sp:status")
    async def payment_status(c: CallbackQuery):
        await c.answer()
        panel, consult = _access(c.from_user.id)
        rows = db.execute(
            "SELECT id,product,amount,status,created_at FROM student_payments WHERE user_id=? ORDER BY id DESC LIMIT 5",
            (c.from_user.id,)
        ).fetchall()
        labels = {
            "awaiting_receipt": "منتظر ارسال رسید",
            "pending_review": "در انتظار بررسی مدیر",
            "approved": "تأیید شده",
            "rejected": "رسید رد شده",
        }
        lines = [
            "🧾 وضعیت دسترسی‌ها",
            f"پنل دانش‌آموزی/دانشجویی: {'🟢 فعال' if panel else '🔴 قفل'}",
            f"مشاوره انتخاب دانشگاه: {'🟢 فعال' if consult else '🔴 قفل'}",
            "",
            "آخرین درخواست‌ها:"
        ]
        for payment_id, product, amount, status, created_at in rows:
            name = "پنل VIP" if product == "panel" else "مشاوره دانشگاه"
            date = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M")
            lines.append(f"• #{payment_id} | {name} | {amount:,} تومان | {labels.get(status, status)} | {date}")
        if not rows:
            lines.append("هنوز درخواست خریدی ثبت نکرده‌ای.")
        await c.message.answer(
            "\n".join(lines),
            reply_markup=_keyboard([
                [InlineKeyboardButton(text="💳 خرید پنل | ۳۰٬۰۰۰ تومان", callback_data="sp:buy:panel")],
                [InlineKeyboardButton(text="🎓 خرید مشاوره | ۲۰٬۰۰۰ تومان", callback_data="sp:buy:consult")],
                [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="sp:menu")]
            ])
        )

    @dp.callback_query(F.data == "sp:flashcards")
    async def flashcards(c: CallbackQuery):
        await c.answer()
        panel, _ = _access(c.from_user.id)
        if not panel:
            return await c.message.answer("این بخش با اشتراک پنل VIP فعال می‌شود.", reply_markup=_keyboard([[InlineKeyboardButton(text="💳 خرید پنل | ۳۰٬۰۰۰ تومان", callback_data="sp:buy:panel")]]))
        index = 0
        question, _answer = FLASHCARDS[index]
        await c.message.answer(
            f"🧠 فلش‌کارت {index + 1} از {len(FLASHCARDS)}\n\n❓ {question}",
            reply_markup=_keyboard([[
                InlineKeyboardButton(text="👁 دیدن پاسخ", callback_data=f"sp:card:show:{index}"),
                InlineKeyboardButton(text="➡️ کارت بعد", callback_data=f"sp:card:next:{index}")
            ], [InlineKeyboardButton(text="⬅️ بازگشت به پنل", callback_data="sp:enter")]])
        )

    @dp.callback_query(F.data.startswith("sp:card:"))
    async def flashcard_action(c: CallbackQuery):
        panel, _ = _access(c.from_user.id)
        if not panel:
            return await c.answer("ابتدا اشتراک پنل را فعال کن.", show_alert=True)
        try:
            _, _, action, raw_index = c.data.split(":")
            index = int(raw_index)
            if action == "show":
                await c.answer()
                await c.message.answer(f"✅ پاسخ کارت {index + 1}:\n{FLASHCARDS[index][1]}",
                    reply_markup=_keyboard([[InlineKeyboardButton(text="➡️ کارت بعد", callback_data=f"sp:card:next:{index}")]]))
            else:
                index = (index + 1) % len(FLASHCARDS)
                await c.answer()
                await c.message.answer(f"🧠 فلش‌کارت {index + 1} از {len(FLASHCARDS)}\n\n❓ {FLASHCARDS[index][0]}",
                    reply_markup=_keyboard([[
                        InlineKeyboardButton(text="👁 دیدن پاسخ", callback_data=f"sp:card:show:{index}"),
                        InlineKeyboardButton(text="➡️ کارت بعد", callback_data=f"sp:card:next:{index}")
                    ]]))
        except Exception:
            await c.answer("این کارت در دسترس نیست.", show_alert=True)

    @dp.callback_query(F.data == "sp:formulas")
    async def formula_menu(c: CallbackQuery):
        await c.answer()
        panel, _ = _access(c.from_user.id)
        if not panel:
            return await c.message.answer("این بخش با اشتراک پنل VIP فعال می‌شود.", reply_markup=_keyboard([[InlineKeyboardButton(text="💳 خرید پنل | ۳۰٬۰۰۰ تومان", callback_data="sp:buy:panel")]]))
        await c.message.answer("📐 فرمول‌های درسی — موضوع را انتخاب کن:", reply_markup=_keyboard([
            [InlineKeyboardButton(text="⚙️ فیزیک", callback_data="sp:formula:physics"),
             InlineKeyboardButton(text="📏 ریاضی", callback_data="sp:formula:math")],
            [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="sp:enter")]
        ]))

    @dp.callback_query(F.data.startswith("sp:formula:"))
    async def formula_topic(c: CallbackQuery):
        panel, _ = _access(c.from_user.id)
        if not panel:
            return await c.answer("ابتدا اشتراک پنل را فعال کن.", show_alert=True)
        topic = c.data.rsplit(":", 1)[1]
        formulas = {
            "physics": "⚙️ فرمول‌های پایه فیزیک\n• سرعت متوسط: v = Δx / Δt\n• شتاب متوسط: a = Δv / Δt\n• قانون دوم نیوتن: F = ma\n• وزن: W = mg\n• کار نیروی ثابت: W = Fd cosθ\n• انرژی جنبشی: K = ½mv²\n• چگالی: ρ = m / V",
            "math": "📏 فرمول‌های پایه ریاضی\n• مساحت مستطیل: A = طول × عرض\n• مساحت مثلث: A = ½ × قاعده × ارتفاع\n• شیب خط: m = (y₂ − y₁) / (x₂ − x₁)\n• فیثاغورس: a² + b² = c²\n• میانگین حسابی: مجموع داده‌ها ÷ تعداد داده‌ها"
        }
        await c.answer()
        await c.message.answer(formulas.get(topic, "موضوع پیدا نشد."), reply_markup=_keyboard([[InlineKeyboardButton(text="⬅️ برگشت به فرمول‌ها", callback_data="sp:formulas")]]))

    @dp.callback_query(F.data.in_({"sp:pdfhelp", "sp:videohelp", "sp:examhelp", "sp:planner"}))
    async def study_shortcuts(c: CallbackQuery):
        await c.answer()
        action = c.data.split(":")[1]
        if action in ("pdfhelp", "videohelp", "examhelp", "planner"):
            panel, _ = _access(c.from_user.id)
            if not panel:
                return await c.message.answer(
                    "این ابزار در پنل VIP قرار دارد. ابتدا اشتراک پنل را فعال کن.",
                    reply_markup=_keyboard([[InlineKeyboardButton(text="💳 خرید پنل | ۳۰٬۰۰۰ تومان", callback_data="sp:buy:panel")]])
                )
        messages = {
            "pdfhelp": "📄 برای دریافت فایل، پایه را در «همیار درس» انتخاب کن و موردی را باز کن؛ اگر PDF عمومی در صفحه موجود باشد، دکمهٔ دریافت فایل نمایش داده می‌شود.",
            "videohelp": "🎬 فهرست آموزش ویدئویی از بخش همیار درس و دستهٔ ویدئوها قابل دسترسی است. ویدئوهایی که فایل مستقیم عمومی دارند داخل تلگرام ارسال می‌شوند؛ پخش‌کننده‌های خارجی ممکن است دکمهٔ پخش داشته باشند.",
            "examhelp": "📝 برای یافتن نمونه‌سؤال، پایه و نام درس را در همیار درس جست‌وجو کن؛ از عبارت‌هایی مثل «پایه دهم فیزیک نمونه سوال» استفاده کن.",
            "planner": "🗓 برنامه‌ریزی درسی: در یک پیام پایه، درس‌ها، زمان آزاد روزانه و تاریخ آزمونت را بفرست تا یک برنامه پیشنهادی قابل ویرایش بسازیم."
        }
        await c.message.answer(messages[action], reply_markup=_keyboard([[InlineKeyboardButton(text="📚 رفتن به همیار درس", callback_data="hd:home")], [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="sp:menu")]]))

    @dp.message(F.photo | F.document)
    async def receipt_upload(message: Message):
        if not message.from_user:
            return
        row = db.execute(
            "SELECT id,product,amount FROM student_payments WHERE user_id=? AND status='awaiting_receipt' ORDER BY id DESC LIMIT 1",
            (message.from_user.id,)
        ).fetchone()
        if not row:
            return
        payment_id, product, amount = row
        if message.photo:
            file_id, kind = message.photo[-1].file_id, "photo"
        else:
            document = message.document
            if not document or (document.mime_type and not (document.mime_type.startswith("image/") or document.mime_type == "application/pdf")):
                return await message.answer("رسید را به شکل عکس یا PDF ارسال کن.")
            file_id, kind = document.file_id, "document"
        db.execute(
            "UPDATE student_payments SET status='pending_review',receipt_file_id=?,receipt_kind=? WHERE id=?",
            (file_id, kind, payment_id)
        )
        db.commit()
        product_name = "پنل دانش‌آموزی/دانشجویی" if product == "panel" else "مشاوره انتخاب دانشگاه"
        for admin_id in admins:
            try:
                keyboard = _keyboard([[
                    InlineKeyboardButton(text="✅ تأیید و فعال‌سازی", callback_data=f"sp:approve:{payment_id}"),
                    InlineKeyboardButton(text="❌ رد رسید", callback_data=f"sp:reject:{payment_id}")
                ]])
                await bot.send_message(
                    admin_id,
                    f"🧾 رسید پرداخت جدید\nپیگیری: {payment_id}\nکاربر: {message.from_user.full_name} "
                    f"(ID: {message.from_user.id})\nبخش: {product_name}\nمبلغ: {amount:,} تومان",
                    reply_markup=keyboard
                )
                if kind == "photo":
                    await bot.send_photo(admin_id, file_id, caption=f"رسید درخواست #{payment_id}")
                else:
                    await bot.send_document(admin_id, file_id, caption=f"رسید درخواست #{payment_id}")
            except Exception:
                log.exception("Could not forward student payment receipt to admin %s", admin_id)
        await message.answer(
            f"رسید درخواست شماره {payment_id} ثبت شد. ⏳\n"
            "پس از بررسی مدیر، نتیجه از طریق همین ربات به تو اعلام می‌شود. تا آن زمان دسترسی هنوز قفل است.",
            reply_markup=_keyboard([[InlineKeyboardButton(text="📋 وضعیت پنل", callback_data="sp:menu")]])
        )

    @dp.callback_query(F.data.startswith("sp:approve:"))
    async def approve_payment(c: CallbackQuery):
        if c.from_user.id not in admins:
            return await c.answer("فقط مدیر مجاز است.", show_alert=True)
        try:
            payment_id = int(c.data.rsplit(":", 1)[1])
        except ValueError:
            return await c.answer("شماره پیگیری نامعتبر است.", show_alert=True)
        row = db.execute(
            "SELECT user_id,product,amount,status FROM student_payments WHERE id=?",
            (payment_id,)
        ).fetchone()
        if not row or row[3] != "pending_review":
            return await c.answer("این درخواست قبلاً بررسی شده یا وجود ندارد.", show_alert=True)
        user_id, product, amount, _ = row
        db.execute(
            "INSERT INTO student_access(user_id,panel_active,consult_active,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "panel_active=MAX(student_access.panel_active,excluded.panel_active), "
            "consult_active=MAX(student_access.consult_active,excluded.consult_active), updated_at=excluded.updated_at",
            (user_id, int(product == "panel"), int(product == "consult"), time.time())
        )
        db.execute("UPDATE student_payments SET status='approved',reviewed_by=?,reviewed_at=? WHERE id=?", (c.from_user.id, time.time(), payment_id))
        db.commit()
        try:
            await bot.send_message(
                user_id,
                ("✅ پرداخت تأیید شد؛ پنل دانش‌آموزی و دانشجویی برایت فعال شد." if product == "panel"
                 else "✅ پرداخت تأیید شد؛ مشاوره انتخاب دانشگاه برایت فعال شد."),
                reply_markup=_panel_keyboard(user_id)
            )
        except Exception:
            log.exception("Could not notify user about approved payment")
        await c.answer("پرداخت تأیید و دسترسی فعال شد.")
        if c.message:
            await c.message.edit_reply_markup(reply_markup=None)
            await c.message.answer(f"تأیید شد: درخواست #{payment_id}، کاربر {user_id}، مبلغ {amount:,} تومان")

    @dp.callback_query(F.data.startswith("sp:reject:"))
    async def reject_payment(c: CallbackQuery):
        if c.from_user.id not in admins:
            return await c.answer("فقط مدیر مجاز است.", show_alert=True)
        try:
            payment_id = int(c.data.rsplit(":", 1)[1])
        except ValueError:
            return await c.answer("شماره پیگیری نامعتبر است.", show_alert=True)
        row = db.execute("SELECT user_id,status FROM student_payments WHERE id=?", (payment_id,)).fetchone()
        if not row or row[1] != "pending_review":
            return await c.answer("این درخواست قبلاً بررسی شده یا وجود ندارد.", show_alert=True)
        db.execute("UPDATE student_payments SET status='rejected',reviewed_by=?,reviewed_at=? WHERE id=?", (c.from_user.id, time.time(), payment_id))
        db.commit()
        try:
            await bot.send_message(row[0], f"رسید درخواست #{payment_id} تأیید نشد. اگر پرداخت انجام شده، رسید واضح‌تر را با درخواست خرید جدید ارسال کن.")
        except Exception:
            log.exception("Could not notify user about rejected payment")
        await c.answer("رسید رد شد.")
        if c.message:
            await c.message.edit_reply_markup(reply_markup=None)
            await c.message.answer(f"رسید درخواست #{payment_id} رد شد.")

    @dp.message(F.text.regexp(r"(?i)(رتبه|تراز|انتخاب دانشگاه|دانشگاه کجا|رتبه ندارم|تخمین ندارم|کارنامه ندارم|برنامه.?ریزی|برنامه درسی|زمان آزاد)"))
    async def student_text_features(message: Message):
        if not message.from_user or not message.text:
            return
        text = message.text.strip()
        normalized = text.lower().replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
        if any(word in normalized for word in ("برنامه ریزی", "برنامه‌ریزی", "برنامه درسی", "زمان آزاد")):
            panel, _ = _access(message.from_user.id)
            if not panel:
                return await message.answer("برای برنامه‌ریزی درسی، اشتراک پنل ۳۰٬۰۰۰ تومانی لازم است.", reply_markup=_keyboard([[InlineKeyboardButton(text="💳 خرید پنل", callback_data="sp:buy:panel")]]))
            hours_match = re.search(r"(\d+)\s*ساعت", normalized)
            hours = max(1, min(8, int(hours_match.group(1)))) if hours_match else 3
            subjects = [x.strip(" .،؛") for x in re.split(r"[,،؛|]", text) if len(x.strip()) >= 2]
            subjects = [x for x in subjects if not any(k in x for k in ("برنامه", "ساعت", "زمان آزاد", "آزمون", "روزانه"))]
            if not subjects:
                return await message.answer("اسم درس‌ها و زمان روزانه را بفرست؛ نمونه: «برنامه‌ریزی، روزی ۳ ساعت، ریاضی، فیزیک، شیمی، فارسی»")
            slots = []
            for i in range(hours):
                subject = subjects[i % len(subjects)]
                slots.append(f"{i + 1}. {subject} — ۴۰ دقیقه مطالعه + ۱۰ دقیقه استراحت")
            return await message.answer("🗓 برنامهٔ پیشنهادی روزانه\n\n" + "\n".join(slots) + "\n\nاین برنامه را با تاریخ آزمون، سختی درس‌ها و زمان واقعی خودت تنظیم کن؛ اگر پایه و تاریخ امتحان را بفرستی، دقیق‌ترش می‌کنم.")
        if normalized in {"رتبه ندارم", "تخمین ندارم", "کارنامه ندارم"}:
            return await message.answer(
                "برای بررسی کارنامه، این موارد مهم‌اند: رتبه در سهمیه، رتبه کشوری، تراز، گروه آزمایشی، سهمیه و سال آزمون. "
                "وقتی کارنامه‌ات را داشتی، اطلاعات غیرحساس را تایپ کن؛ عکس کارنامه شامل کد ملی یا اطلاعات شخصی را نفرست."
            )
        if any(word in normalized for word in ("رتبه", "تراز", "انتخاب دانشگاه", "دانشگاه کجا")):
            panel, consult = _access(message.from_user.id)
            rank_match = re.search(r"رتبه\s*[:：]?\s*([\d٬,]+)", normalized)
            score_match = re.search(r"تراز\s*[:：]?\s*([\d٬,]+)", normalized)
            rank = int(re.sub(r"[,٬]", "", rank_match.group(1))) if rank_match else None
            score = int(re.sub(r"[,٬]", "", score_match.group(1))) if score_match else None
            if "انتخاب دانشگاه" in normalized or "دانشگاه کجا" in normalized:
                if not consult:
                    return await message.answer("برای مشاوره انتخاب دانشگاه، اشتراک ۲۰٬۰۰۰ تومانی لازم است.", reply_markup=_keyboard([[InlineKeyboardButton(text="💳 خرید مشاوره", callback_data="sp:buy:consult")]]))
                return await message.answer(
                    "برای اینکه برآورد گمراه‌کننده ندهم، لطفاً یک پیام با این قالب کامل بفرست:\n"
                    "رشته | رتبه در سهمیه | منطقه/سهمیه | تراز | معدل | سال کنکور | شهرهای ترجیحی\n"
                    "مثال: تجربی | رتبه ۵۲۰۰ | منطقه ۲ | تراز ۸۷۰۰ | معدل ۱۸٫۵ | ۱۴۰۵ | تهران"
                )
            details = []
            if rank is not None:
                details.append(f"رتبه‌ای که وارد کردی: {rank:,}")
            if score is not None:
                details.append(f"ترازی که وارد کردی: {score:,}")
            if not details:
                return await message.answer(
                    "برای ثبت اطلاعات، بنویس: «رشته تجربی، رتبه ۵۲۰۰، تراز ۸۷۰۰، منطقه ۲، سال ۱۴۰۵». "
                    "اگر رتبه یا تراز رسمی نداری، بنویس «تخمین ندارم»."
                )
            return await message.answer(
                "📊 خلاصه اطلاعات واردشده\n" + "\n".join(details) +
                "\n\nاین ربات رتبه/تراز رسمی را از سنجش واکشی نمی‌کند و از این اعداد به‌تنهایی قبولی قطعی قابل محاسبه نیست. "
                "برای تحلیل معتبر، رشته، سهمیه، سال آزمون و داده‌های رسمی همان سال هم لازم است."
            )
