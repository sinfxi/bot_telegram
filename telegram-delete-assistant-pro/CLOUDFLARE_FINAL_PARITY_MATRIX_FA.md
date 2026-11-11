# ماتریس تکمیل نسخه نهایی FXI Telegram

این سند معیار پذیرش مهاجرت کامل است. قابلیت‌های زیر از کد فعلی شاخه `feature/telegram-delete-assistant` استخراج شده‌اند؛ وضعیت «در انتظار انتقال» به معنی وجود قابلیت در نسخه اصلی و نبود parity تأییدشده در runtime جدید Cloudflare است.

## وضعیت runtime جدید

| بخش | وضعیت | معیار پذیرش |
|---|---|---|
| Webhook تلگرام | در حال توسعه | بررسی secret، update ID معتبر، idempotency، retry امن |
| D1 staging | آماده اولیه | schema versioned، queryها و migration تست‌شده |
| OpenRouter | نمونه اولیه | مدیریت خطا، timeout، مدل و محدودیت مصرف |
| پنل مالک | در انتظار انتقال | تمام routeها و احراز هویت برابر نسخه اصلی |
| پنل مدیران | در انتظار انتقال | نقش‌ها، permissionهای سمت سرور و ابطال نشست |
| پنل مالک گروه | در انتظار انتقال | اثبات مالکیت از Telegram و همه عملیات گروه |
| Moderation | در انتظار انتقال | تست واقعی گروه با دسترسی‌های Telegram |
| backup/restore | در انتظار انتقال | خروجی، checksum، بازیابی آزمایشی و نگهداری امن |
| production cutover | مسدود تا پذیرش | smoke test، rollback، webhook کنترل‌شده |

## قابلیت‌های اصلی موردنیاز

### هسته و پاسخ‌گویی هوشمند
- [ ] پاسخ خصوصی و گروهی با OpenRouter
- [ ] تشخیص منشن و ریپلای به پیام ربات
- [ ] حالت گفت‌وگوی رفاقتی گروه با محدودیت نرخ
- [ ] حافظه و تاریخچه مکالمه
- [ ] دستورالعمل سراسری مدل
- [ ] تحلیل تصویر رسید
- [ ] فرمان‌های طبیعی فارسی و تنظیمات AI
- [ ] مدیریت مدل و تاریخچه خصوصی

### مدیریت گروه و کانال
- [ ] قوانین گروه و تنظیمات
- [ ] حذف، سنجاق، اخطار، سکوت، آزادسازی و مسدودسازی
- [ ] ضدسیل و ضداسپم
- [ ] فیلتر واژه و لینک
- [ ] خوشامدگویی
- [ ] آمار گروه و اعضا
- [ ] گزارش کانال و پست‌های برتر
- [ ] برنامه محتوا، چالش و پیشنهاد موضوع
- [ ] روشن/خاموش کردن قابلیت‌ها برای هر فضای مستقل

### پنل مالک و مدیران
- [ ] ورود مالک با OTP تلگرام
- [ ] ورود مدیر با OTP تلگرام
- [ ] دعوت و تأیید درخواست مدیر
- [ ] مدیریت مدیران و لغو نشست
- [ ] مجوزهای تفکیکی مدیر در سمت سرور
- [ ] کاربران، مسدودسازی و خروجی CSV
- [ ] گفت‌وگوها و تاریخچه
- [ ] پیام همگانی
- [ ] گزارش رویدادهای مدیریتی
- [ ] وضعیت سرویس، سلامت و پشتیبان‌گیری

### پنل مالک گروه
- [ ] تأیید مالک واقعی گروه از Telegram API
- [ ] کد ورود یک‌بارمصرف و نشست گروهی
- [ ] نمای کلی و اعضا
- [ ] تاریخچه پیام‌ها با صفحه‌بندی
- [ ] ویرایش/حذف پیام‌های ربات
- [ ] اقدامات مدیریتی روی اعضا
- [ ] تنظیمات گروه
- [ ] ساخت لینک افزودن ربات و خروج ربات

