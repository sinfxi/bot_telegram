const API = "https://api.telegram.org/bot";
const ADMIN_ID = "6384557276";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") {
      return new Response("Free Fire request bot is running.", { headers: { "content-type": "text/plain; charset=utf-8" } });
    }
    if (request.method !== "POST" || url.pathname !== "/telegram-webhook") {
      return new Response("Not found", { status: 404 });
    }
    if (env.WEBHOOK_SECRET && request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
      return new Response("Forbidden", { status: 403 });
    }
    if (!env.BOT_TOKEN || !env.DB) return new Response("Missing configuration", { status: 500 });
    let update;
    try { update = await request.json(); } catch { return new Response("Bad JSON", { status: 400 }); }
    try {
      if (update.message) await onMessage(update.message, env);
      if (update.callback_query) await onCallback(update.callback_query, env);
    } catch (err) {
      console.error("Update handler failed", err);
    }
    return new Response("OK");
  }
};

async function tg(env, method, body) {
  const r = await fetch(API + env.BOT_TOKEN + "/" + method, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!r.ok) console.error("Telegram API error", method, await r.text());
  return r;
}
async function say(env, chatId, text, extra = {}) {
  return tg(env, "sendMessage", { chat_id: chatId, text, ...extra });
}
function menu() {
  return { inline_keyboard: [
    [{ text: "🎮 ثبت درخواست لایک", callback_data: "new_request" }],
    [{ text: "📋 درخواست‌های من", callback_data: "my_requests" }],
    [{ text: "ℹ️ راهنما", callback_data: "help" }]
  ]};
}
async function onMessage(m, env) {
  const chatId = m.chat.id;
  const userId = String(m.from.id);
  const text = (m.text || "").trim();
  await env.DB.prepare("INSERT OR IGNORE INTO users (user_id, username, first_name, created_at) VALUES (?, ?, ?, ?)")
    .bind(userId, m.from.username || "", m.from.first_name || "", Date.now()).run();
  if (text.startsWith("/start")) {
    await env.DB.prepare("DELETE FROM sessions WHERE user_id = ?").bind(userId).run();
    return say(env, chatId, "سلام! 🎮\nبه ربات ثبت و پیگیری درخواست‌های Free Fire خوش اومدی.\n\nاز منوی زیر استفاده کن:", { reply_markup: menu() });
  }
  if (text.startsWith("/admin")) {
    if (userId !== ADMIN_ID) return say(env, chatId, "⛔️ دسترسی ندارید.");
    const row = await env.DB.prepare("SELECT COUNT(*) AS n FROM requests").first();
    const pending = await env.DB.prepare("SELECT COUNT(*) AS n FROM requests WHERE status = 'pending'").first();
    return say(env, chatId, "🛠 پنل مدیریت\nکل درخواست‌ها: " + row.n + "\nدر انتظار بررسی: " + pending.n, { reply_markup: { inline_keyboard: [[{ text: "📥 درخواست‌های در انتظار", callback_data: "admin_pending" }]] } });
  }
  const session = await env.DB.prepare("SELECT step FROM sessions WHERE user_id = ?").bind(userId).first();
  if (session?.step === "uid") {
    const match = text.match(/^([0-9]{5,20})\s*(?:\/|\s)\s*([a-zA-Z]{2,8})$/);
    if (!match) return say(env, chatId, "فرمت درست نیست. شناسه و منطقه را این‌طور بفرست:\n123456789 / ME");
    const result = await env.DB.prepare("INSERT INTO requests (user_id, game_uid, region, status, created_at) VALUES (?, ?, ?, 'pending', ?)")
      .bind(userId, match[1], match[2].toUpperCase(), Date.now()).run();
    await env.DB.prepare("DELETE FROM sessions WHERE user_id = ?").bind(userId).run();
    await say(env, chatId, "✅ درخواستت ثبت شد.\nشماره درخواست: " + result.meta.last_row_id + "\nوضعیت: در انتظار بررسی", { reply_markup: menu() });
    await say(env, ADMIN_ID, "📥 درخواست جدید #" + result.meta.last_row_id + "\nکاربر: " + userId + "\nUID: " + match[1] + "\nمنطقه: " + match[2].toUpperCase(), { reply_markup: { inline_keyboard: [[
      { text: "✅ تأیید", callback_data: "approve:" + result.meta.last_row_id },
      { text: "❌ رد", callback_data: "reject:" + result.meta.last_row_id }
    ]] } });
    return;
  }
  if (text.startsWith("/help")) return say(env, chatId, "برای ثبت درخواست، «ثبت درخواست لایک» را بزن و UID و منطقه را با قالب 123456789 / ME ارسال کن.\nاین نسخه درخواست را ثبت می‌کند؛ لایک خودکار فقط با API مجاز و معتبر قابل افزودن است.", { reply_markup: menu() });
  return say(env, chatId, "از دکمه‌های منو استفاده کن یا /start را بزن.", { reply_markup: menu() });
}
async function onCallback(q, env) {
  const userId = String(q.from.id);
  const chatId = q.message?.chat?.id || q.from.id;
  const data = q.data || "";
  await tg(env, "answerCallbackQuery", { callback_query_id: q.id });
  if (data === "new_request") {
    await env.DB.prepare("INSERT INTO sessions (user_id, step) VALUES (?, 'uid') ON CONFLICT(user_id) DO UPDATE SET step='uid'").bind(userId).run();
    return say(env, chatId, "لطفاً UID و منطقه‌ات را در یک پیام بفرست. مثال:\n123456789 / ME");
  }
  if (data === "help") return say(env, chatId, "UID و منطقه را با قالب 123456789 / ME بفرست. این ربات درخواست را مدیریت می‌کند و به‌تنهایی لایک واقعی ارسال نمی‌کند.");
  if (data === "my_requests") {
    const rows = await env.DB.prepare("SELECT id, game_uid, region, status FROM requests WHERE user_id = ? ORDER BY id DESC LIMIT 10").bind(userId).all();
    if (!rows.results.length) return say(env, chatId, "هنوز درخواستی ثبت نکردی.");
    const labels = { pending: "در انتظار بررسی", approved: "تأیید شده", rejected: "رد شده" };
    return say(env, chatId, "📋 آخرین درخواست‌ها:\n" + rows.results.map(r => "#" + r.id + " | " + r.game_uid + " (" + r.region + ") | " + (labels[r.status] || r.status)).join("\n"));
  }
  if (data === "admin_pending") {
    if (userId !== ADMIN_ID) return say(env, chatId, "⛔️ دسترسی ندارید.");
    const rows = await env.DB.prepare("SELECT id, user_id, game_uid, region FROM requests WHERE status='pending' ORDER BY id ASC LIMIT 15").all();
    if (!rows.results.length) return say(env, chatId, "درخواستی در انتظار بررسی نیست.");
    for (const r of rows.results) await say(env, chatId, "#" + r.id + " | کاربر " + r.user_id + "\nUID: " + r.game_uid + " | " + r.region, { reply_markup: { inline_keyboard: [[
      { text: "✅ تأیید", callback_data: "approve:" + r.id },
      { text: "❌ رد", callback_data: "reject:" + r.id }
    ]] } });
    return;
  }
  const action = data.match(/^(approve|reject):([0-9]+)$/);
  if (action) {
    if (userId !== ADMIN_ID) return say(env, chatId, "⛔️ دسترسی ندارید.");
    const status = action[1] === "approve" ? "approved" : "rejected";
    const row = await env.DB.prepare("SELECT user_id FROM requests WHERE id = ? AND status = 'pending'").bind(Number(action[2])).first();
    if (!row) return say(env, chatId, "این درخواست پیدا نشد یا قبلاً بررسی شده.");
    await env.DB.prepare("UPDATE requests SET status = ?, reviewed_at = ? WHERE id = ?").bind(status, Date.now(), Number(action[2])).run();
    await say(env, row.user_id, "وضعیت درخواست #" + action[2] + ": " + (status === "approved" ? "✅ تأیید شد" : "❌ رد شد"));
    return say(env, chatId, "درخواست #" + action[2] + " به‌روزرسانی شد.");
  }
}