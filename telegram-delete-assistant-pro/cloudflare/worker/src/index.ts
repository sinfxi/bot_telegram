import { authorize, handleAuthRequest, permissionForPath } from "./auth";
import { handleOwnerManagerRequest } from "./managers";
import { handleCommunityUpdate } from "./community";

export interface Env {
  DB: D1Database;
  ASSETS: Fetcher;
  TELEGRAM_BOT_TOKEN?: string;
  TELEGRAM_WEBHOOK_SECRET?: string;
  OWNER_TELEGRAM_ID?: string;
  AUTH_PEPPER?: string;
  APP_ORIGIN?: string;
  APP_ENV?: string;
}
interface TelegramUpdate {
  update_id: number;
  message?: {
    message_id: number;
    text?: string;
    chat: { id: number; type: string };
    from?: { id: number; first_name?: string; username?: string };
  };
  channel_post?: {
    message_id: number;
    text?: string;
    chat: { id: number; type: string };
  };
}
const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
function equalBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}
async function secretMatches(provided: string, expected: string): Promise<boolean> {
  const encoder = new TextEncoder();
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  return equalBytes(new Uint8Array(a), new Uint8Array(b));
}
function classifyUpdate(update: TelegramUpdate): string {
  if (update.message) return "message";
  if (update.channel_post) return "channel_post";
  return "other";
}
async function sendTelegramMessage(token: string, chatId: number, text: string): Promise<void> {
  const response = await fetch("https://api.telegram.org/bot" + token + "/sendMessage", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
  if (!response.ok) throw new Error("telegram_send_failed_" + response.status);
}
async function handleUpdate(update: TelegramUpdate, env: Env): Promise<void> {
  if (await handleCommunityUpdate(update, env)) return;
  const message = update.message;
  if (!message || typeof message.text !== "string") return;
  const text = message.text.trim();
  if (text === "/start" || text.startsWith("/start ")) {
    if (!env.TELEGRAM_BOT_TOKEN) throw new Error("telegram_token_missing");
    await sendTelegramMessage(
      env.TELEGRAM_BOT_TOKEN,
      message.chat.id,
      "سلام! زیرساخت آزمایشی FXI پیام را دریافت کرد. قابلیت‌های مدیریتی در مراحل بعدی منتقل می‌شوند.",
    );
  }
}
async function telegramWebhook(request: Request, env: Env): Promise<Response> {
  const expected = env.TELEGRAM_WEBHOOK_SECRET;
  const provided = request.headers.get("x-telegram-bot-api-secret-token") ?? "";
  if (!expected || !provided || !(await secretMatches(provided, expected))) {
    return json({ ok: false, error: "unauthorized" }, 401);
  }
  let update: TelegramUpdate;
  try {
    const raw = await request.text();
    if (raw.length > 1024 * 1024) return json({ ok: false, error: "payload_too_large" }, 413);
    update = JSON.parse(raw) as TelegramUpdate;
  } catch {
    return json({ ok: false, error: "invalid_json" }, 400);
  }
  if (!Number.isSafeInteger(update?.update_id) || update.update_id < 0) {
    return json({ ok: false, error: "invalid_update_id" }, 400);
  }
  const inserted = await env.DB.prepare(
    "INSERT OR IGNORE INTO telegram_updates (update_id, update_type, payload_json, processing_status) VALUES (?, ?, ?, 'processing')",
  ).bind(update.update_id, classifyUpdate(update), JSON.stringify(update)).run();
  if ((inserted.meta?.changes ?? 0) === 0) return json({ ok: true, duplicate: true });
  try {
    await handleUpdate(update, env);
    await env.DB.prepare(
      "UPDATE telegram_updates SET processing_status = 'processed', processed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE update_id = ?",
    ).bind(update.update_id).run();
    return json({ ok: true });
  } catch (error) {
    const code = error instanceof Error ? error.message.slice(0, 80) : "processing_failed";
    await env.DB.prepare(
      "UPDATE telegram_updates SET processing_status = 'failed', last_error_code = ? WHERE update_id = ?",
    ).bind(code, update.update_id).run();
    return json({ ok: false, error: "processing_failed" }, 500);
  }
}
function sameOrigin(request: Request, env: Env): boolean {
  if (!env.APP_ORIGIN) return false;
  const origin = request.headers.get("origin");
  if (!origin) return false;
  try {
    return new URL(origin).origin === new URL(env.APP_ORIGIN).origin;
  } catch {
    return false;
  }
}
function isMutation(method: string): boolean {
  return !["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase());
}
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/auth/")) {
      const authResponse = await handleAuthRequest(request, env);
      if (authResponse) return authResponse;
    }
    if (request.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, service: "fxi-cloudflare-worker", environment: env.APP_ENV ?? "unknown" });
    }
    if (request.method === "GET" && url.pathname === "/ready") {
      try {
        const result = await env.DB.prepare("SELECT 1 AS ok").first<{ ok: number }>();
        return result?.ok === 1
          ? json({ ok: true, database: "connected" })
          : json({ ok: false, database: "unavailable" }, 503);
      } catch {
        return json({ ok: false, database: "unavailable" }, 503);
      }
    }
    if (url.pathname.startsWith("/admin/api/")) {
      if (isMutation(request.method) && !sameOrigin(request, env)) {
        return json({ detail: "درخواست مبدأ معتبر نیست." }, 403);
      }
      const required = permissionForPath(url.pathname);
      const result = await authorize(request, env, required === "__unmapped__" ? undefined : required);
      if (result.response) return result.response;
      if (result.actor?.role === "manager" && required === "__unmapped__") {
        return json({ detail: "این مسیر در سیاست دسترسی تعریف نشده است." }, 403);
      }
      return json({ detail: "این API هنوز در مرحله انتقال پیاده‌سازی نشده است." }, 501);
    }
    if (url.pathname.startsWith("/owner/api/")) {
      if (isMutation(request.method) && !sameOrigin(request, env)) {
        return json({ detail: "درخواست مبدأ معتبر نیست." }, 403);
      }
      const result = await authorize(request, env);
      if (result.response) return result.response;
      if (result.actor?.role !== "owner") return json({ detail: "فقط مالک اجازه این عملیات را دارد." }, 403);
      const managerResponse = await handleOwnerManagerRequest(request, env, result.actor);
      if (managerResponse) return managerResponse;
      return json({ detail: "این API هنوز در مرحله انتقال پیاده‌سازی نشده است." }, 501);
    }
    if (request.method === "POST" && url.pathname === "/telegram/webhook") {
      return telegramWebhook(request, env);
    }
    if (request.method === "GET" && ["/owner", "/owner/", "/owner/login"].includes(url.pathname)) {
      return env.ASSETS.fetch(new Request(new URL("/owner.html", request.url), request));
    }
    if (request.method === "GET" && ["/admin", "/admin/", "/admin/login"].includes(url.pathname)) {
      return env.ASSETS.fetch(new Request(new URL("/admin.html", request.url), request));
    }
    if (request.method === "GET" && url.pathname.startsWith("/owner/")) {
      return env.ASSETS.fetch(request);
    }
    return env.ASSETS.fetch(request);
  },
};
