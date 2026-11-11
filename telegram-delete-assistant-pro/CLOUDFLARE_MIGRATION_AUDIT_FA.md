# ممیزی مهاجرت Cloudflare — شاخه telegram-delete-assistant

این سند بر اساس کد موجود در شاخه `feature/telegram-delete-assistant` تهیه شده است.
این مرحله فقط ممیزی است؛ هیچ سرویس تولیدی، webhook، توکن یا داده‌ای تغییر داده نشده است.

## مبنای بررسی

- شاخه: `feature/telegram-delete-assistant`
- commit بررسی‌شده: `baedb373ea9eaa9c7a67427cfd45a46e4e41b1b5`
- برنامه اصلی: `telegram-delete-assistant-pro/zeus_bot.py`
- نقطه ورود فعلی: `telegram-delete-assistant-pro/app.py`
- پنل مالک و مدیر: `panel_auth.py` و فایل‌های `static/admin.*`
- پنل مدیر گروه: `group_owner.py` و فایل‌های `static/group-owner.*`

## قابلیت‌هایی که باید حفظ شوند

### ربات و هوش مصنوعی
- فرمان‌های شروع، راهنما، انتخاب و وضعیت ارائه‌دهنده هوش مصنوعی
- اتصال هوش مصنوعی از طریق OpenRouter
- نگهداری تاریخچه مکالمه و پاک‌سازی تاریخچه
- مدیریت پرداخت/رسید و بررسی مالک
- پردازش پیام‌های متنی و صوتی و پاسخ‌های طولانی
- ثبت پیام‌های ربات و پیام‌های گروه/کانال

### مدیریت گروه و کانال
- تنظیمات جامعه، فعال/غیرفعال‌سازی هوش مصنوعی و قوانین
- بن، میوت، رفع میوت و سنجاق پیام
- پیش‌نویس کانال، گزارش کانال، پست‌های برتر و برنامه محتوا
- پیشنهاد موضوع، آمار و چالش‌های جامعه
- تشخیص خطاب به ربات و درخواست طبیعی
- مدیریت تغییرات پیام‌ها، واکنش‌ها و اعضا

### پنل مالک و مدیر
- ورود امن مالک و مدیر، نشست‌ها و محدودسازی تلاش ورود
- درخواست/دعوت مدیر، تأیید و رد درخواست، لغو دعوت و حذف مدیر
- مجوزهای تفکیک‌شده مدیران و کنترل سمت سرور
- وضعیت سرویس، کاربران، مسدودسازی، مکالمات، رویدادهای ممیزی
- تنظیم قابلیت‌ها، وضعیت ربات، پخش همگانی، prompt و پرداخت‌ها
- پشتیبان‌گیری پایگاه داده از مسیر مالک

### پنل مالک گروه
- درخواست کد و ورود مالک گروه
- نمای کلی، پیام‌ها و اعضا
- تغییر تنظیمات، ویرایش/حذف پیام‌های ربات
- مدیریت اعضا، خروج ربات از گروه و لینک افزودن
- ابزار مالک اصلی برای بازرسی و مدیریت پیام‌های گروه

## وابستگی‌های فعلی و موانع انتقال مستقیم

فایل `requirements.txt` شامل Aiogram 3، FastAPI، Uvicorn، aiohttp، psycopg، itsdangerous و python-dotenv است.

کد فعلی مستقیماً قابل اجرا در Cloudflare Workers نیست؛ موارد زیر باید به‌صورت واقعی بازطراحی شوند:

1. **Polling:** در lifespan، تابع `dp.start_polling` اجرا می‌شود. در Workers باید به webhook و پردازش updateهای ورودی تبدیل شود؛ اجرای polling هم‌زمان با webhook ممنوع است.
2. **چرخه عمر و taskها:** watchdog، یادآور عدم فعالیت و پاک‌سازی پیام موقت با `asyncio.create_task`/خواب‌های طولانی ساخته شده‌اند. این‌ها باید به Cron Trigger، Queue یا اجرای رویدادمحور منتقل شوند.
3. **پایگاه داده:** کد از PostgreSQL و psycopg استفاده می‌کند. مهاجرت به D1 نیازمند طراحی schema، تبدیل queryها، تراکنش‌ها، pagination، migration داده و تست سازگاری است؛ صرفاً تغییر نام `DATABASE_URL` کافی نیست.
4. **HTTP و Telegram Bot API:** استفاده از aiohttp و session پیش‌فرض Aiogram باید با transport سازگار با محیط Workers جایگزین و از نظر timeout، خطا، retry و محدودیت اندازه تست شود.
5. **فایل و پشتیبان:** خروجی پشتیبان مالک و ذخیره‌های محلی باید به ذخیره‌سازی پایدار Cloudflare (در صورت نیاز R2) منتقل شوند.
6. **پنل وب:** فایل‌های HTML/CSS/JS باید به‌عنوان static assets ارائه شوند و تمام APIهای مورد استفاده پنل، احراز هویت، کوکی‌ها، CSRF/CORS و مجوزها در runtime جدید آزموده شوند.
7. **محدودیت بسته‌ها:** سازگاری واقعی هر dependency با Python Workers باید در build آزمایش شود؛ پشتیبانی FastAPI به‌تنهایی به معنی سازگاری کل برنامه نیست.

