const JSON_HEADERS = { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" };
const MAX_HISTORY = 12;
const MAX_TEXT = 3500;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: JSON_HEADERS });
}
function cleanText(value, max = MAX_TEXT) {
  return String(value ?? "").replace(/\u0000/g, "").trim().slice(0, max);
}
function parseAdminIds(value) {
  return new Set(String(value ?? "").split(/[;,\s]+/).filter(Boolean));
}
async function telegram(env, method, payload = {}) {
  const token = env.ZEUS_BOT_TOKEN;
  if (!token) throw new Error("bot_token_missing");
  const response = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload)
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok !== true) throw new Error(`telegram_api_${method}_failed`);
  return data.result;
}
async function ensureSchema(db) {
  await db.batch([
    db.prepare(`CREATE TABLE IF NOT EXISTS fxi_js_updates (
      update_id INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'received',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, processed_at TEXT
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS fxi_js_history (
      chat_id TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','assistant')),
      content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    db.prepare(`CREATE INDEX IF NOT EXISTS idx_fxi_js_history_chat_time
      ON fxi_js_history(chat_id, created_at)`),
    db.prepare(`CREATE TABLE IF NOT EXISTS fxi_js_settings (
      key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`)
  ]);
}
async function saveHistory(db, chatId, role, content) {
  await db.prepare("INSERT INTO fxi_js_history(chat_id, role, content) VALUES(?,?,?)")
    .bind(String(chatId), role, cleanText(content, 4000)).run();
  await db.prepare(`DELETE FROM fxi_js_history WHERE chat_id = ? AND rowid NOT IN
    (SELECT rowid FROM fxi_js_history WHERE chat_id = ? ORDER BY rowid DESC LIMIT ?)`)
    .bind(String(chatId), String(chatId), MAX_HISTORY).run();
}
async function getHistory(db, chatId) {
  const result = await db.prepare("SELECT role, content FROM fxi_js_history WHERE chat_id=? ORDER BY rowid DESC LIMIT ?")
    .bind(String(chatId), MAX_HISTORY).all();
  return (result.results ?? []).reverse();
}
async function answerWithAI(env, history, userText, chatType) {
  if (!env.OPENROUTER_API_KEY) return "پیامت رو دریافت کردم؛ موتور هوش مصنوعی هنوز پیکربندی نشده.";
  const messages = [
    { role: "system", content: "تو دستیار فارسی‌زبان ربات تلگرام FXI هستی. طبیعی، دقیق، کوتاه و دوستانه پاسخ بده. در گروه فقط به موضوع پیام پاسخ بده و ادعای انجام کار انجام‌نشده نکن." },
    ...history,
    { role: "user", content: chatType === "private" ? userText : `پیام در گروه تلگرام: ${userText}` }
  ];
  const response = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: {
      "authorization": `Bearer ${env.OPENROUTER_API_KEY}`,
      "content-type": "application/json",
      "http-referer": "https://fxi-telegram-edge.fxi-media-engine.workers.dev",
      "x-title": "FXI Telegram Bot"
    },
    body: JSON.stringify({
      model: env.OPENROUTER_MODEL || "openrouter/auto",
      messages,
      temperature: 0.7,
      max_tokens: 500
    })
  });
  if (!response.ok) throw new Error("openrouter_request_failed");
  const data = await response.json();
  return cleanText(data.choices?.[0]?.message?.content || "الان نتونستم پاسخ مناسبی بسازم.", 3800);
}
async function handleMessage(update, env, db) {
  const message = update.message ?? update.edited_message ?? update.channel_post ?? update.edited_channel_post;
  if (!message?.chat || message.from?.is_bot) return;
  if (update.channel_post || update.edited_channel_post) {
    const channelText = cleanText(message.text ?? message.caption);
    if (channelText) {
      await db.prepare("CREATE TABLE IF NOT EXISTS fxi_js_channel_posts (chat_id TEXT NOT NULL, message_id INTEGER NOT NULL, content TEXT NOT NULL, posted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(chat_id,message_id))").run();
      await db.prepare("INSERT INTO fxi_js_channel_posts(chat_id,message_id,content) VALUES(?,?,?) ON CONFLICT(chat_id,message_id) DO UPDATE SET content=excluded.content").bind(String(message.chat.id), message.message_id, channelText).run();
    }
    return;
  }
  const text = cleanText(message.text ?? message.caption);
  if (!text) return;
  const chatId = message.chat.id;
  const chatType = message.chat.type;
  const botUsername = String(env.TELEGRAM_BOT_USERNAME || "The_fxi_bot").replace(/^@/, "").toLowerCase();
  const isCommand = text.startsWith("/");
  const addressed = chatType === "private" || text.toLowerCase().includes(`@${botUsername}`) ||
    message.reply_to_message?.from?.username?.toLowerCase() === botUsername;
  if (chatType !== "private" && !isCommand && !addressed) return;

  const command = text.split(/\s+/, 1)[0].split("@")[0].toLowerCase();
  if (command === "/start") {
    await telegram(env, "sendMessage", { chat_id: chatId, text: "سلام! 👋 من ربات FXI هستم. پیام بده تا کمکت کنم." , reply_to_message_id: message.message_id });
    return;
  }
  if (command === "/help") {
    await telegram(env, "sendMessage", { chat_id: chatId, text: "برای گفتگو در خصوصی پیام بده؛ در گروه من را با @The_fxi_bot صدا بزن یا به پیامم پاسخ بده." });
    return;
  }
  if (command === "/status") {
    if (!parseAdminIds(env.ADMIN_IDS).has(String(message.from.id))) return;
    await telegram(env, "sendMessage", { chat_id: chatId, text: "FXI Edge فعال است؛ ذخیره‌سازی D1 متصل است." });
    return;
  }

  const prompt = text.replace(new RegExp(`@?${botUsername}`, "ig"), "").trim() || text;
  const history = await getHistory(db, chatId);
  await saveHistory(db, chatId, "user", prompt);
  try {
    const answer = await answerWithAI(env, history, prompt, chatType);
    await telegram(env, "sendMessage", {
      chat_id: chatId, text: answer,
      reply_to_message_id: message.message_id,
      allow_sending_without_reply: true
    });
    await saveHistory(db, chatId, "assistant", answer);
  } catch (error) {
    console.error("message_handler_failed", String(error));
    await telegram(env, "sendMessage", {
      chat_id: chatId, text: "الان در پردازش پیام مشکلی پیش اومد؛ کمی بعد دوباره امتحان کن.",
      reply_to_message_id: message.message_id,
      allow_sending_without_reply: true
    }).catch(() => {});
    throw error;
  }
}
async function handleUpdate(update, env, db) {
  await handleMessage(update, env, db);
}
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") {
      return json({ service: "FXI Telegram Edge", runtime: "Cloudflare Workers JavaScript", status: "running" });
    }
    if (request.method === "GET" && url.pathname === "/health") {
      try {
        await env.DB.prepare("SELECT 1").first();
        return json({ ok: true, worker: "running", database: "connected" });
      } catch {
        return json({ ok: false, worker: "running", database: "unavailable" }, 503);
      }
    }
    if (request.method === "GET" && url.pathname === "/ready") {
      try {
        if (!env.ZEUS_BOT_TOKEN || !env.TELEGRAM_WEBHOOK_SECRET) throw new Error("telegram_secrets_missing");
        await env.DB.prepare("SELECT 1").first();
        const me = await telegram(env, "getMe");
        const info = await telegram(env, "getWebhookInfo");
        const expectedUrl = new URL("/telegram/webhook", url.origin).toString();
        return json({ ready: true, telegram: "authenticated", bot_username: me.username || null, webhook: info.url === expectedUrl ? "configured" : "not_configured", pending_updates: info.pending_update_count ?? null, database: "connected", ai_configured: Boolean(env.OPENROUTER_API_KEY) });
      } catch (error) {
        console.error("readiness_failed", String(error));
        return json({ ready: false, reason: String(error).includes("telegram_secrets_missing") ? "telegram_secrets_missing" : "telegram_or_database_unavailable" }, 503);
      }
    }
    if (request.method === "POST" && url.pathname === "/admin/register-webhook") {
      const expected = env.ADMIN_PANEL_PASSWORD || "";
      if (!expected || request.headers.get("authorization") !== "Bearer " + expected) return json({ ok: false }, 401);
      try {
        await ensureSchema(env.DB);
        const me = await telegram(env, "getMe");
        const webhookUrl = new URL("/telegram/webhook", url.origin).toString();
        await telegram(env, "setWebhook", { url: webhookUrl, secret_token: env.TELEGRAM_WEBHOOK_SECRET, allowed_updates: ["message", "edited_message", "channel_post", "edited_channel_post"], drop_pending_updates: false });
        return json({ ok: true, bot_username: me.username || null, webhook: "configured" });
      } catch (error) {
        console.error("webhook_registration_failed", String(error));
        return json({ ok: false, error: "registration_failed" }, 503);
      }
    }
    if (request.method === "POST" && url.pathname === "/telegram/webhook") {
      const expected = env.TELEGRAM_WEBHOOK_SECRET || "";
      const supplied = request.headers.get("x-telegram-bot-api-secret-token") || "";
      if (!expected || supplied.length !== expected.length ||
          !crypto.subtle || !await timingSafeEqual(supplied, expected)) return json({ ok: false }, 401);
      let update;
      try { update = await request.json(); } catch { return json({ error: "invalid_json" }, 400); }
      if (!Number.isSafeInteger(update?.update_id) || update.update_id < 0) return json({ error: "invalid_update_id" }, 400);
      await ensureSchema(env.DB);
      const inserted = await env.DB.prepare("INSERT OR IGNORE INTO fxi_js_updates(update_id) VALUES(?)")
        .bind(update.update_id).run();
      if (inserted.meta?.changes === 0) return json({ ok: true, duplicate: true });
      try {
        await handleUpdate(update, env, env.DB);
        await env.DB.prepare("UPDATE fxi_js_updates SET status='processed', processed_at=CURRENT_TIMESTAMP WHERE update_id=?")
          .bind(update.update_id).run();
        return json({ ok: true, processed: true });
      } catch {
        await env.DB.prepare("UPDATE fxi_js_updates SET status='failed' WHERE update_id=?")
          .bind(update.update_id).run();
        return json({ ok: false, error: "processing_failed" }, 500);
      }
    }
    return json({ error: "not_found" }, 404);
  }
};
async function timingSafeEqual(a, b) {
  const enc = new TextEncoder();
  const digestA = await crypto.subtle.digest("SHA-256", enc.encode(a));
  const digestB = await crypto.subtle.digest("SHA-256", enc.encode(b));
  const x = new Uint8Array(digestA), y = new Uint8Array(digestB);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}
