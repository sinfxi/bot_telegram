# ماتریس تطبیق API ربات FXI در مهاجرت Cloudflare

این فهرست از route decoratorهای شاخه `feature/telegram-delete-assistant` استخراج شده است. شمارش قابل بازتولید این سه فایل **67 مسیر HTTP** است؛ بنابراین عدد ۶۷ مسیر API در درخواست کاربر با این سه فایل تطبیق دارد.

**معیار مهم:** هیچ endpoint صرفاً به دلیل وجود UI، فایل HTML یا پاسخ ساده Worker منتقل‌شده محسوب نمی‌شود. هر مسیر باید قرارداد ورودی/خروجی، خطاها، مجوز سمت سرور، اثر واقعی در D1/Telegram، audit و تست مثبت/منفی داشته باشد.

## وضعیت فعلی

- Worker staging فعلی فقط webhook پایه، سلامت، آمادگی و رفتار محدود گفتگو را دارد.
- هیچ‌یک از 67 مسیر زیر هنوز با parity کامل در Worker پیاده‌سازی و تست نشده است.
- پنل مالک گروه، نقش‌ها و مجوزها، مدیریت کامل گروه/کانال، پشتیبان‌گیری و بازیابی هنوز در محدوده مهاجرت باقی‌اند.
- تست compile و migration با تست runtime، E2E تلگرام یا پذیرش قابلیت‌ها یکسان نیست.

## zeus_bot.py (36)

| Method | Path | Cloudflare parity |
|---|---|---|
| GET | `/` | Not implemented / not verified |
| GET | `/admin/invite/{token}` | Not implemented / not verified |
| POST | `/admin/invite/{token}` | Not implemented / not verified |
| POST | `/admin/logout` | Not implemented / not verified |
| GET | `/static/admin.css` | Not implemented / not verified |
| GET | `/static/admin.js` | Not implemented / not verified |
| GET | `/admin` | Not implemented / not verified |
| GET | `/admin/api/audit` | Not implemented / not verified |
| GET | `/admin/api/users/export` | Not implemented / not verified |
| POST | `/admin/api/users/{user_id}/block` | Not implemented / not verified |
| POST | `/admin/api/users/{user_id}/unblock` | Not implemented / not verified |
| GET | `/admin/api/community` | Not implemented / not verified |
| POST | `/admin/api/community/{chat_id}/settings` | Not implemented / not verified |
| POST | `/admin/api/community/{chat_id}/leave` | Not implemented / not verified |
| GET | `/admin/api/status` | Not implemented / not verified |
| GET | `/admin/api/conversations` | Not implemented / not verified |
| GET | `/admin/api/conversations/{user_id}` | Not implemented / not verified |
| POST | `/admin/api/manager-invites` | Not implemented / not verified |
| POST | `/admin/api/manager-invites/revoke` | Not implemented / not verified |
| POST | `/admin/api/manager-requests` | Not implemented / not verified |
| POST | `/admin/api/manager-requests/{request_id}/approve` | Not implemented / not verified |
| POST | `/admin/api/manager-requests/{request_id}/reject` | Not implemented / not verified |
| DELETE | `/admin/api/managers/{username}` | Not implemented / not verified |
| GET | `/admin/api/managers/{username}/permissions` | Not implemented / not verified |
| POST | `/admin/api/managers/{username}/permissions` | Not implemented / not verified |
| GET | `/admin/api/admins/{user_id}/permissions` | Not implemented / not verified |
| POST | `/admin/api/admins/{user_id}/permissions` | Not implemented / not verified |
| POST | `/admin/api/features` | Not implemented / not verified |
| POST | `/admin/api/bot-state` | Not implemented / not verified |
| POST | `/admin/api/broadcast` | Not implemented / not verified |
| POST | `/admin/api/prompt` | Not implemented / not verified |
| GET | `/admin/api/payments` | Not implemented / not verified |
| POST | `/admin/api/payments/{payment_id}/{action}` | Not implemented / not verified |
| GET | `/admin/api/metrics` | Not implemented / not verified |
| GET | `/health` | Not implemented / not verified |
| GET | `/ready` | Not implemented / not verified |

## group_owner.py (21)

