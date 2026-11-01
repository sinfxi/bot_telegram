# FXI Community Manager

FXI is being shifted from a private AI-chat bot to a Telegram group/channel management assistant.

## Current implementation on the development branch

- Private `/start` now explains how to add FXI to a group or channel; private free-form messages no longer trigger AI chat replies.
- Community message capture stores chat title/type, message count, recently observed member identity, and a bounded sample of recent text.
- Conservative anti-flood protection removes repeated rapid messages in groups when the bot has delete-message permission. Group administrators are exempt.
- Reply-based `/ban`, `/mute [minutes]`, `/unmute`, and `/pin` commands are available to group administrators.
- Group rules: `/rules` and administrator-only `/setrules <text>`.
- Group activity summary: `/communitystats`.
- Administrator-only challenge publishing: `/challenge`.
- Administrator-only five-item idea list: `/suggest`.
- Reaction-count updates are recorded when Telegram delivers them; post records are ranked by total reactions.
- New-member welcome message is attempted when Telegram sends a chat-member update.
- Admin metrics expose observed communities, message counts, members seen, and tracked posts.

## Setup and Telegram permissions

1. Add the bot to the target group. Promote it to administrator and grant **Delete messages** for anti-flood moderation.
2. Add the bot to the target channel as administrator. Telegram channel post and reaction updates require appropriate channel access.
3. In BotFather, ensure group privacy settings are configured for the message visibility you intend. A bot with privacy mode enabled will not receive every ordinary group message; commands and replies are still subject to Telegram's rules.
4. The bot can only build its own history from updates received after it is added/configured. It cannot automatically download the group's old message history.
5. Reaction counts are only available for messages for which Telegram sends reaction-count updates. A bot cannot see private identities of people who reacted unless Telegram explicitly provides those details.

## Commands

| Command | Purpose |
|---|---|
| `/community` | Community feature guide |
| `/rules` | Show group rules |
| `/setrules <text>` | Change rules (group administrator only) |
| `/communitystats` | Show observed activity totals |
| `/ban` (reply) | Ban the replied-to member (administrator only) |
| `/mute [minutes]` (reply) | Restrict the replied-to member, default 60 minutes (administrator only) |
| `/unmute` (reply) | Restore sending permissions (administrator only) |
| `/pin` (reply) | Pin the replied-to message (administrator only) |
| `/challenge` | Publish a group challenge (administrator only) |
| `/suggest` | Produce five content/community ideas (administrator only) |

## Known limitations / next integration work

- The five suggestions currently use locally collected group activity and engagement records. The fifth item is a news-research prompt, **not** a live news result. A verified news/RSS provider must be connected before claiming real-time world-news recommendations.
- Reaction totals do not equal unique people or quality; the current ranking is a simple engagement signal.
- The current community state uses the existing bot-state persistence layer. For high-volume communities, move message/event history into dedicated PostgreSQL tables with retention and per-chat controls.
- Add configurable moderation thresholds, allowlists, warning/ban escalation, link policy, join-request review, polls, scheduled posts, and full dashboard workflows before calling this production-complete.
- Admin-only commands currently rely on Telegram group administrator status or configured FXI admin IDs.
- Do not enable automatic bans or mass deletions without explicit per-community policy and admin controls.


## قابلیت‌های اختصاصی کانال

- `/channelreport`: گزارش پست‌های ثبت‌شده، رتبه‌بندی تعامل و واژه‌های پرتکرار.
- `/topposts`: نمایش ۱۰ پست برتر بر اساس داده‌های واکنش، بازدید و فوروارد.
- `/contentplan`: ساخت برنامه پیشنهادی پنج‌پستی برای انتشار بعدی.
- ثبت متن پست، نوع رسانه، شناسه پیام و داده‌های قابل‌دسترسی بازدید/فوروارد؛ واکنش‌ها از رویدادهای شمارش واکنش تلگرام به‌روزرسانی می‌شوند.
- رتبه‌بندی از یک امتیاز شفاف استفاده می‌کند: واکنش‌ها وزن ۳، فوروارد وزن ۲ و بازدید وزن ۱ به ازای هر هزار بازدید (با سقف محاسباتی ۱۰۰ هزار).

**محدودیت‌های تحلیل:** ربات فقط از زمان اضافه‌شدن و فقط از رویدادهایی که تلگرام برای آن می‌فرستد داده دارد؛ تاریخچه قدیمی کانال را خودکار بازیابی نمی‌کند. تعداد مشترکان، نرخ تعامل دقیق، بهترین ساعت انتشار و خبرهای روز بدون داده/منبع مستقل قابل محاسبه یا تأیید نیستند. گزارش‌ها این موارد را حدس نمی‌زنند. برای دریافت پست‌ها و واکنش‌ها، ربات باید در کانال ادمین باشد و دسترسی‌های لازم را داشته باشد.


## پاسخ‌گویی طبیعی هوشمند در گروه

- `/fxi_enable`: فعال‌سازی پاسخ هوشمند برای گروه (فقط مدیر).
- `/fxi_disable`: خاموش‌کردن پاسخ هوشمند گروه (فقط مدیر).
- پس از فعال‌سازی، ربات فقط وقتی به نام کاربری‌اش اشاره شود یا عضوی به پیام خود ربات ریپلای بزند پاسخ می‌دهد؛ به تمام پیام‌های گروه جواب نمی‌دهد.
- برای کاهش مزاحمت، بین پاسخ‌های یک عضو در همان گروه حداقل ۸ ثانیه فاصله اعمال می‌شود.
- پاسخ‌ها از سرویس AI تنظیم‌شده و انتخاب‌شده برای همان عضو استفاده می‌کنند؛ تاریخچه هر گفت‌وگوی گروهی از گفت‌وگوهای خصوصی جدا نگه داشته می‌شود.
- `/draft <موضوع>`: ساخت پیش‌نویس فارسی برای انتشار؛ فقط مدیر مجاز است. پیش‌نویس به‌صورت خودکار در کانال منتشر نمی‌شود و باید توسط مدیر بازبینی شود.

**نکته حریم خصوصی:** با فعال‌سازی قابلیت هوشمند، متن پیام‌هایی که اعضا مستقیماً به ربات ارجاع می‌دهند برای پردازش به سرویس AI پیکربندی‌شده ارسال می‌شود. از ارسال اطلاعات حساس خودداری کنید.
