# 🤖 رباتی که فقط «ربات» نیست...

> **یک ربات همه‌کاره برای مدیریت گروه‌های تلگرام؛ از اولین پیام کاربر تا آخرین اخطار، همه‌چیز زیر کنترل شماست.**

اگر دنبال یک ربات ساده با چند دستور تکراری هستی، این پروژه برای تو نیست.  
اما اگر می‌خواهی ببینی یک **پنل مدیریتی، سیستم امنیتی، ضداسپم، CAPTCHA، اخطار، فیلتر، یادداشت و مدیریت کاربران** چطور در یک ربات جمع می‌شوند، ادامه بده. 👀

<p align="center">
  <a href="https://github.com/sinfxi/bot_telegram">
    <img src="https://img.shields.io/badge/GitHub-View%20Project-181717?style=for-the-badge&logo=github" alt="GitHub">
  </a>
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Aiogram-3.x-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white" alt="Aiogram">
  <img src="https://img.shields.io/github/actions/workflow/status/sinfxi/bot_telegram/ci.yml?branch=main&style=for-the-badge&label=CI" alt="CI">
</p>

---

## 👀 اول این را ببین

تصور کن یک نفر وارد گروه می‌شود...

**CAPTCHA فعال است.**  
ربات ورود او را بررسی می‌کند. 🛡️

شروع به ارسال لینک می‌کند؟

**Anti-Link وارد عمل می‌شود.** 🔗

در چند ثانیه چندین پیام می‌فرستد؟

**Anti-Spam آماده است.** ⚡

قوانین را رعایت نمی‌کند؟

**Warn → Warn → محدودسازی.** 🚨

و ادمین؟

همه‌چیز را از طریق دستورها و **پنل Inline** کنترل می‌کند. 👑

این دقیقاً ایده‌ی این پروژه است.

---

# 🔥 چه چیزی داخلش هست؟

| بخش | قابلیت |
|---|---|
| 🛡️ Moderation | Ban / Unban / Mute / Unmute |
| 👑 Admin | Promote / Demote / Delete / Pin |
| 🚨 Warning | سیستم اخطار + محدودسازی خودکار |
| 🔐 Security | Anti-Link / Anti-Spam / CAPTCHA |
| 🧹 Filters | فیلتر کلمات و مدیریت فیلترها |
| 👋 Community | Welcome + Rules |
| 📝 Notes | ذخیره و بازیابی پاسخ‌های آماده |
| 📊 Management | آمار کاربران و لاگ اقدامات |
| 📢 Broadcast | ارسال پیام همگانی |
| 🎛️ Panel | پنل مدیریتی Inline |

---

## 🧠 سیستم اخطار فقط یک شمارنده نیست

مثلاً:

```
⚠️ Warning #1
        ↓
⚠️ Warning #2
        ↓
🚨 Warning #3
        ↓
🔒 محدودسازی کاربر
```

اخطارها در دیتابیس ذخیره می‌شوند و برای هر گروه و کاربر جداگانه مدیریت می‌شوند.

---

# 🛡️ بخش امنیتی

### 🔗 Anti-Link
لینک‌های ناخواسته را شناسایی و حذف می‌کند.

### ⚡ Anti-Spam
ارسال پشت‌سرهم پیام‌ها را بررسی می‌کند و در صورت تشخیص رفتار اسپمی واکنش نشان می‌دهد.

### 🤖 CAPTCHA
عضو جدید قبل از فعالیت، باید تأیید شود.

### 🚫 Word Filter
کلمات مشخص‌شده توسط ادمین قابل فیلتر هستند.

---

# 👑 پنل مدیریت

پنل Inline برای اینکه مدیریت فقط مجموعه‌ای از دستورهای خشک نباشد:

```
┌────────────────────────────┐
│       👑 ADMIN PANEL       │
├────────────────────────────┤
│ 📊 آمار       👥 کاربران   │
│ 🛡 امنیت      📝 امکانات   │
│ 📢 همگانی                  │
└────────────────────────────┘
```

