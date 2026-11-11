# مهاجرت رایگان FXI Telegram Assistant به Cloudflare

## وضعیت فعلی

- مخزن مبنا: `sinfxi/bot_telegram`
- شاخه مبنا: `feature/telegram-delete-assistant`
- شاخه مهاجرت: `feature/cloudflare-free-webhook-migration`
- مسیر برنامه فعلی: `telegram-delete-assistant-pro/`
- دیتابیس Cloudflare موجود: `fxi_bot_prod` (شناسه در تنظیمات حساب Cloudflare؛ فعلاً ۰ جدول)
- Workerهای موجود `bot-telegram` و `sinajs` هستند و نباید بدون بررسی/اجازه جداگانه تغییر کنند.

## یافته‌های فنی

برنامه فعلی یک FastAPI + aiogram است و فقط یک endpoint ساده نیست:

- در `zeus_bot.py` راه‌اندازی `dp.start_polling(...)` داخل FastAPI lifespan انجام می‌شود.
- دو حلقه پس‌زمینه watchdog و inactivity reminder وجود دارد.
- لایه داده از `psycopg` و PostgreSQL استفاده می‌کند؛ از جمله JSONB، BIGSERIAL، ایندکس‌های PostgreSQL و queryهای مخصوص PostgreSQL.
- فایل محلی `/tmp/fxi_admin_data.json` به‌عنوان fallback وجود دارد و برای داده پایدار روی Worker مناسب نیست.
- پنل‌های مدیر و مالک گروه در `panel_auth.py` و `group_owner.py` به runtime فعلی، فایل‌های static و state مشترک وابسته‌اند.
- مسیرهای مدیریت گروه، آرشیو پیام‌ها، تاریخچه گفتگو، پرداخت/حمایت و تنظیمات باید حفظ شوند؛ حذف یا جایگزینی آن‌ها با یک پاسخگوی ساده قابل قبول نیست.

## معماری هدف با هزینه صفر

1. **Cloudflare Worker (TypeScript)** برای HTTP، webhook تلگرام، API پنل و اعتبارسنجی درخواست‌ها.
2. **Telegram webhook** به‌جای polling دائمی. تا زمانی که پردازش کامل updateها و تست‌ها آماده نشده، webhook ربات اصلی نباید تغییر کند.
3. **Cloudflare D1** با binding داخلی برای state، کاربران، گروه‌ها، پیام‌های آرشیوی، تاریخچه گفتگو، دعوت مدیران، پرداخت‌ها و deduplication شناسه update.
4. **Cloudflare Cron Triggers** برای کارهای زمان‌بندی‌شده‌ای که واقعاً دوره‌ای هستند؛ نه حلقه‌های بی‌نهایت در حافظه.
5. **Cloudflare Secrets** برای توکن تلگرام، کلید OpenRouter، secret وبهوک و کلیدهای نشست.
6. **GitHub Actions / Wrangler** برای استقرار از همین شاخه و بدون دست‌کاری Workerهای نامرتبط.

## مواردی که باید بازنویسی یا تطبیق داده شوند

- aiogram polling باید به ورودی webhook تبدیل شود. صرفاً قراردادن FastAPI روی ASGI این تغییر را انجام نمی‌دهد.
- تماس‌های Bot API باید با HTTP fetch و timeout/retry محدود انجام شوند؛ سازگاری aiogram/aiohttp در Python Workers باید جداگانه اثبات شود.
- psycopg و SQLهای PostgreSQL باید با D1 binding و SQL سازگار با SQLite جایگزین شوند.
- همه عملیات state باید async و مبتنی بر D1 باشند؛ فایل موقت محلی نباید منبع اصلی داده باشد.
- watchdog و inactivity reminder باید به triggerهای زمان‌بندی‌شده یا صف/کارهای کوتاه تبدیل شوند.
- پنل‌های موجود باید از نظر مسیر فایل‌ها، نشست‌ها، CSRF، CORS و ذخیره‌سازی در محیط Worker تطبیق داده و تست شوند.
- webhook باید با secret path/header و deduplication update_id محافظت شود.
- عملیات طولانی و ارسال گروهی باید به batchهای محدود و قابل تکرار تبدیل شوند تا سقف CPU و زمان اجرای رایگان رعایت شود.

## ترتیب اجرای امن

### مرحله ۱ — تثبیت و آزمون
- حفظ شاخه و سرویس فعلی برای rollback.
- استخراج فهرست routeها، handlerها، جدول‌ها و قابلیت‌های پنل.
- تست‌های قرارداد برای routeها و رفتار handlerهای مهم.

### مرحله ۲ — لایه داده D1
- ایجاد schema نسخه‌بندی‌شده.
- طراحی migration از PostgreSQL با export امن و تبدیل JSONB به JSON و انواع/ایندکس‌های SQLite.
- اعتبارسنجی شمارش رکوردها و نمونه‌خوانی؛ هیچ داده‌ای بدون backup و تطبیق حذف نشود.

### مرحله ۳ — webhook و پردازش update
- پیاده‌سازی احراز اصالت webhook و ثبت update_id به‌صورت idempotent.
- انتقال handlerها و سرویس‌های Telegram به fetch.
- تست پیام خصوصی، گروه، کانال، callback query، عکس/فایل و خطاهای Telegram API.

### مرحله ۴ — پنل و عملیات زمان‌بندی‌شده
- انتقال تمام endpointهای پنل و مجوزها.
- انتقال آرشیو، تاریخچه، مدیران، دعوت‌ها، پرداخت‌ها و تنظیمات.
- تبدیل کارهای پس‌زمینه به Cron/Queue و آزمون محدودیت‌ها.

### مرحله ۵ — انتشار کنترل‌شده
- استقرار روی Worker جدید با نام مستقل؛ نه `bot-telegram` و نه `sinajs`.
- تست /health، /ready، پنل، D1 و webhook آزمایشی.
- فقط پس از تست کامل، تنظیم webhook توکن اصلی و بررسی عملکرد واقعی.
- Render تا زمان تأیید نهایی به‌عنوان rollback باقی بماند؛ خاموش یا حذف نشود تا نسخه جدید پایدار باشد.

## شرط انتشار

هیچ نسخه‌ای به‌عنوان production اعلام نمی‌شود مگر اینکه:
- تمام قابلیت‌های موردنیاز در ماتریس تست پوشش داده شوند؛
- داده‌های PostgreSQL با backup و تطبیق منتقل شده باشند؛
- کلیدها فقط در Secrets باشند؛
- webhook اصلی بدون duplicate update کار کند؛
- پنل و کنترل دسترسی مالک/مدیر تأیید شوند؛
- مصرف در سقف رایگان Cloudflare بماند.

## محدودیت صادقانه

Cloudflare Workers یک process دائمی برای polling یا حلقه‌های پس‌زمینه فراهم نمی‌کند. Python Workers می‌تواند ASGI را میزبانی کند، اما این موضوع به‌تنهایی سازگاری aiogram، aiohttp، psycopg، فایل‌سیستم و taskهای دائمی برنامه فعلی را تضمین نمی‌کند. بنابراین این مهاجرت یک بازنویسی/تطبیق واقعی است، نه انتقال مستقیم کد.
