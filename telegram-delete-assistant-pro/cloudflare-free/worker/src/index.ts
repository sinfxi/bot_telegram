export interface Env { DB: D1Database; TELEGRAM_WEBHOOK_SECRET: string; }
interface TelegramUpdate { update_id: number; [key: string]: unknown; }
const MAX_WEBHOOK_BYTES = 1_000_000;
const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), {
  status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
});
function safeEqual(a: string, b: string): boolean {
  if (!a || !b) return false;
  const encoder = new TextEncoder(), left = encoder.encode(a), right = encoder.encode(b);
  if (left.length !== right.length) return false;
  let diff = 0; for (let i = 0; i < left.length; i++) diff |= left[i] ^ right[i];
  return diff === 0;
}
async function health(env: Env): Promise<Response> {
  try { await env.DB.prepare("SELECT 1 AS ok").first(); return json({ ok: true, service: "fxi-telegram-edge-staging", database: "connected" }); }
  catch { return json({ ok: false, service: "fxi-telegram-edge-staging", database: "unavailable" }, 503); }
}
async function readiness(env: Env): Promise<Response> {
  try {
    const checks = await Promise.all([
      env.DB.prepare("SELECT 1 FROM schema_migrations WHERE version = ?").bind("0001").first(),
      env.DB.prepare("SELECT 1 FROM telegram_updates LIMIT 1").first(),
    ]);
    if (!checks[0]) return json({ ok: false, reason: "schema_migration_missing" }, 503);
    return json({ ok: true, ready: true, schema: "0001", webhook_processing: "durable_ingest_only" });
  } catch { return json({ ok: false, ready: false, reason: "database_schema_unavailable" }, 503); }
}
async function readBoundedBody(request: Request): Promise<string | null> {
  const reader = request.body?.getReader();
  if (!reader) return "";
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_WEBHOOK_BYTES) {
        await reader.cancel();
        return null;
      }
      chunks.push(value);
    }
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } finally {
    reader.releaseLock();
  }
}
async function receiveTelegramUpdate(request: Request, env: Env): Promise<Response> {
  const suppliedSecret = request.headers.get("x-telegram-bot-api-secret-token") ?? "";
  if (!safeEqual(suppliedSecret, env.TELEGRAM_WEBHOOK_SECRET)) return json({ ok: false, error: "unauthorized" }, 401);
  const declaredLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(declaredLength) && declaredLength > MAX_WEBHOOK_BYTES) return json({ ok: false, error: "payload_too_large" }, 413);
  let raw: string;
  try {
    const body = await readBoundedBody(request);
    if (body === null) return json({ ok: false, error: "payload_too_large" }, 413);
    raw = body;
  } catch { return json({ ok: false, error: "invalid_body_encoding" }, 400); }
  let update: TelegramUpdate;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return json({ ok: false, error: "invalid_update" }, 400);
    update = parsed as TelegramUpdate;
  } catch { return json({ ok: false, error: "invalid_json" }, 400); }
  if (!Number.isSafeInteger(update.update_id) || update.update_id < 0) return json({ ok: false, error: "invalid_update_id" }, 400);
  try {
    // Telegram redelivery re-queues only updates previously marked failed.
    // Other states remain idempotent and cannot be reset by duplicate delivery.
    await env.DB.prepare(`INSERT INTO telegram_updates (update_id, payload_json, status)
      VALUES (?, ?, 'received')
      ON CONFLICT(update_id) DO UPDATE SET
        payload_json = excluded.payload_json,
        status = 'received',
        attempts = telegram_updates.attempts + 1,
        last_error = NULL
      WHERE telegram_updates.status = 'failed'`)
      .bind(update.update_id, JSON.stringify(update)).run();
    return json({ ok: true, accepted: true, update_id: update.update_id });
  } catch { return json({ ok: false, error: "temporary_storage_failure" }, 503); }
}
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") return health(env);
    if (request.method === "GET" && url.pathname === "/ready") return readiness(env);
    if (request.method === "POST" && url.pathname === "/telegram/webhook") return receiveTelegramUpdate(request, env);
    if (request.method === "GET" && url.pathname === "/") return json({ service: "FXI Telegram Edge Staging", status: "scaffold", endpoints: ["/health", "/ready"] });
    return json({ ok: false, error: "not_found" }, 404);
  },
};