| Method | Path | Cloudflare parity |
|---|---|---|
| GET | `/group-owner` | Not implemented / not verified |
| GET | `/group-owner/panel` | Not implemented / not verified |
| GET | `/group-owner/static/{asset}` | Not implemented / not verified |
| POST | `/group-owner/api/request-code` | Not implemented / not verified |
| POST | `/group-owner/api/login` | Not implemented / not verified |
| POST | `/group-owner/api/logout` | Not implemented / not verified |
| GET | `/group-owner/api/overview` | Not implemented / not verified |
| GET | `/group-owner/api/messages` | Not implemented / not verified |
| GET | `/group-owner/api/members` | Not implemented / not verified |
| POST | `/group-owner/api/settings` | Not implemented / not verified |
| POST | `/group-owner/api/messages/{message_id}/delete` | Not implemented / not verified |
| POST | `/group-owner/api/messages/{message_id}/edit` | Not implemented / not verified |
| POST | `/group-owner/api/members/{user_id}/{action}` | Not implemented / not verified |
| POST | `/group-owner/api/leave` | Not implemented / not verified |
| GET | `/group-owner/api/add-link` | Not implemented / not verified |
| POST | `/admin/api/community/inspect` | Not implemented / not verified |
| GET | `/admin/api/community/{chat_id}/messages` | Not implemented / not verified |
| POST | `/admin/api/community/{chat_id}/messages/{message_id}/delete` | Not implemented / not verified |
| POST | `/admin/api/community/{chat_id}/messages/{message_id}/edit` | Not implemented / not verified |
| POST | `/admin/api/community/{chat_id}/leave` | Not implemented / not verified |
| GET | `/admin/api/community/{chat_id}/add-link` | Not implemented / not verified |

## panel_auth.py (10)

| Method | Path | Cloudflare parity |
|---|---|---|
| GET | `/owner` | Not implemented / not verified |
| GET | `/owner/api/backup` | Not implemented / not verified |
| GET | `/admin/request` | Not implemented / not verified |
| GET | `/admin/login` | Not implemented / not verified |
| POST | `/auth/manager-request-code` | Not implemented / not verified |
| POST | `/auth/manager-login` | Not implemented / not verified |
| GET | `/login` | Not implemented / not verified |
| POST | `/auth/owner-request-code` | Not implemented / not verified |
| POST | `/auth/owner-login` | Not implemented / not verified |
| POST | `/auth/logout` | Not implemented / not verified |

## ترتیب تحویل

1. **پایه داده:** schema کامل D1، migration ledger، adapterهای query/transaction، import/export قابل تکرار.
2. **امنیت:** نشست امن، cookie، CSRF، origin policy، کدهای یک‌بارمصرف، rate limit، نقش‌ها و permission matrix.
3. **مالک و مدیر:** تمام APIهای پنل، audit log، دعوت/لغو دعوت، درخواست و تأیید مدیر، مجوزهای ریزدانه.
4. **مالک گروه:** ورود با کد، اثبات مالکیت گروه، overview، پیام‌ها، اعضا، تنظیمات و عملیات مجاز.
5. **گروه/کانال:** moderation، حذف/ویرایش پیام، خروج، welcome، anti-flood، link/keyword/media guard، پست‌ها و پیشنهاد محتوا.
6. **عملیات:** broadcast متن/تصویر با Queue و retry، مکالمه و AI، پرداخت/حمایت، metrics.
7. **پشتیبان‌گیری:** snapshot رمزگذاری‌شده به R2، retention، manifest/checksum، restore آزمایشی و گزارش ممیزی.
8. **پذیرش:** تست تمام 67 مسیر، آزمون مجوزهای role-by-role، E2E در گروه و کانال آزمایشی، webhook rollback و cutover کنترل‌شده.

## معیار پذیرش هر endpoint

- method/path و schema درخواست/پاسخ با FastAPI اصلی منطبق باشد.
- permission check در backend اجرا شود؛ کنترل UI به‌تنهایی کافی نیست.
- ورودی نامعتبر، نبود نشست، نقش ناکافی، منبع متعلق به دیگری و خطای Telegram/D1 تست شوند.
- side-effect واقعی idempotent یا قابل retry باشد و نتیجه در audit ثبت شود.
- برای عملیات حساس، مالکیت، تأیید، rate limit و rollback تعریف شود.
- مسیر فقط پس از تست staging به وضعیت «تکمیل‌شده» ارتقا پیدا کند.

## حفاظت از Production

Worker و D1 فعلی Production دست‌نخورده می‌مانند. ربات اصلی تا پایان آزمون staging از webhook فعلی استفاده می‌کند. هیچ داده‌ای از منبع اصلی حذف یا overwrite نمی‌شود.
