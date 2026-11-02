# راهنمای استقرار FXI Telegram Community Manager روی Render

این راهنما مربوط به پروژه داخل پوشه `telegram-delete-assistant-pro/` در شاخه `feature/telegram-delete-assistant` است. Dockerfile و تنظیمات Railway ریشه مخزن متعلق به فایل‌های قدیمی پروژه FoodMind هستند و برای این سرویس استفاده نمی‌شوند.

## تنظیمات سرویس Web

- Repository: `sinfxi/bot_telegram`
- Branch: `feature/telegram-delete-assistant`
- Root Directory: `telegram-delete-assistant-pro`
- Runtime: Python
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/health`

## Environment Variables

حداقل این متغیرها را در Render تعریف کن:

- `ZEUS_BOT_TOKEN`
- `ADMIN_PANEL_USERNAME`
- `ADMIN_PANEL_PASSWORD`
- `SESSION_SECRET` (یک مقدار تصادفی طولانی و مستقل از توکن ربات)
- `ADMIN_PANEL_URL` (دامنه HTTPS سرویس، بدون `/admin`)
- `OPENROUTER_API_KEY` برای قابلیت‌های هوش مصنوعی
- `DATABASE_URL` برای ذخیره‌سازی پایدار؛ بدون آن، بعضی داده‌ها فقط در فایل محلی میزبان ذخیره می‌شوند و ممکن است با جایگزینی نمونه از بین بروند.

از مقادیر واقعی در GitHub استفاده نکن؛ فقط Environment میزبان محل نگهداری secrets است.

## پس از Deploy

1. لاگ Build و سپس لاگ اجرای برنامه را بررسی کن.
2. `/health` را برای بررسی پاسخ‌گویی وب باز کن.
3. `/ready` را برای وضعیت اتصال‌های ضروری بررسی کن.
4. ورود مالک را از `/login` و ورود مدیر ربات را از `/admin/login` آزمایش کن.
5. یک گروه آزمایشی بساز و مجوزهای لازم را به ربات بده.
6. عبارت‌های طبیعی، ضدسیل، فیلترها، اخطار، پیام همگانی و OpenRouter را جداگانه آزمایش کن.

## نکات عملیاتی

- برای هر توکن تلگرام فقط یک نمونه polling فعال نگه دار؛ اجرای چند نمونه ممکن است `getUpdates conflict` ایجاد کند.
- `/health` فقط زنده‌بودن فرایند وب را نشان می‌دهد؛ موفقیت آن تضمین‌کننده سلامت polling یا OpenRouter نیست.
- `/ready` می‌تواند در صورت نبود اتصال‌های ضروری، وضعیت 503 برگرداند.
- تغییر GitHub به‌تنهایی به معنی انتشار نیست. وضعیت deployment در Render را جداگانه بررسی کن.
