# راهنمای تنظیم APIهای هوش مصنوعی FXI

این راهنما برای سرویس `telegram-delete-assistant-pro` است. هیچ کلید API نباید داخل GitHub یا فایل کد قرار بگیرد؛ همه کلیدها را فقط در بخش Environment سرویس Render وارد کنید.

## سرویس‌های درخواستی

| سرویس | متغیرهای Render | مدل پیش‌فرض کد |
|---|---|---|
| Google Gemini | `GEMINI_API_KEY` | `gemini-2.5-flash` |
| Groq | `GROQ_API_KEY` | `openai/gpt-oss-120b` |
| OpenRouter | `OPENROUTER_API_KEY` | `openrouter/free` |
| Mistral | `MISTRAL_API_KEY` | `mistral-small-latest` |
| Cloudflare Workers AI | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | `@cf/meta/llama-3.1-8b-instruct` |
| NVIDIA NIM | `NVIDIA_API_KEY` | `meta/llama-3.3-70b-instruct` |
| SambaNova | `SAMBANOVA_API_KEY` | `DeepSeek-V3.1` |
| Cohere | `COHERE_API_KEY` | `command-a-03-2025` |

## متغیرهای اختیاری برای تغییر مدل

در صورت نیاز می‌توانید این متغیرها را هم تنظیم کنید:

- `GEMINI_MODEL`
- `GROQ_MODEL`
- `OPENROUTER_MODEL`
- `MISTRAL_MODEL`
- `CLOUDFLARE_MODEL`
- `NVIDIA_MODEL`
- `SAMBANOVA_MODEL`
- `COHERE_MODEL`

شناسه مدل‌ها و سهمیه رایگان ارائه‌دهندگان ممکن است تغییر کند؛ پیش از فعال‌سازی نهایی، مدل انتخابی باید با فهرست مدل‌های قابل‌دسترسی همان حساب تطبیق داده و با کلید واقعی آزمایش شود. «رایگان» به معنی نامحدود یا تضمین‌شده نیست.

## نکات مهم

1. برای Cloudflare، توکن باید مجوز دسترسی Workers AI در همان حساب را داشته باشد و Account ID نیز لازم است.
2. OpenRouter با مدل `openrouter/free` می‌تواند یک مدل رایگانِ در دسترس را انتخاب کند؛ محدودیت‌های نرخ و سهمیه همچنان اعمال می‌شوند.
3. کلیدهای API را در پیام تلگرام، GitHub، کد منبع یا اسکرین‌شات عمومی منتشر نکنید.
4. وضعیت «آماده» در پنل فعلی فقط وجود متغیر کلید را نشان می‌دهد؛ اثبات نمی‌کند که کلید معتبر است یا مدل سهمیه دارد. تست واقعی با ارسال یک درخواست انجام می‌شود.
5. این commit فقط روی شاخه GitHub قرار می‌گیرد. تا دریافت تأیید نهایی جداگانه، هیچ Deploy یا تغییری روی سرویس زنده انجام نمی‌شود.
