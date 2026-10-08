# 🤖 Telegram All-in-One Bot

یک ربات مدیریتی و همه‌کاره تلگرام با Python و Aiogram، مناسب گروه‌ها و کامیونیتی‌ها.

## ✨ امکانات

### 🛡 مدیریت و Moderation
- Ban / Unban
- Mute / Unmute
- Promote / Demote
- Delete / Pin
- سیستم اخطار 3 مرحله‌ای و محدودسازی خودکار

### 🔐 امنیت
- Anti-Link
- Anti-Spam
- CAPTCHA ورود اعضای جدید
- فیلتر کلمات

### 👋 مدیریت کامیونیتی
- Welcome message
- قوانین گروه
- Notes / پاسخ‌های آماده
- آمار کاربران و اخطارها
- Admin action logs

### 📢 مدیریت محتوا
- Broadcast برای کاربران ثبت‌شده
- پنل مدیریتی Inline

## 🚀 اجرا

### 1. نصب

```bash
pip install -r requirements.txt
```

### 2. تنظیم متغیرها

فایل `.env.example` را ببینید. در محیط اجرا این متغیرها را تنظیم کنید:

```text
BOT_TOKEN=...
ADMIN_IDS=123456789
DB_PATH=bot.db
PORT=8080
```

**BOT_TOKEN را داخل GitHub commit نکنید.**

### 3. اجرا

```bash
python bot.py
```

## 🚂 Railway

این پروژه برای اجرای Long Polling روی Railway آماده شده است. فقط Repository را متصل کنید و متغیرهای محیطی را در Railway تنظیم کنید.

## 📚 مستندات

فهرست کامل دستورات در [docs/COMMANDS.md](docs/COMMANDS.md) قرار دارد.

## 🧱 ساختار

```text
bot_telegram/
├── bot.py
├── requirements.txt
├── Dockerfile
├── railway.json
├── .env.example
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml
└── docs/
    └── COMMANDS.md
```

## 🔒 امنیت

- Secrets فقط از Environment Variables خوانده می‌شوند.
- فایل دیتابیس محلی داخل Git نادیده گرفته می‌شود.
- GitHub Actions برای Syntax Check فعال است.

## 📄 License

این پروژه برای استفاده و توسعه شخصی/آموزشی آماده شده است.
