# FXI Telegram — Cloudflare Python runtime (staging)

این پروژه یک runtime مستقل برای مهاجرت تدریجی ربات به Cloudflare Python Workers است. عمداً `zeus_bot.py` را import نمی‌کند؛ چون آن برنامه در startup، polling و taskهای بلندمدت راه می‌اندازد و به PostgreSQL متکی است.

## محدوده فعلی

- Python Worker native با `workers.WorkerEntrypoint`
- ورودی webhook با اعتبارسنجی `X-Telegram-Bot-Api-Secret-Token`
- جلوگیری از پردازش تکراری updateها با کلید اصلی D1
- ذخیره محدود تاریخچه پیام‌ها و پست‌های کانال در D1
- پاسخ پایه به `/start` و `/help`
- پاسخ هوشمند پایه با OpenRouter برای چت خصوصی و منشن/ریپلای در گروه
- مسیرهای `/health` و `/ready`
- فایل‌های static از binding دارایی‌ها

این مرحله **معادل کامل** برنامه Python فعلی نیست. پنل‌های مالک/مدیر/مالک گروه، مجوزهای مدیر، ابزارهای moderation، پشتیبان‌گیری و تمام قراردادهای API هنوز باید منتقل و تست شوند.

## نصب و اجرای محلی

نیازمند Python 3.13+، uv و Node.js است.

```bash
uv sync
uv run pywrangler dev
```

## Secrets محیط staging

مقادیر را فقط از طریق Cloudflare Worker secrets وارد کنید؛ هرگز در Git ثبت نکنید:

- `ZEUS_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET`
- `OPENROUTER_API_KEY` (اختیاری)
- `TELEGRAM_BOT_USERNAME` (اختیاری؛ مقدار پیش‌فرض The_fxi_bot)

این Worker به D1 مستقل `fxi-telegram-assistant-stage` متصل است و به دیتابیس production دست نمی‌زند.

## انتشار staging

```bash
uv run pywrangler deploy
```

پس از انتشار، ابتدا `GET /health` و `GET /ready` را بررسی کنید. این پروژه به‌صورت پیش‌فرض webhook ربات را ثبت یا تغییر نمی‌دهد. فقط بعد از تنظیم secretها و اجرای تست‌های قرارداد/امنیت، ثبت webhook آزمایشی مجاز است.

## برنامه ادامه مهاجرت

1. انتقال routeهای FastAPI و قرارداد API پنل‌ها.
2. port کردن لایه auth/session/CSRF و permission checks با حفظ رفتار.
3. انتقال moderation و group-owner workflows.
4. مهاجرت schema و داده‌ها با ابزار export/import قابل تکرار؛ بدون حذف PostgreSQL منبع.
5. تست parity کامل در گروه و کانال آزمایشی.
6. cutover فقط پس از تأیید readiness و rollback plan.


## مجوز لازم برای GitHub Actions

برای انتشار staging، دو Repository Secret زیر باید در
`Settings → Secrets and variables → Actions` موجود باشند:

- `CLOUDFLARE_API_TOKEN`: توکن API با scope همان Account و دسترسی‌های:
  - `Account Settings: Read`
  - `Workers Scripts: Edit`
- `CLOUDFLARE_ACCOUNT_ID`: شناسه حساب Cloudflare که Worker staging در آن ساخته می‌شود.

خطای Wrangler با کد `10000` در اجرای CI قبلی نشان داد توکن فعلی برای درخواست metadata/deploy مجوز کافی ندارد یا حساب را نمی‌تواند resolve کند. توکن را در چت یا Git ثبت نکنید؛ فقط در GitHub Actions Secrets ذخیره کنید. پس از اصلاح مجوزها، workflow را دوباره اجرا کنید.


<!-- staging validation trigger: 2026-11-11 -->
