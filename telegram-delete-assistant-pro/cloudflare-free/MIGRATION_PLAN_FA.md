# مهاجرت رایگان FXI Telegram Assistant به Cloudflare

## وضعیت فعلی

- مخزن مبنا: `sinfxi/bot_telegram`
- شاخه مبنا: `feature/telegram-delete-assistant`
- شاخه مهاجرت: `feature/cloudflare-free-webhook-migration`
- مسیر برنامه فعلی: `telegram-delete-assistant-pro/`
- دیتابیس Cloudflare موجود: `fxi_bot_prod` (`c31fe782-6cc2-41ff-a9a0-3e7504d3f319`، منطقه قضایی `eu`). مهاجرت `0001` اجرا شده و ساختار D1 شامل `fxi_bot_state`، `fxi_chat_messages`، `fxi_community_messages`، `telegram_updates` و `schema_migrations` به‌همراه ایندکس‌هاست. پیش از تغییر، bookmark بازیابی ثبت شد. دیتابیس قبل از ایجاد schema هیچ جدول کاربردی یا داده ربات نداشت.
- Workerهای موجود `bot-telegram` و `sinajs` هستند و نباید بدون بررسی/اجازه جداگانه تغییر کنند.

## پیشرفت واقعی تا ۱۱ نوامبر ۲۰۲۶

- [x] بررسی مستقیم دیتابیس `fxi_bot_prod` از طریق Cloudflare API؛ پیش از تغییر فقط جدول سیستمی `_cf_KV` وجود داشت.
- [x] ثبت bookmark پیش از اعمال schema برای امکان بازگشت زمانی.
- [x] اجرای موفق migration `0001` و ثبت آن در `schema_migrations`.
- [x] همسان‌سازی `schema.sql` با عملیات واقعی ذخیره‌سازی در `zeus_bot.py` و ثبت فایل در همین شاخه.
- [x] ایجاد اسکلت Worker مستقل `fxi-telegram-edge` در مسیر `cloudflare-free/worker/`؛ Workerهای موجود `bot-telegram` و `sinajs` دست‌نخورده باقی ماندند.
- [x] افزودن endpointهای `/health` و `/ready` برای بررسی اتصال D1 و نسخه schema.
- [x] افزودن ورودی webhook آزمایشی با اعتبارسنجی `X-Telegram-Bot-Api-Secret-Token`، محدودیت اندازه payload، کنترل `update_id` و ثبت idempotent در `telegram_updates`.
- [x] افزودن لایه repository برای state اصلی، تاریخچه چت AI، و آرشیو پیام‌های گروه/کانال شامل ثبت، صفحه‌بندی، جستجو، دریافت، ویرایش پیام ربات و حذف.
- [ ] اتصال repository به handlerهای واقعی و جایگزینی کامل تمام فراخوانی‌های PostgreSQL؛ این مرحله هنوز انجام نشده و باید همراه تست قرارداد پیش برود.
- [ ] تطبیق runtime برنامه با D1؛ کد فعلی هنوز از `psycopg` و SQL اختصاصی PostgreSQL استفاده می‌کند و به D1 متصل نشده است.
- [x] انتشار Worker مستقل `fxi-telegram-edge` از طریق Cloudflare API؛ Deployment ID: `45c9b634-5954-47aa-af0a-fcf4bfc04196`.
- [x] فعال‌سازی زیردامنه عمومی `workers.dev` و اتصال binding دیتابیس D1.
- [ ] افزودن Secretهای واقعی و اتصال webhook اصلی؛ در حال حاضر هیچ Secret روی Worker تعریف نشده و webhook تلگرام تغییر نکرده است.
- [x] راه‌اندازی مجدد سرویس اصلی Render؛ Deploy `dep-dbq4jpbrjlhs73b7u5e0` با build موفق و شروع مجدد polling ربات به پایان رسید.
- [x] افزودن Cron Trigger هر ۵ دقیقه به Worker برای درخواست `/health` سرویس Render و جلوگیری از خوابیدن سرویس رایگان به علت بی‌ترافیکی؛ این فقط راهکار موقت نگه‌داشتن سرویس فعلی است و جایگزین انتقال کامل runtime به Cloudflare نیست.
- [ ] اتصال handlerهای واقعی aiogram، پنل‌ها و کارهای زمان‌بندی‌شده به runtime جدید.
- [ ] انتقال داده‌های production؛ فعلاً داده‌ای از PostgreSQL به D1 منتقل نشده است.

## وضعیت آنلاین‌بودن ربات — ۱۱ نوامبر ۲۰۲۶

- سرویس `telegram-delete-assistant-pro` در Render پس از Deploy دستی دوباره بالا آمد.
- لاگ‌های جدید: `Application startup complete`، `FXI Telegram polling started`، `Start polling` و `Run polling for bot @The_fxi_bot` در `2026-11-11T10:57:53Z`.
- Render در `2026-11-11T10:58:03Z` وضعیت `Your service is live` را ثبت کرده است.
- چون سرویس روی پلن رایگان Render قرار دارد و قبلاً پس از حدود ۱۴ دقیقه بی‌ترافیکی خاموش شده بود، Cron Trigger پنج‌دقیقه‌ای روی Worker برای درخواست `/health` تنظیم شد. این راهکار برای پایداری موقت سرویس فعلی است؛ تضمین SLA یا جایگزین پلن همیشه‌روشن نیست.
- Worker هنوز پردازش‌کننده واقعی updateهای ربات نیست؛ ربات فعلاً با long polling روی Render کار می‌کند و D1 فقط زیرساخت آماده‌شده مهاجرت است.

## وضعیت انتشار آزمایشی Worker — ۱۱ نوامبر ۲۰۲۶

- آدرس عمومی Worker: `https://fxi-telegram-edge.fxi-media-engine.workers.dev`
- مسیرهای `/health` و `/ready` و `/` برای سرویس منتشر شده‌اند؛ binding دیتابیس `fxi_bot_prod` به نام `DB` وصل است.
- این انتشار فقط edge ingress و بررسی سلامت است؛ هنوز اجرای handlerهای اصلی ربات، پنل، moderation، OpenRouter و زمان‌بندی‌ها را انجام نمی‌دهد.
- هیچ secret روی Worker نصب نشده و webhook تلگرام عمداً تغییر داده نشده است؛ بنابراین این آدرس را نباید به‌عنوان ربات آنلاین یا جایگزین سرویس فعلی معرفی کرد.

## پیشرفت مرحله بعد — Worker پایه

فایل‌های جدید در شاخه مهاجرت:

- `cloudflare-free/worker/src/index.ts`
- `cloudflare-free/worker/wrangler.toml`
- `cloudflare-free/worker/README.md`
- `cloudflare-free/worker/src/store.ts`

این Worker صرفاً دریافت پایدار update را پیاده می‌کند و هنوز handlerهای ربات را اجرا نمی‌کند. این مرز عمداً حفظ شده تا پیام‌های کاربران با پاسخ موفق Telegram گم نشوند و ربات اصلی پیش از آماده‌شدن مسیر کامل تغییر webhook ندهد.

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
