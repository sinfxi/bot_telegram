# FXI Telegram Community Manager 🛡️

[![FXI CI](https://github.com/sinfxi/bot_telegram/actions/workflows/telegram-delete-assistant-ci.yml/badge.svg?branch=feature%2Ftelegram-delete-assistant)](https://github.com/sinfxi/bot_telegram/actions/workflows/telegram-delete-assistant-ci.yml)

ربات فارسی مدیریت گروه و کانال تلگرام با فرمان‌های طبیعی، ابزارهای حرفه‌ای مدیریت اعضا، گفت‌وگوی هوشمند مبتنی بر OpenRouter و پنل وب مستقل برای مالک و مدیران ربات.

> **پروژه فعال این شاخه:** `telegram-delete-assistant-pro/`  
> این شاخه برای توسعه و نگهداری FXI Telegram Community Manager است. فایل‌های قدیمی FoodMind در ریشه مخزن، بخشی از تاریخچه قبلی مخزن هستند و نقطه ورود این پروژه محسوب نمی‌شوند.

## معرفی سریع

FXI برای مدیریت روزمره جامعه‌های تلگرام ساخته شده است: مدیر گروه می‌تواند با عبارت‌های فارسی و بدون فرمان‌های اسلش‌دار، پیام‌ها و اعضا را مدیریت کند؛ مالک ربات نیز از پنل وب، دسترسی مدیران ربات و قابلیت‌های کلی را کنترل می‌کند.

### قابلیت‌های اصلی

- **مدیریت گروه و کانال:** سنجاق و حذف پیام، سکوت و رفع سکوت، مسدودسازی، اخطار مرحله‌ای، ضدسیل، فیلتر واژه و کنترل اختیاری لینک.
- **فرمان طبیعی فارسی:** عبارت‌هایی مثل «پین»، «حذف»، «سکوت ۱۰ دقیقه»، «آزاد»، «بن»، «قوانین» و «آمار گروه». فقط `/start` به‌عنوان فرمان اسلش‌دار باقی می‌ماند.
- **هوش مصنوعی رفاقتی:** پاسخ محاوره‌ای و متناسب با فضای گروه، با OpenRouter؛ امکان فعال‌سازی مستقل برای هر گروه و محدودیت نرخ پاسخ.
- **پنل مالک و مدیر ربات:** ورود جداگانه، حساب مدیر با نام کاربری و رمز ساخته‌شده توسط مالک، و کنترل مجوزها در سمت سرور.
- **پنل گروه‌ها و کانال‌ها:** تنظیم مستقل قابلیت‌ها، سقف اخطار و فهرست واژه‌های ممنوع برای هر فضا.
- **پنل عملیاتی:** آمار، کاربران، مسدودسازی دسترسی به ربات، پیام همگانی متنی/تصویری، گزارش مدیریتی و وضعیت سرویس.
- **ذخیره‌سازی:** PostgreSQL برای داده‌های پایدار و فایل JSON به‌عنوان مسیر جایگزین؛ تاریخچه مکالمه در PostgreSQL نگهداری می‌شود.

## مسیر پروژه

| مسیر | کاربرد |
|---|---|
| `telegram-delete-assistant-pro/zeus_bot.py` | منطق ربات تلگرام، فرمان‌های طبیعی، مدیریت گروه، API و سرویس هوش مصنوعی |
| `telegram-delete-assistant-pro/panel_auth.py` | ورود مالک و مدیران، نشست‌ها و محافظت مسیرهای پنل |
| `telegram-delete-assistant-pro/app.py` | نقطه ورود FastAPI |
| `telegram-delete-assistant-pro/static/admin.html` | رابط فارسی پنل مدیریت |
| `telegram-delete-assistant-pro/docs/` | راهنمای پنل، API و مدیریت جامعه |
| `tests/test_fxi_core.py` | تست‌های رگرسیون آفلاین FXI |
| `.github/workflows/telegram-delete-assistant-ci.yml` | کنترل کامپایل، تست‌ها و نحو JavaScript در CI |

## اجرای محلی

نیازمندی: Python 3.11 یا جدیدتر.

```bash
cd telegram-delete-assistant-pro
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

مقدارهای واقعی را در فایل محلی `.env` وارد کن؛ این فایل را هرگز commit نکن. سپس اجرا کن:

```bash
uvicorn app:app --env-file .env --host 0.0.0.0 --port 8000
```

برای راهنمای کامل استقرار و تنظیمات، فایل [راهنمای پروژه](telegram-delete-assistant-pro/README.md) را ببین.

## تنظیمات ضروری

- `ZEUS_BOT_TOKEN`: توکن ربات از BotFather.
- `ADMIN_PANEL_USERNAME` و `ADMIN_PANEL_PASSWORD`: نام کاربری و رمز مالک اصلی پنل.
- `SESSION_SECRET`: کلید تصادفی طولانی برای امضای نشست‌ها.
- `OPENROUTER_API_KEY`: کلید سرویس هوش مصنوعی.
- `DATABASE_URL`: آدرس PostgreSQL برای ذخیره‌سازی پایدار.
- `ADMIN_PANEL_URL`: آدرس پایه HTTPS پنل، بدون مسیر `/admin`.

**هیچ توکن، رمز یا کلید API را در GitHub قرار نده.** مقدارهای واقعی فقط باید در Environment میزبان تنظیم شوند. اگر توکنی قبلاً منتشر شده، آن را از پنل ارائه‌دهنده تعویض کن.

## پنل‌ها

- مالک ربات: [ورود مالک](https://telegram-delete-assistant-pro.onrender.com/login)؛ پس از ورود به پنل مالک هدایت می‌شود.
- مدیر ربات: [ورود مدیر](https://telegram-delete-assistant-pro.onrender.com/admin/login)؛ فقط حساب‌هایی که مالک ساخته است امکان ورود دارند.
- مدیر گروه، به‌تنهایی مدیر ربات یا مالک پنل محسوب نمی‌شود.

## وضعیت و پایش

- `GET /health`: بررسی زنده‌بودن فرایند وب.
- `GET /ready`: بررسی آمادگی اتصال‌های ضروری.
- لاگ‌های Render و نتیجه GitHub Actions را پیش از انتشار نسخه بررسی کن.

## تست‌ها

```bash
python -m compileall -q telegram-delete-assistant-pro
python -m unittest discover -s tests -p "test_fxi_core.py" -v
```

GitHub Actions علاوه بر این موارد، نحو JavaScript پنل و صفحه ورود و ثبت مسیرهای اصلی احراز هویت را بررسی می‌کند. موفقیت CI جایگزین تست واقعی در تلگرام و مرورگر نیست.

## تاریخچه نسخه‌ها

- [تاریخچه تغییرات](CHANGELOG.md)

## مستندات تکمیلی

- [راهنمای پنل مدیریت](telegram-delete-assistant-pro/docs/ADMIN_CONSOLE_FA.md)
- [راهنمای مدیریت گروه و کانال](telegram-delete-assistant-pro/docs/COMMUNITY_MANAGER_FA.md)
- [راهنمای تنظیم API](telegram-delete-assistant-pro/docs/API_SETUP_FA.md)
- [پایش و عیب‌یابی](telegram-delete-assistant-pro/MONITORING_FA.md)

## محدودیت‌های شناخته‌شده

- برای دریافت پیام‌های معمولی گروه، Privacy ربات در BotFather باید متناسب با شیوه استفاده تنظیم شود.
- حذف پیام، سنجاق و محدودسازی اعضا به مجوزهای مناسب ربات در گروه نیاز دارد.
- ربات تاریخچه قدیمی گروه را بازیابی نمی‌کند؛ آمار از زمان دریافت رویدادها جمع می‌شود.
- در هر محیط فقط یک نمونه polling برای هر توکن اجرا کن تا با خطای `getUpdates conflict` مواجه نشوی.
- حالت گفت‌وگوی طبیعی و پاسخ‌های هوشمند وابسته به تنظیم بودن OpenRouter و دسترسی شبکه است.

---

**FXI Telegram Community Manager** — مدیریت شفاف‌تر، کنترل دقیق‌تر و تعامل طبیعی‌تر در جامعه‌های تلگرام.
