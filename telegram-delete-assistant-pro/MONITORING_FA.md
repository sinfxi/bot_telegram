# پایش و بازیابی خودکار FXI روی Render

## ساخت Cron Job مستقل
1. در Render یک Cron Job جداگانه بساز و مخزن `sinfxi/bot_telegram` و شاخه `feature/telegram-delete-assistant` را انتخاب کن.
2. Root Directory: `telegram-delete-assistant-pro`
3. Build Command: `pip install -r requirements.txt`
4. Schedule پیشنهادی: `*/10 * * * *`
5. Command: `python monitor.py`

## متغیرهای محیطی Cron Job
این مقادیر را فقط در Environment Variables خود Render ثبت کن:
- `SERVICE_URL=https://telegram-delete-assistant-pro.onrender.com`
- `ZEUS_BOT_TOKEN`: توکن ربات اصلی
- `ADMIN_CHAT_ID`: شناسه عددی مدیر برای دریافت هشدار
- `DATABASE_URL`: همان اتصال PostgreSQL سرویس اصلی؛ برای نگهداری امن شمارنده خطا و مهلت بازیابی
- `RENDER_DEPLOY_HOOK_URL`: آدرس محرمانه Deploy Hook سرویس اصلی Render
- اختیاری: `CHECK_TIMEOUT_SECONDS=15`
- اختیاری: `FAILURES_BEFORE_RECOVERY=3`
- اختیاری: `RECOVERY_COOLDOWN_MINUTES=30`

## منطق بازیابی
- هر اجرا مسیر `/health` را برای زنده بودن فرایند وب بررسی می‌کند و `getMe` را جداگانه برای دسترسی API تلگرام می‌سنجد.
- خطای API تلگرام به‌تنهایی هرگز باعث Deploy مجدد نمی‌شود؛ ابتدا باید وضعیت توکن، شبکه یا اختلال تلگرام بررسی شود.
- فقط پس از ۳ شکست متوالی در `/health`، یک درخواست بازیابی ارسال می‌شود.
- بین درخواست‌های بازیابی حداقل ۳۰ دقیقه فاصله است. وضعیت شمارنده و زمان آخرین درخواست در PostgreSQL ذخیره می‌شود تا اجرای هم‌زمان یا Cron بعدی Deploy پشت‌سرهم ایجاد نکند.
- اگر `DATABASE_URL` در دسترس نباشد، مانیتور هشدار می‌دهد و برای جلوگیری از حلقه Deploy، بازیابی خودکار را غیرفعال می‌کند.
- پذیرفته شدن Deploy Hook به معنی سالم شدن قطعی سرویس نیست؛ وضعیت نهایی Deploy باید در Render بررسی شود.

## نکات امنیتی و عملیاتی
- توکن تلگرام، `DATABASE_URL` و Deploy Hook را در GitHub، کد یا پنل عمومی قرار نده؛ فقط در Environment امن Render نگهداری کن.
- Cron Job باید یک سرویس مستقل باشد؛ مانیتور داخل همان فرایند اصلی نمی‌تواند زمان خاموش بودن کامل سرور را بررسی کند.
- `/health` فقط زنده بودن فرایند وب را نشان می‌دهد. بررسی `getMe` فقط دسترسی API تلگرام و اعتبار توکن را می‌سنجد و ثابت نمی‌کند polling واقعاً در حال دریافت آپدیت‌هاست.
- این مانیتور هنوز در Render ساخته نشده است؛ فایل و مستندات مخزن به‌تنهایی اجرای پایش را فعال نمی‌کنند.