از همین‌جا می‌توانی به بخش‌های مدیریتی و آماری دسترسی داشته باشی.

---

# 📝 یک قابلیت جالب: Notes

پاسخ‌های تکراری را یک بار ذخیره کن.

```
/note rules قوانین کامل گروه...
```

بعد:

```
/getnote rules
```

و ربات همان متن را برمی‌گرداند.

برای قوانین، FAQ، پیام‌های آماده و پاسخ‌های پرتکرار کاربردی است.

---

# 🎯 چند دستور برای شروع

```
/admin
/warn
/warnings
/ban
/mute
/antilink on
/antispam on
/captcha on
/filter spam
/note rules متن قوانین
/getnote rules
```

فهرست کامل دستورها:

👉 [📚 COMMANDS.md](docs/COMMANDS.md)

---

# ⚙️ تکنولوژی

- 🐍 **Python**
- 🤖 **Aiogram 3**
- 🗄️ **SQLite**
- 🌐 **aiohttp**
- 🚂 **Railway**
- ⚙️ **GitHub Actions**

ساختار پروژه عمداً ساده نگه داشته شده تا بتوانی سریع آن را اجرا، بررسی و توسعه بدهی.

---

# 🚀 اجرا در چند قدم

### 1️⃣ نصب وابستگی‌ها

```bash
pip install -r requirements.txt
```

### 2️⃣ تنظیم Environment Variables

```env
BOT_TOKEN=your_bot_token
ADMIN_IDS=123456789
DB_PATH=bot.db
PORT=8080
```

> 🔒 توکن ربات را هیچ‌وقت داخل GitHub قرار نده.

### 3️⃣ اجرا

```bash
python bot.py
```

---

# 🚂 آماده برای Railway

این پروژه برای اجرای **Long Polling** روی Railway آماده شده است.

کافی است Repository را متصل کرده و متغیرهای محیطی را تنظیم کنی.

---

# 🧱 ساختار پروژه

```text
bot_telegram/
│
├── 🤖 bot.py
├── 📦 requirements.txt
├── 🐳 Dockerfile
├── 🚂 railway.json
│
├── 🔐 .env.example
├── 🚫 .gitignore
│
├── ⚙️ .github/
│   └── workflows/
│       └── ci.yml
│
└── 📚 docs/
    └── COMMANDS.md
```

---

# 🔒 امنیت پروژه

- Secrets از Environment Variables خوانده می‌شوند.
- فایل دیتابیس محلی داخل Git نادیده گرفته می‌شود.
- CI برای بررسی Syntax فعال است.
- اطلاعات حساس نباید داخل Repository قرار بگیرند.

---

# 🧪 این پروژه هنوز جای رشد دارد...

اینجا قسمت جذاب ماجراست. 👀

این ربات را می‌توان به سمت یک **پلتفرم کامل مدیریت کامیونیتی** توسعه داد:

- 📅 زمان‌بندی پیام‌ها
- 📈 آمار پیشرفته گروه
- 🧠 سیستم ضداسپم هوشمندتر
- 🎛️ پنل مدیریتی کامل‌تر
- 📢 مدیریت کانال
- 🏆 سیستم امتیاز و Level
- 🎮 Gamification
- 🔌 سیستم Plugin
- 🌐 Web Admin Panel

**یعنی این پایان پروژه نیست؛ نقطه شروع آن است.**

---

## ⭐ اگر ایده‌اش برات جالب بود...

Repository را ببین، کد را بررسی کن و ببین این ربات واقعاً چطور ساخته شده:

<p align="center">
  <a href="https://github.com/sinfxi/bot_telegram">
    <img src="https://img.shields.io/badge/⭐%20Explore%20the%20Project-000000?style=for-the-badge" alt="Explore the project">
  </a>
</p>

---

### 👨‍💻 ساخته‌شده با Python و Aiogram

**Telegram All-in-One Bot**  
از یک ربات ساده شروع شد؛ هدفش تبدیل‌شدن به یک ابزار کامل برای مدیریت کامیونیتی است.
