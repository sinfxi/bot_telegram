import type { AuthActor, AuthEnv } from "./auth";

const PERMISSIONS = new Set([
  "dashboard", "providers", "users", "community", "conversations",
  "audit", "payments", "broadcast", "prompt", "system",
]);
const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), {
  status,
  headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store, private", "x-content-type-options": "nosniff" },
});
async function bodyJson(request: Request): Promise<Record<string, unknown> | null> {
  const raw = await request.text();
  if (raw.length > 8192) return null;
  try {
    const value = JSON.parse(raw);
    return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
  } catch { return null; }
}
function cleanUsername(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const username = value.trim().toLowerCase();
  return /^[a-z0-9_.-]{3,32}$/.test(username) ? username : null;
}
function cleanTelegramId(value: unknown): number | null {
  const id = typeof value === "string" ? Number(value) : value;
  return Number.isSafeInteger(id) && Number(id) > 0 ? Number(id) : null;
}
function cleanPin(value: unknown): string | null {
  const pin = String(value ?? "");
  return /^\d{4}$/.test(pin) ? pin : null;
}
function cleanPermissions(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length > PERMISSIONS.size) return null;
  const items = [...new Set(value.filter((v): v is string => typeof v === "string"))];
  if (items.length !== value.length || items.some((v) => !PERMISSIONS.has(v))) return null;
  if (!items.includes("dashboard")) items.push("dashboard");
  return items;
}
async function audit(env: AuthEnv, actor: AuthActor, action: string, targetId: string, details: unknown): Promise<void> {
  await env.DB.prepare(
    "INSERT INTO audit_log(actor_type, actor_id, action, target_type, target_id, details_json) VALUES ('owner', ?, ?, 'manager', ?, ?)",
  ).bind(actor.subjectId, action, targetId, JSON.stringify(details ?? {})).run();
}
async function hashPin(pin: string): Promise<string> {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(pin), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations: 210000 }, key, 256);
  const hex = (bytes: Uint8Array) => [...bytes].map((v) => v.toString(16).padStart(2, "0")).join("");
  return "pbkdf2-sha256$210000$" + hex(salt) + "$" + hex(new Uint8Array(bits));
}
async function replacePermissions(env: AuthEnv, managerId: number, permissions: string[]): Promise<void> {
  const statements = [
    env.DB.prepare("DELETE FROM manager_permissions WHERE manager_id = ?").bind(managerId),
    ...permissions.map((permission) => env.DB.prepare(
      "INSERT INTO manager_permissions(manager_id, permission_key) VALUES (?, ?)",
    ).bind(managerId, permission)),
  ];
  await env.DB.batch(statements);
}
async function listManagers(env: AuthEnv): Promise<Response> {
  const result = await env.DB.prepare(
    "SELECT id, username, telegram_user_id, is_active, session_version, failed_login_attempts, locked_until, created_at FROM managers ORDER BY id DESC LIMIT 200",
  ).all<{
    id:number; username:string; telegram_user_id:number|null; is_active:number;
    session_version:number; failed_login_attempts:number; locked_until:string|null; created_at:string;
  }>();
  const rows = result.results ?? [];
  const permissions = await env.DB.prepare(
    "SELECT manager_id, permission_key FROM manager_permissions ORDER BY manager_id, permission_key",
  ).all<{manager_id:number;permission_key:string}>();
  const byId = new Map<number,string[]>();
  for (const row of permissions.results ?? []) {
    const values = byId.get(row.manager_id) ?? [];
    if (PERMISSIONS.has(row.permission_key)) values.push(row.permission_key);
    byId.set(row.manager_id, values);
  }
  return json({ managers: rows.map((row) => ({
    ...row,
    is_active: row.is_active === 1,
    permissions: byId.get(row.id) ?? ["dashboard"],
  })) });
}
async function createManager(request: Request, env: AuthEnv, actor: AuthActor): Promise<Response> {
  const body = await bodyJson(request);
  const username = cleanUsername(body?.username);
  const telegramId = cleanTelegramId(body?.telegram_user_id);
  const pin = cleanPin(body?.password ?? body?.pin);
  const permissions = cleanPermissions(body?.permissions);
  if (!body || !username || !telegramId || !pin || !permissions) {
    return json({ detail: "نام کاربری، شناسه تلگرام، رمز چهاررقمی و فهرست مجوزهای معتبر الزامی است." }, 400);
  }
  const passwordHash = await hashPin(pin);
  try {
    const statements = [
      env.DB.prepare(
        "INSERT INTO managers(username, telegram_user_id, password_hash, is_active) VALUES (?, ?, ?, 1)",
      ).bind(username, telegramId, passwordHash),
      ...permissions.map((permission) => env.DB.prepare(
        "INSERT INTO manager_permissions(manager_id, permission_key) SELECT id, ? FROM managers WHERE username = ? COLLATE NOCASE",
      ).bind(permission, username)),
    ];
    await env.DB.batch(statements);
    const inserted = await env.DB.prepare("SELECT id FROM managers WHERE username = ? COLLATE NOCASE")
      .bind(username).first<{id:number}>();
    if (!inserted?.id) return json({ detail: "ساخت حساب مدیر انجام نشد." }, 500);
    await audit(env, actor, "manager_created", String(inserted.id), { username, telegram_user_id: telegramId, permissions });
    let notificationSent = false;
    if (env.TELEGRAM_BOT_TOKEN) {
      const message = "🎉 حساب مدیریت FXI برای شما ساخته شد.\nنام کاربری: " + username +
        "\nرمز اولیه: " + pin + "\nاین رمز چهاررقمی را فقط برای ورود پنل استفاده کن.";
      const response = await fetch("https://api.telegram.org/bot" + env.TELEGRAM_BOT_TOKEN + "/sendMessage", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ chat_id: telegramId, text: message }),
      }).catch(() => null);
      notificationSent = response?.ok === true;
    }
    return json({ ok: true, manager_id: inserted.id, notification_sent: notificationSent, message: "مدیر ساخته شد." }, 201);
  } catch (error) {
    const message = error instanceof Error ? error.message : "";
    if (message.includes("UNIQUE")) return json({ detail: "این نام کاربری یا شناسه تلگرام قبلاً ثبت شده است." }, 409);
    throw error;
  }
}
async function updateManager(request: Request, env: AuthEnv, actor: AuthActor, managerId: number): Promise<Response> {
  const body = await bodyJson(request);
  if (!body) return json({ detail: "بدنه درخواست معتبر نیست." }, 400);
  const current = await env.DB.prepare("SELECT id, username, telegram_user_id FROM managers WHERE id = ?")
    .bind(managerId).first<{id:number;username:string;telegram_user_id:number|null}>();
  if (!current) return json({ detail: "مدیر پیدا نشد." }, 404);
  const sets: string[] = [];
  const values: (string|number)[] = [];
  let changedPin: string | null = null;
  let username = current.username;
  let telegramId = current.telegram_user_id;
  if ("username" in body) {
    const value = cleanUsername(body.username);
    if (!value) return json({ detail: "نام کاربری معتبر نیست." }, 400);
    username = value; sets.push("username = ?"); values.push(value);
  }
  if ("telegram_user_id" in body) {
    const value = cleanTelegramId(body.telegram_user_id);
    if (!value) return json({ detail: "شناسه تلگرام معتبر نیست." }, 400);
    telegramId = value; sets.push("telegram_user_id = ?"); values.push(value);
  }
  if ("password" in body || "pin" in body) {
    const pin = cleanPin(body.password ?? body.pin);
    if (!pin) return json({ detail: "رمز باید دقیقاً چهار رقم باشد." }, 400);
    changedPin = pin;
    sets.push("password_hash = ?", "failed_login_attempts = 0", "locked_until = NULL", "session_version = session_version + 1");
    values.push(await hashPin(pin));
  }
  if ("is_active" in body) {
    if (typeof body.is_active !== "boolean") return json({ detail: "وضعیت مدیر معتبر نیست." }, 400);
    sets.push("is_active = ?", "session_version = session_version + 1");
    values.push(body.is_active ? 1 : 0);
  }
  const permissions = "permissions" in body ? cleanPermissions(body.permissions) : null;
  if ("permissions" in body && !permissions) return json({ detail: "فهرست دسترسی‌ها معتبر نیست." }, 400);
  if (sets.length) {
    try {
      await env.DB.prepare("UPDATE managers SET " + sets.join(", ") + " WHERE id = ?")
        .bind(...values, managerId).run();
    } catch (error) {
      if (String(error).includes("UNIQUE")) return json({ detail: "نام کاربری یا شناسه تلگرام تکراری است." }, 409);
      throw error;
    }
  }
  if (permissions) await replacePermissions(env, managerId, permissions);
  await audit(env, actor, "manager_updated", String(managerId), {
    username, telegram_user_id: telegramId,
    changed_fields: Object.keys(body).filter((k) => ["username","telegram_user_id","password","pin","is_active","permissions"].includes(k)),
  });
  let notificationSent: boolean | null = null;
  if (changedPin && telegramId && env.TELEGRAM_BOT_TOKEN) {
    const response = await fetch("https://api.telegram.org/bot" + env.TELEGRAM_BOT_TOKEN + "/sendMessage", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ chat_id: telegramId, text: "🔐 رمز ورود پنل FXI شما توسط مالک تغییر کرد.\\nنام کاربری: " + username + "\\nرمز جدید: " + changedPin }),
    }).catch(() => null);
    notificationSent = response?.ok === true;
  }
  return json({ ok: true, notification_sent: notificationSent, message: "اطلاعات مدیر به‌روزرسانی شد." });
}
async function revokeManager(env: AuthEnv, actor: AuthActor, managerId: number): Promise<Response> {
  const result = await env.DB.prepare(
    "UPDATE managers SET session_version = session_version + 1, failed_login_attempts = 0, locked_until = NULL WHERE id = ?",
  ).bind(managerId).run();
  if ((result.meta?.changes ?? 0) !== 1) return json({ detail: "مدیر پیدا نشد." }, 404);
  await env.DB.prepare(
    "UPDATE sessions SET revoked_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE subject_type = 'manager' AND subject_id = ? AND revoked_at IS NULL",
  ).bind(String(managerId)).run();
  await audit(env, actor, "manager_sessions_revoked", String(managerId), {});
  return json({ ok: true, message: "تمام نشست‌های این مدیر باطل شد." });
}
export async function handleOwnerManagerRequest(request: Request, env: AuthEnv, actor: AuthActor): Promise<Response | null> {
  const url = new URL(request.url);
  const path = url.pathname;
  if (path === "/owner/api/managers" && request.method === "GET") return listManagers(env);
  if (path === "/owner/api/managers" && request.method === "POST") return createManager(request, env, actor);
  const match = path.match(/^\/owner\/api\/managers\/(\d+)(?:\/(revoke))?$/);
  if (!match) return null;
  const managerId = Number(match[1]);
  if (!Number.isSafeInteger(managerId) || managerId <= 0) return json({ detail: "شناسه مدیر معتبر نیست." }, 400);
  if (match[2] === "revoke" && request.method === "POST") return revokeManager(env, actor, managerId);
  if (!match[2] && (request.method === "PATCH" || request.method === "PUT")) return updateManager(request, env, actor, managerId);
  return json({ detail: "روش درخواست پشتیبانی نمی‌شود." }, 405);
}
