# FXI Telegram Edge — staging

این Worker فقط محیط آزمایشی و دریافت پایدار Update است؛ ربات اصلی یا جایگزین production نیست.

- Worker: `fxi-telegram-edge-stage`
- D1: `fxi-telegram-assistant-stage`
- D1 binding: `DB`
- مسیر webhook: `POST /telegram/webhook`
- health: `GET /health`
- readiness: `GET /ready`

## امنیت

- هیچ توکن/کلید واقعی در Git قرار ندهید.
- webhook production را به این Worker متصل نکنید.
- این runtime در حال حاضر Update را فقط در D1 ذخیره می‌کند و handlerهای ربات را اجرا نمی‌کند.
- Worker عملیاتی، D1 عملیاتی و Render خارج از محدوده این workflow هستند.

## Deploy رایگان staging

در GitHub → Settings → Secrets and variables → Actions دو Repository Secret بسازید:

- `CLOUDFLARE_API_TOKEN`: مجوز Workers Scripts:Edit و D1:Edit فقط در همان Account
- `CLOUDFLARE_ACCOUNT_ID`: شناسه Account

سپس از Actions، workflow با نام `FXI Cloudflare Free staging` را دستی اجرا کنید. Workflow ابتدا migration دیتابیس staging را اعمال و سپس فقط Worker آزمایشی را deploy می‌کند.

پس از انتشار، فقط `/health` و `/ready` را تست کنید. ثبت webhook تلگرام در این مرحله عمداً انجام نمی‌شود.
