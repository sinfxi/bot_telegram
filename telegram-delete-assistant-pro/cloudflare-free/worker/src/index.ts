export interface Env {
  DB: D1Database;
  TELEGRAM_WEBHOOK_SECRET: string;
}

interface TelegramUpdate {
  update_id: number;
  [key: string]: unknown;
}

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

function safeEqual(a: string, b: string): boolean {
  if (!a || !b) return false;
  const left = new TextEncoder().encode(a);
  const right = new TextEncoder().encode(b);
  if (left.length !== right.length) return false;
  let diff = 0;
  for (let i = 0; i < left.length; i++) diff |= left[i] ^ right[i];
  return diff === 0;
}

async function health(env: Env): Promise<Response> {
  try {
    await env.DB.prepare("SELECT 1 AS ok").first();
    return json({ ok: true, service: "fxi-telegram-edge-stage", database: "connected" });
  } catch {
    return json({ ok: false, service: "fxi-telegram-edge-stage", database: "unavailable" }, 503);
  }
}

async function readiness(env: Env): Promise<Response> {
  try {
    const migration = await env.DB.prepare(
      "SELECT 1 FROM schema_migrations WHERE version = ?",
    ).bind("0001").first();
    if (!migration) return json({ ok: false, reason: "schema_migration_missing" }, 503);
    return json({ ok: true, ready: true, schema: "0001", webhook_processing: "durable_ingest_only" });
  } catch {
    return json({ ok: false, ready: false, reason: "database_schema_unavailable" }, 503);
  }
}

async function receiveTelegramUpdate(request: Request, env: Env): Promise<Response> {
  const expected = env.TELEGRAM_WEBHOOK_SECRET ?? "";
  const supplied = request.headers.get("x-telegram-bot-api-secret-token") ?? "";
  if (!safeEqual(supplied, expected)) return json({ ok: false, error: "unauthorized" }, 401);

  const declaredLength = Number(request.headers.get("content-length") ?? "0");
  if (declaredLength > 1_000_000) return json({ ok: false, error: "payload_too_large" }, 413);

  let update: TelegramUpdate;
  try {
    const raw = await request.text();
    if (new TextEncoder().encode(raw).byteLength > 1_000_000) {
      return json({ ok: false, error: "payload_too_large" }, 413);
    }
    update = JSON.parse(raw) as TelegramUpdate;
  } catch {
    return json({ ok: false, error: "invalid_json" }, 400);
  }

  if (!Number.isSafeInteger(update.update_id) || update.update_id < 0) {
    return json({ ok: false, error: "invalid_update_id" }, 400);
  }

  try {
    await env.DB.prepare(
      `INSERT OR IGNORE INTO telegram_updates (update_id, payload_json, status)
       VALUES (?, ?, 'received')`,
    ).bind(update.update_id, JSON.stringify(update)).run();
    return json({ ok: true, accepted: true, update_id: update.update_id });
  } catch {
    // Telegram retries non-2xx responses; never acknowledge an update that was not persisted.
    return json({ ok: false, error: "temporary_storage_failure" }, 503);
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") return health(env);
    if (request.method === "GET" && url.pathname === "/ready") return readiness(env);
    if (request.method === "POST" && url.pathname === "/telegram/webhook") {
      return receiveTelegramUpdate(request, env);
    }
    if (request.method === "GET" && url.pathname === "/") {
      return json({ service: "FXI Telegram staging", status: "ingress-only" });
    }
    return json({ ok: false, error: "not_found" }, 404);
  },
};
