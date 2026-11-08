import type { Env } from "./index";

type TgUser = { id: number; first_name?: string; last_name?: string; username?: string; is_bot?: boolean };
type TgChat = { id: number; type: string; title?: string };
type TgMessage = {
  message_id: number; date?: number; text?: string; caption?: string; chat: TgChat;
  from?: TgUser; reply_to_message?: TgMessage; new_chat_members?: TgUser[];
  left_chat_member?: TgUser; entities?: Array<{ type: string; offset: number; length: number }>;
  photo?: unknown[]; video?: unknown; document?: unknown; audio?: unknown; voice?: unknown;
  sticker?: unknown; animation?: unknown; contact?: unknown; location?: unknown;
  new_chat_title?: string;
};
type Update = {
  message?: TgMessage; edited_message?: TgMessage; channel_post?: TgMessage;
  edited_channel_post?: TgMessage;
  chat_member?: { chat: TgChat; old_chat_member: { status: string }; new_chat_member: { status: string; user: TgUser } };
};
type Settings = {
  bot_enabled: boolean; welcome_enabled: boolean; anti_flood_enabled: boolean;
  link_guard_enabled: boolean; keyword_filter_enabled: boolean; media_guard_enabled: boolean;
  flood_limit: number; warn_limit: number;
};
const DEFAULT_SETTINGS: Settings = {
  bot_enabled: true, welcome_enabled: true, anti_flood_enabled: true,
  link_guard_enabled: false, keyword_filter_enabled: false, media_guard_enabled: false,
  flood_limit: 7, warn_limit: 3,
};
const encoder = new TextEncoder();
const normalize = (value: string) => value.toLowerCase().replace(/‌/g, " ").replace(/[،؛.!؟?]+/g, " ").replace(/\s+/g, " ").trim();
function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
async function telegram(env: Env, method: string, payload: Record<string, unknown>): Promise<any> {
  if (!env.TELEGRAM_BOT_TOKEN) throw new Error("telegram_token_missing");
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
  });
  const data = await response.json() as { ok?: boolean; description?: string; result?: any };
  if (!response.ok || !data.ok) throw new Error(`telegram_${method}_failed`);
  return data.result;
}
async function send(env: Env, chatId: number, text: string, replyTo?: number): Promise<void> {
  await telegram(env, "sendMessage", {
    chat_id: chatId, text: text.slice(0, 4000),
    ...(replyTo ? { reply_to_message_id: replyTo, allow_sending_without_reply: true } : {}),
  });
}
async function isChatAdmin(env: Env, chatId: number, userId: number): Promise<boolean> {
  try {
    const member = await telegram(env, "getChatMember", { chat_id: chatId, user_id: userId });
    return member.status === "creator" || member.status === "administrator";
  } catch { return false; }
}
async function getSettings(env: Env, chat: TgChat): Promise<{ settings: Settings; rules: string }> {
  const row = await env.DB.prepare(
    "SELECT settings_json, rules_text FROM community_chat_settings WHERE chat_id = ?",
  ).bind(chat.id).first<{ settings_json: string; rules_text: string }>();
  let stored: Partial<Settings> = {};
  try { stored = row ? JSON.parse(row.settings_json) as Partial<Settings> : {}; } catch { stored = {}; }
  const settings = { ...DEFAULT_SETTINGS, ...stored };
  await env.DB.prepare(
    `INSERT INTO community_chat_settings(chat_id, chat_type, title, settings_json)
     VALUES (?, ?, ?, ?)
     ON CONFLICT(chat_id) DO UPDATE SET chat_type=excluded.chat_type, title=excluded.title`,
  ).bind(chat.id, chat.type, chat.title ?? "", JSON.stringify(settings)).run();
  return { settings, rules: row?.rules_text ?? "به اعضا احترام بگذارید؛ از اسپم و تبلیغات ناخواسته خودداری کنید." };
}
async function saveSettings(env: Env, chat: TgChat, settings: Settings, rules?: string): Promise<void> {
  await env.DB.prepare(
    `INSERT INTO community_chat_settings(chat_id, chat_type, title, settings_json, rules_text)
     VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(chat_id) DO UPDATE SET settings_json=excluded.settings_json,
       rules_text=COALESCE(?, community_chat_settings.rules_text),
       updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`,
  ).bind(chat.id, chat.type, chat.title ?? "", JSON.stringify(settings),
    rules ?? "به اعضا احترام بگذارید؛ از اسپم و تبلیغات ناخواسته خودداری کنید.", rules ?? null).run();
}
async function archive(env: Env, message: TgMessage): Promise<void> {
  const body = (message.text ?? message.caption ?? "").slice(0, 4000);
  await env.DB.prepare(
    `INSERT INTO community_messages(chat_id, message_id, sender_id, sender_name, message_text, created_at)
     VALUES (?, ?, ?, ?, ?, ?)
     ON CONFLICT(chat_id, message_id) DO UPDATE SET message_text=excluded.message_text, edited_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`,
  ).bind(message.chat.id, message.message_id, message.from?.id ?? null,
    [message.from?.first_name, message.from?.last_name].filter(Boolean).join(" ") || "Channel",
    body, message.date ? new Date(message.date * 1000).toISOString() : new Date().toISOString()).run();
}
function intent(text: string): string | null {
  const v = normalize(text);
  if (["پین", "سنجاق", "سنجاق کن", "این پیام رو پین کن", "این پیام را سنجاق کن"].includes(v)) return "pin";
  if (["آنپین", "آنبین", "برداشتن پین", "لغو سنجاق", "پین رو بردار", "سنجاق رو بردار"].includes(v)) return "unpin";
  if (["حذف", "پاک کن", "حذف پیام", "این پیام رو حذف کن", "این پیام را پاک کن"].includes(v)) return "delete";
  if (v === "بن" || v === "مسدود کن" || v === "اخراج کن") return "ban";
  if (v === "آنبن" || v === "رفع بن" || v === "رفع مسدودی") return "unban";
  if (v === "آزاد" || v === "رفع سکوت" || v === "آنمیوت") return "unmute";
  if (/^(سکوت|میوت|محدود کن|ساکت کن)/.test(v)) return "mute";
  if (v === "تنظیمات" || v === "تنظیمات گروه") return "settings";
  if (v === "قوانین" || v === "قوانین گروه") return "rules";
  if (/^(ثبت قوانین|قوانین جدید|تغییر قوانین)/.test(v)) return "set_rules";
  if (/^(فیلتر کلمه|افزودن کلمه ممنوع) /.test(v)) return "add_word";
  if (/^(حذف فیلتر|برداشتن فیلتر) /.test(v)) return "remove_word";
  if (v === "آمار گروه" || v === "آمار کانال" || v === "وضعیت گروه") return "stats";
  if (v === "راهنما" || v === "کمک") return "help";
  return null;
}
async function processCommand(env: Env, message: TgMessage, text: string, settings: Settings, rules: string): Promise<boolean> {
  const action = intent(text);
  if (!action) return false;
  const user = message.from;
  if (!user || user.is_bot) return false;
  const privileged = new Set(["pin","unpin","delete","ban","unban","mute","unmute","settings","set_rules","add_word","remove_word"]);
  if (privileged.has(action) && !(await isChatAdmin(env, message.chat.id, user.id))) {
    await send(env, message.chat.id, "⛔ این عملیات فقط برای مدیران همین گروه/کانال مجاز است.", message.message_id);
    return true;
  }
  if (action === "help") {
    await send(env, message.chat.id, "برای مدیریت پیام روی آن ریپلای کن و بنویس «پین»، «آنپین»، «حذف»، «سکوت ۱۰ دقیقه»، «آزاد» یا «بن». برای تنظیمات، قوانین و آمار هم همین عبارت‌ها را بفرست.", message.message_id);
    return true;
  }
  if (action === "rules") { await send(env, message.chat.id, "📜 قوانین:\n" + rules, message.message_id); return true; }
  if (action === "stats") {
    const row = await env.DB.prepare("SELECT COUNT(*) AS total FROM community_messages WHERE chat_id = ?").bind(message.chat.id).first<{ total: number }>();
    await send(env, message.chat.id, `📊 تعداد پیام‌های ثبت‌شده: ${row?.total ?? 0}`, message.message_id);
    return true;
  }
  if (action === "settings") {
    await send(env, message.chat.id, `⚙️ تنظیمات فعلی\nخوشامدگویی: ${settings.welcome_enabled ? "روشن" : "خاموش"}\nضداسپم: ${settings.anti_flood_enabled ? "روشن" : "خاموش"}\nکنترل لینک: ${settings.link_guard_enabled ? "روشن" : "خاموش"}\nفیلتر واژه: ${settings.keyword_filter_enabled ? "روشن" : "خاموش"}`, message.message_id);
    return true;
  }
  if (action === "set_rules") {
    const value = text.replace(/^(ثبت قوانین|قوانین جدید|تغییر قوانین)\s*[:：-]?\s*/i, "").trim();
    if (!value || value.length > 3000) { await send(env, message.chat.id, "متن قوانین را بعد از «ثبت قوانین» بنویس.", message.message_id); return true; }
    await saveSettings(env, message.chat, settings, value);
    await send(env, message.chat.id, "✅ قوانین ذخیره شد.", message.message_id); return true;
  }
  if (action === "add_word" || action === "remove_word") {
    const word = text.replace(/^(فیلتر کلمه|افزودن کلمه ممنوع|حذف فیلتر|برداشتن فیلتر)\s*/i, "").trim().toLowerCase();
    if (!word || word.length > 60 || /\s/.test(word)) { await send(env, message.chat.id, "یک واژه کوتاه و بدون فاصله وارد کن.", message.message_id); return true; }
    if (action === "add_word") {
      await env.DB.prepare("INSERT OR IGNORE INTO community_blocked_words(chat_id, word, created_by) VALUES (?, ?, ?)").bind(message.chat.id, word, user.id).run();
      settings.keyword_filter_enabled = true;
    } else {
      await env.DB.prepare("DELETE FROM community_blocked_words WHERE chat_id = ? AND word = ?").bind(message.chat.id, word).run();
    }
    await saveSettings(env, message.chat, settings);
    await send(env, message.chat.id, action === "add_word" ? `🚫 واژه «${word}» به فیلتر اضافه شد.` : `واژه «${word}» از فیلتر حذف شد.`, message.message_id);
    return true;
  }
  const target = message.reply_to_message;
  if (!target && action !== "unpin") {
    await send(env, message.chat.id, "برای این عملیات روی پیام موردنظر ریپلای کن.", message.message_id);
    return true;
  }
  try {
    if (action === "pin") await telegram(env, "pinChatMessage", { chat_id: message.chat.id, message_id: target!.message_id, disable_notification: true });
    else if (action === "unpin") await telegram(env, "unpinChatMessage", { chat_id: message.chat.id, ...(target ? { message_id: target.message_id } : {}) });
    else if (action === "delete") await telegram(env, "deleteMessage", { chat_id: message.chat.id, message_id: target!.message_id });
    else {
      const targetUser = target?.from;
      if (!targetUser || targetUser.is_bot) { await send(env, message.chat.id, "روی پیام یک عضو واقعی ریپلای کن.", message.message_id); return true; }
      if (await isChatAdmin(env, message.chat.id, targetUser.id)) { await send(env, message.chat.id, "این عملیات روی مدیران گروه اجرا نمی‌شود.", message.message_id); return true; }
      if (action === "ban") await telegram(env, "banChatMember", { chat_id: message.chat.id, user_id: targetUser.id });
      if (action === "unban") await telegram(env, "unbanChatMember", { chat_id: message.chat.id, user_id: targetUser.id, only_if_banned: true });
      if (action === "mute" || action === "unmute") {
        const digits = text.replace(/[۰-۹٠-٩]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩".indexOf(d) % 10));
        const duration = Math.max(1, Math.min(10080, Number(digits.match(/\d{1,5}/)?.[0] ?? 60)));
        await telegram(env, "restrictChatMember", {
          chat_id: message.chat.id, user_id: targetUser.id,
          permissions: action === "mute" ? { can_send_messages: false } : {
            can_send_messages: true, can_send_audios: true, can_send_documents: true,
            can_send_photos: true, can_send_videos: true, can_send_video_notes: true,
            can_send_voice_notes: true, can_send_polls: true, can_send_other_messages: true,
            can_add_web_page_previews: true,
          },
          ...(action === "mute" ? { until_date: Math.floor(Date.now() / 1000) + duration * 60 } : {}),
        });
      }
    }
    await send(env, message.chat.id, ({ pin:"📌 پیام سنجاق شد.", unpin:"📍 سنجاق برداشته شد.", delete:"🗑 پیام حذف شد.", ban:"⛔ عضو مسدود شد.", unban:"✅ مسدودیت برداشته شد.", mute:"🔇 عضو محدود شد.", unmute:"🔊 محدودیت برداشته شد." } as Record<string,string>)[action] ?? "انجام شد.", message.message_id);
  } catch {
    await send(env, message.chat.id, "عملیات انجام نشد؛ دسترسی مدیریتی ربات در همین گروه/کانال را بررسی کن.", message.message_id);
  }
  return true;
}
async function processMessage(env: Env, message: TgMessage, edited = false): Promise<void> {
  const chat = message.chat;
  if (!["group", "supergroup", "channel"].includes(chat.type)) return;
  const { settings, rules } = await getSettings(env, chat);
  await archive(env, message);
  const text = message.text ?? message.caption ?? "";
  if (chat.type === "channel" || !message.from || message.from.is_bot || !settings.bot_enabled) return;
  const admin = await isChatAdmin(env, chat.id, message.from.id);
  if (!admin) {
    if (settings.media_guard_enabled && (message.photo || message.video || message.document || message.audio || message.voice || message.animation)) {
      try { await telegram(env, "deleteMessage", { chat_id: chat.id, message_id: message.message_id }); } catch {}
      return;
    }
    if (settings.link_guard_enabled && /(?:https?:\/\/|t\.me\/|telegram\.me\/|www\.)/i.test(text)) {
      try { await telegram(env, "deleteMessage", { chat_id: chat.id, message_id: message.message_id }); } catch {}
      return;
    }
    if (settings.keyword_filter_enabled) {
      const rows = await env.DB.prepare("SELECT word FROM community_blocked_words WHERE chat_id = ?").bind(chat.id).all<{ word: string }>();
      const lowered = text.toLowerCase();
      if ((rows.results ?? []).some((row) => row.word && lowered.includes(row.word.toLowerCase()))) {
        try { await telegram(env, "deleteMessage", { chat_id: chat.id, message_id: message.message_id }); } catch {}
        return;
      }
    }
    if (settings.anti_flood_enabled && !edited) {
      await env.DB.prepare("INSERT INTO community_flood_events(chat_id, user_id) VALUES (?, ?)").bind(chat.id, message.from.id).run();
      const count = await env.DB.prepare(
        "SELECT COUNT(*) AS total FROM community_flood_events WHERE chat_id = ? AND user_id = ? AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-30 seconds')",
      ).bind(chat.id, message.from.id).first<{ total: number }>();
      await env.DB.prepare("DELETE FROM community_flood_events WHERE created_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-2 minutes')").run();
      if ((count?.total ?? 0) > Math.max(3, Math.min(20, settings.flood_limit))) {
        try {
          await telegram(env, "deleteMessage", { chat_id: chat.id, message_id: message.message_id });
          await telegram(env, "restrictChatMember", { chat_id: chat.id, user_id: message.from.id, permissions: { can_send_messages: false }, until_date: Math.floor(Date.now()/1000) + 60 });
        } catch {}
        return;
      }
    }
  }
  if (!edited && await processCommand(env, message, text, settings, rules)) return;
}
async function processMemberUpdate(env: Env, update: NonNullable<Update["chat_member"]>): Promise<void> {
  const { settings } = await getSettings(env, update.chat);
  const oldStatus = update.old_chat_member.status;
  const newStatus = update.new_chat_member.status;
  if (["left", "kicked"].includes(oldStatus) && ["member", "restricted", "administrator"].includes(newStatus)
      && settings.bot_enabled && settings.welcome_enabled) {
    const name = [update.new_chat_member.user.first_name, update.new_chat_member.user.last_name].filter(Boolean).join(" ") || "دوست";
    await send(env, update.chat.id, `👋 خوش اومدی ${name} به ${update.chat.title ?? "گروه"}! قوانین گروه رو با نوشتن «قوانین» بخون.`);
  }
}
export async function handleCommunityUpdate(update: Update, env: Env): Promise<boolean> {
  if (update.chat_member) {
    try { await processMemberUpdate(env, update.chat_member); } catch {}
    return true;
  }
  const message = update.message ?? update.edited_message ?? update.channel_post ?? update.edited_channel_post;
  if (!message || !["group", "supergroup", "channel"].includes(message.chat.type)) return false;
  await processMessage(env, message, Boolean(update.edited_message || update.edited_channel_post));
  return true;
}
