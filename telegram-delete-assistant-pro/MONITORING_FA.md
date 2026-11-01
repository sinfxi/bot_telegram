# پایش و بازیابی خودکار FXI روی Render

## ساخت Cron Job
1. در Render یک Cron Job جدید بساز و مخزن `sinfxi/bot_telegram` و شاخه `feature/telegram-delete-assistant` را انتخاب کن.
2. Root Directory: `telegram-delete-assistant-pro`
3. Build Command: `pip install -r requirements.txt`
4. Schedule: `*/10 * * * *`
5. Command: `python monitor.py`
6. در Environment Variables فقط داخل Render این مقادیر را ثبت کن:
   - `SERVICE_URL=https://telegram-delete-assistant-pro.onrender.com`
   - `ZEUS_BOT_TOKEN`: توکن ربات اصلی
   - `ADMIN_CHAT_ID`: شناسه عددی تلگرام مدیر برای دریافت گزارش
   - `RENDER_DEPLOY_HOOK_URL`: آدرس محرمانه Deploy Hook از تنظیمات سرویس اصلی Render
   - اختیاری: `CHECK_TIMEOUT_SECONDS=15`

اسکریپت ابتدا پاسخ وب‌سرویس و متد `getMe` تلگرام را بررسی می‌کند. اگر یکی شکست بخورد، از Deploy Hook درخواست انتشار مجدد می‌دهد و نتیجه را به مدیر پیام می‌کند. اگر همه بررسی‌ها موفق باشند، پیام «ربات آنلاین است» می‌فرستد.

## نکات مهم
- توکن تلگرام و Deploy Hook را در GitHub یا پنل فرانت‌اند قرار نده؛ فقط در Environment امن Render ذخیره کن.
- هر بار شکست بررسی‌ها ممکن است Deploy جدید ایجاد کند؛ اسکریپت فقط هنگام شکست این کار را می‌کند.
- `getMe` معتبر بودن توکن و پاسخ API تلگرام را بررسی می‌کند، نه اینکه polling داخل سرویس قطعاً فعال است.
- اگر Render یا build خراب باشد، اسکریپت نمی‌تواند تضمین کند سرویس آنلاین شود.
- چون طبق درخواست هر ۱۰ دقیقه پیام ارسال می‌شود، پیام‌های زیادی به مدیر می‌رسد.
- این Cron Job باید جداگانه در Render ساخته و متغیرهای محیطی آن تنظیم شوند؛ هنوز ساخته نشده است.