## قراردادهای HTTP استخراج‌شده از برنامه فعلی

تعداد routeهای ثبت‌شده در سه ماژول FastAPI: **67**. هر route باید در Worker جدید با همان نقش، اعتبارسنجی، ساختار پاسخ و کنترل مجوز پیاده‌سازی و تست شود.

### zeus_bot.py (36 route)

| متد | مسیر | handler |
|---|---|---|
| `GET` | `"/"` | `admin_root_redirect` |
| `GET` | `"/admin/invite/{token}", HTML` | `preview_admin_invite` |
| `POST` | `"/admin/invite/{token}"` | `accept_admin_invite` |
| `POST` | `"/admin/logout"` | `admin_logout` |
| `GET` | `"/static/admin.css"` | `admin_panel_css` |
| `GET` | `"/static/admin.js"` | `admin_panel_js` |
| `GET` | `"/admin", HTML` | `admin_panel` |
| `GET` | `"/admin/api/audit"` | `admin_audit` |
| `GET` | `"/admin/api/users/export"` | `admin_export_users` |
| `POST` | `"/admin/api/users/{user_id}/block"` | `block_bot_user` |
| `POST` | `"/admin/api/users/{user_id}/unblock"` | `unblock_bot_user` |
| `GET` | `"/admin/api/community"` | `admin_community` |
| `POST` | `"/admin/api/community/{chat_id}/settings"` | `update_community_settings` |
| `POST` | `"/admin/api/community/{chat_id}/leave"` | `leave_community_chat` |
| `GET` | `"/admin/api/status"` | `admin_status` |
| `GET` | `"/admin/api/conversations"` | `admin_conversations` |
| `GET` | `"/admin/api/conversations/{user_id}"` | `admin_conversation` |
| `POST` | `"/admin/api/manager-invites"` | `create_manager_invite` |
| `POST` | `"/admin/api/manager-invites/revoke"` | `revoke_manager_invite` |
| `POST` | `"/admin/api/manager-requests"` | `submit_manager_request` |
| `POST` | `"/admin/api/manager-requests/{request_id}/approve"` | `approve_manager_request` |
| `POST` | `"/admin/api/manager-requests/{request_id}/reject"` | `reject_manager_request` |
| `DELETE` | `"/admin/api/managers/{username}"` | `remove_manager` |
| `GET` | `"/admin/api/managers/{username}/permissions"` | `get_manager_permissions` |
| `POST` | `"/admin/api/managers/{username}/permissions"` | `set_manager_permissions` |
| `GET` | `"/admin/api/admins/{user_id}/permissions"` | `get_admin_permissions` |
| `POST` | `"/admin/api/admins/{user_id}/permissions"` | `set_admin_permissions` |
| `POST` | `"/admin/api/features"` | `update_feature_settings` |
| `POST` | `"/admin/api/bot-state"` | `set_bot_state` |
| `POST` | `"/admin/api/broadcast"` | `broadcast` |
| `POST` | `"/admin/api/prompt"` | `update_prompt` |
| `GET` | `"/admin/api/payments"` | `admin_payments` |
| `POST` | `"/admin/api/payments/{payment_id}/{action}"` | `admin_payment_action` |
| `GET` | `"/admin/api/metrics"` | `admin_metrics` |
| `GET` | `"/health"` | `health` |
| `GET` | `"/ready"` | `readiness` |

### panel_auth.py (10 route)

| متد | مسیر | handler |
|---|---|---|
| `GET` | `"/owner", HTML` | `owner_panel` |
| `GET` | `"/owner/api/backup"` | `owner_database_backup` |
| `GET` | `"/admin/request", HTML` | `manager_access_request_page` |
| `GET` | `"/admin/login", HTML` | `manager_login_page` |
| `POST` | `"/auth/manager-request-code"` | `manager_request_code` |
| `POST` | `"/auth/manager-login"` | `manager_login` |
| `GET` | `"/login", HTML` | `panel_login` |
| `POST` | `"/auth/owner-request-code"` | `owner_request_code` |
| `POST` | `"/auth/owner-login"` | `owner_login` |
| `POST` | `"/auth/logout"` | `panel_logout` |

