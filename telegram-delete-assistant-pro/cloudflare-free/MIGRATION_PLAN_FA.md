# برنامه مهاجرت رایگان FXI به Cloudflare

شاخه مرجع: `feature/telegram-delete-assistant`
مسیر: `telegram-delete-assistant-pro/cloudflare-free/`

## مرز ایمنی

- این پیاده‌سازی فقط staging است و به Worker یا D1 عملیاتی متصل نمی‌شود.
- نام Worker آزمایشی: `fxi-telegram-edge-stage`
- دیتابیس آزمایشی: `fxi-telegram-assistant-stage`
- webhook ربات اصلی، polling فعلی، Render و داده‌های کاربران تا پایان آزمون parity تغییر نمی‌کنند.
- هیچ secret یا token در مخزن ثبت نمی‌شود.
- اجرای migration و deploy فقط از GitHub Actions دستی و با Secrets انجام می‌شود.

## وضعیت پیاده‌سازی

- [x] دریافت webhook با بررسی هدر secret تلگرام
- [x] محدودیت اندازه payload و اعتبارسنجی update_id
- [x] ثبت idempotent رویدادها در D1 آزمایشی
- [x] repository اولیه برای state، تاریخچه AI و آرشیو پیام‌های جامعه
- [x] endpointهای health و readiness
- [x] پیکربندی Wrangler مستقل از production
- [x] workflow دستی برای migration و deploy staging
- [ ] مصرف و اجرای updateهای ذخیره‌شده؛ در این مرحله هنوز ingest-only است
- [ ] انتقال handlerهای واقعی aiogram و قابلیت‌های moderation
- [ ] انتقال تمام 67 route پنل مالک/مدیر/مالک گروه
- [ ] انتقال نشست‌ها، OTP، CSRF و permission checks
- [ ] انتقال وظایف پس‌زمینه به Cron/Queues
- [ ] export/transform/import داده‌ها از PostgreSQL با backup و تطبیق شمارش
- [ ] تست قرارداد و end-to-end در گروه آزمایشی
- [ ] cutover کنترل‌شده webhook تولید، فقط با تأیید جداگانه

## معماری رایگان هدف

Cloudflare Worker TypeScript برای webhook و API، D1 برای داده‌های ساختاریافته، Cron Triggers برای کارهای دوره‌ای کوتاه، و Secrets برای اطلاعات محرمانه. از Workers Paid، Containers و سرویس پولی استفاده نمی‌شود.

## ترتیب کار

1. Deploy و تست staging بدون اتصال Telegram webhook.
2. ساخت queue/dispatcher امن برای updateهای ذخیره‌شده و retry محدود.
3. انتقال handlerها و adapter دیتابیس.
4. انتقال پنل‌ها و احراز هویت.
5. تست parity و backup/restore.
6. cutover و rollback فقط پس از قبولی تمام معیارهای پذیرش.