## مسیر پیشنهادی پیاده‌سازی

1. ساخت ماتریس route/API و رفتارهای ربات از همین commit و تست‌های مرجع.
2. ایجاد runtime مستقل Cloudflare Python Worker بدون دست‌زدن به production.
3. تبدیل ورودی Telegram به webhook و تغذیه updateها به dispatcher.
4. ساخت لایه persistence برای D1 و migration idempotent داده‌های فعلی.
5. انتقال routeهای FastAPI و پنل‌ها به‌صورت مرحله‌ای، با حفظ قراردادهای API.
6. جایگزینی taskهای طولانی با scheduled/queue handlers و افزودن idempotency.
7. اجرای تست‌های واحد، امنیتی، قرارداد API، webhook، D1 و smoke test پنل.
8. مقایسه ماتریس قابلیت‌ها و فقط پس از قبولی تست‌ها، cutover کنترل‌شده روی Worker موجود.

## وضعیت این مرحله

- [x] شاخه و commit مبنا تأیید شد.
- [x] ساختار برنامه، فایل‌های پنل و تست امنیتی بررسی شد.
- [x] وابستگی‌ها و موانع اصلی انتقال مستقیم ثبت شد.
- [x] یک runtime مستقل Python Worker برای staging در مسیر `cloudflare-python/` اضافه شد؛ از import برنامه pollingمحور اصلی خودداری می‌کند.
- [x] یک D1 مستقل با نام `fxi-telegram-assistant-stage` در منطقه EU ساخته شد؛ دیتابیس production با نام `fxi_bot_prod` تغییر نکرد.
- [x] جدول‌های اولیهٔ staging شامل `fxi_py_updates`، `fxi_py_messages` و `fxi_py_channel_posts` ایجاد و با SQL واقعی بررسی شدند.
- [x] GitHub Actions برای نصب Workers SDK، compile، اعتبارسنجی migration و Deploy محیط staging آماده شد.
- [x] اجرای CI در commit `75f7efe81fc8819bc1544c455b469b6e7fc17529` مراحل نصب SDK، compile و اعتبارسنجی D1 را با موفقیت گذراند.
- [ ] Worker staging هنوز منتشر نشده است؛ مقدار `CLOUDFLARE_API_TOKEN` در GitHub Actions موجود نیست و مرحلهٔ Deploy به همین دلیل اجرا نشده است.
- [ ] Secretهای ربات در محیط staging تنظیم نشده‌اند؛ هیچ توکن یا کلیدی از Worker production خوانده یا کپی نشده است.
- [ ] تمام قابلیت‌های ربات/پنل به Cloudflare منتقل نشده‌اند.
- [ ] تست parity و cutover تولید انجام نشده است.

**هشدار:** Worker ساده‌شده یا پاسخ‌گوی mock جایگزین این برنامه نیست. تا زمان تکمیل و تست parity، نسخه عملیاتی فعلی باید دست‌نخورده بماند.


## گزارش اجرای staging در 2026-11-11

- مسیر کد جدید: `telegram-delete-assistant-pro/cloudflare-python/`
- Worker مقصد staging: `fxi-telegram-python-stage` (هنوز در حساب ساخته/منتشر نشده؛ بارگذاری مستقیم API به‌علت نبود SDK بسته‌بندی‌شده رد شد).
- D1 staging: `fxi-telegram-assistant-stage`
- D1 staging ID: `e702e0b0-3d89-4699-93e1-199b5c3c45be`
- شناسه دیتابیس production `fxi_bot_prod` و Worker عملیاتی فعلی دست‌نخورده ماندند.
- GitHub Actions run مربوط به commit `75f7efe81fc8819bc1544c455b469b6e7fc17529`: نصب وابستگی‌ها، compile و اعتبارسنجی SQL موفق؛ Deploy به‌علت خالی بودن secret لازم اجرا نشد.
- برای ادامه، یک GitHub Actions repository secret با نام `CLOUDFLARE_API_TOKEN` و مجوز Worker Scripts:Edit لازم است. پس از افزودن آن، push بعدی یا اجرای دستی workflow انتشار staging را انجام می‌دهد.

**وضعیت نهایی این مرحله: کد و دیتابیس آزمایشی آماده‌اند؛ Worker هنوز آنلاین نیست و webhook ربات اصلی تغییر نکرده است.**