### group_owner.py (21 route)

| متد | مسیر | handler |
|---|---|---|
| `GET` | `"/group-owner", HTML` | `group_owner_login_page` |
| `GET` | `"/group-owner/panel", HTML` | `group_owner_panel` |
| `GET` | `"/group-owner/static/{asset}"` | `group_owner_static` |
| `POST` | `"/group-owner/api/request-code"` | `group_owner_request_code` |
| `POST` | `"/group-owner/api/login"` | `group_owner_login` |
| `POST` | `"/group-owner/api/logout"` | `group_owner_logout` |
| `GET` | `"/group-owner/api/overview"` | `group_owner_overview` |
| `GET` | `"/group-owner/api/messages"` | `group_owner_messages` |
| `GET` | `"/group-owner/api/members"` | `group_owner_members` |
| `POST` | `"/group-owner/api/settings"` | `group_owner_update_settings` |
| `POST` | `"/group-owner/api/messages/{message_id}/delete"` | `group_owner_delete_message` |
| `POST` | `"/group-owner/api/messages/{message_id}/edit"` | `group_owner_edit_bot_message` |
| `POST` | `"/group-owner/api/members/{user_id}/{action}"` | `group_owner_member_action` |
| `POST` | `"/group-owner/api/leave"` | `group_owner_remove_bot` |
| `GET` | `"/group-owner/api/add-link"` | `group_owner_add_link` |
| `POST` | `"/admin/api/community/inspect"` | `owner_inspect_community` |
| `GET` | `"/admin/api/community/{chat_id}/messages"` | `owner_panel_group_messages` |
| `POST` | `"/admin/api/community/{chat_id}/messages/{message_id}/delete"` | `owner_panel_delete_group_message` |
| `POST` | `"/admin/api/community/{chat_id}/messages/{message_id}/edit"` | `owner_panel_edit_group_message` |
| `POST` | `"/admin/api/community/{chat_id}/leave"` | `owner_panel_leave_group` |
| `GET` | `"/admin/api/community/{chat_id}/add-link"` | `owner_panel_group_add_link` |

## دروازه‌های انتشار نسخه نهایی

- [ ] همه routeهای بالا منتقل و contract test شده باشند.
- [ ] تست نقش مالک، مدیر با مجوز محدود، مدیر بدون مجوز، مدیر حذف‌شده و نشست منقضی اجرا شود.
- [ ] عملیات گروه در گروه آزمایشی با bot admin و بدون bot admin بررسی شود.
- [ ] پردازش پیام متنی، تصویر، پست کانال، edit/delete و update تکراری آزمایش شود.
- [ ] دیتابیس D1 با داده نمونه و تست مهاجرت رفت/برگشت بررسی شود؛ داده production بدون برنامه مهاجرت دست‌کاری نشود.
- [ ] بکاپ و restore در محیط جداگانه اجرا و checksum بررسی شود.
- [ ] همه دکمه‌های پنل به endpoint واقعی متصل باشند؛ هیچ کنترل نمایشی باقی نماند.
- [ ] secrets در Cloudflare staging تنظیم و تست شوند؛ مقادیر آن‌ها هرگز وارد Git نشوند.
- [ ] smoke test و مانیتورینگ staging موفق باشد.
- [ ] rollback به Worker قبلی و بازگردانی webhook مستند و آزمایش شود.
- [ ] فقط پس از همه موارد بالا cutover production انجام شود.

## نکته سازگاری

این مهاجرت یک بازنویسی رفتاری است، نه انتقال فایل‌به‌فایل. برنامه فعلی به Aiogram polling، FastAPI، PostgreSQL و taskهای طولانی‌عمر متکی است؛ Worker باید webhook-driven و D1-compatible باشد. تا تکمیل همه قراردادها، runtime فعلی production نباید جایگزین شود.
