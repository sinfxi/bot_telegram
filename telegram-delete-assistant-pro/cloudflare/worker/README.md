# FXI Cloudflare Worker — migration foundation

این پوشه یک اسکلت مهاجرت مستقل است و جایگزین نسخه تولیدی Render نیست.

## محدوده فعلی
- endpointهای health و readiness
- اعتبارسنجی secret وب‌هوک تلگرام
- ثبت idempotent شناسه update در D1
- پاسخ حداقلی به /start فقط برای smoke test
- طرح اولیه دیتابیس D1

**هنوز پیاده‌سازی نشده:** handlerهای مدیریت گروه، ورود مالک/مدیر، API کامل پنل، ارسال همگانی، اتصال OpenRouter، انتقال داده و ابزار بازیابی.

## اجرای محلی
1. Node.js و Wrangler را در محیط محلی نصب کن.
2. از همین مسیر migration محلی را اجرا کن:
   `npx wrangler d1 migrations apply fxi_bot_prod --local`
3. secrets محلی را در فایل `.dev.vars` قرار بده و هرگز commit نکن:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_WEBHOOK_SECRET`
4. `npx wrangler dev` را اجرا و GET /health و GET /ready را تست کن.

تا زمان بازبینی نهایی schema از `--remote` استفاده نکن.

## انتشار
در این مرحله deploy و ثبت setWebhook عمداً انجام نمی‌شود. ربات اصلی تا پایان انتقال قابلیت‌ها، تست‌ها و تأیید rollback روی میزبان فعلی باقی می‌ماند.
