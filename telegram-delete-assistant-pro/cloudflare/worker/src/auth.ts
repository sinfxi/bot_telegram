export interface AuthEnv {
  DB: D1Database;
  TELEGRAM_BOT_TOKEN?: string;
  OWNER_TELEGRAM_ID?: string;
  APP_ORIGIN?: string;
  AUTH_PEPPER?: string;
}

export interface AuthActor {
  role: "owner" | "manager";
  subjectId: string;
  username?: string;
  permissions: string[];
  sessionIdHash: string;
}

const COOKIE = "fxi_admin_session";
const SESSION_SECONDS = 60 * 60 * 24 * 7;
const OTP_SECONDS = 60;
const MANAGER_PERMISSIONS = new Set(["dashboard", "providers", "users", "community", "conversations", "audit", "payments", "broadcast", "prompt", "system"]);
const encoder = new TextEncoder();

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store, private",
      "pragma": "no-cache",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer",
    },
  });
}
function base64url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}
function randomToken(bytes = 32): string {
  const value = new Uint8Array(bytes);
  crypto.getRandomValues(value);
  return base64url(value);
}
async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(value));
  return [...new Uint8Array(digest)].map((v) => v.toString(16).padStart(2, "0")).join("");
}
async function codeDigest(subject: string, salt: string, code: string, pepper: string): Promise<string> {
  return sha256([pepper, subject, salt, code].join(":"));
}
function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
function cookieHeader(token: string, maxAge: number): string {
  return `${COOKIE}=${token}; Path=/; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=Strict`;
}
function clearCookie(): string {
  return `${COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict`;
}
function clientAddress(request: Request): string {
  return request.headers.get("cf-connecting-ip") ?? "unknown";
}
async function readJson<T>(request: Request): Promise<T | null> {
  const raw = await request.text();
  if (raw.length > 4096) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}
async function allowedOrigin(request: Request, env: AuthEnv): Promise<boolean> {
  if (!env.APP_ORIGIN) return false;
  const origin = request.headers.get("origin");
  if (!origin) return false;
  try {
    return new URL(origin).origin === new URL(env.APP_ORIGIN).origin;
  } catch {
    return false;
  }
}
async function rateLimit(request: Request, env: AuthEnv, action: string): Promise<boolean> {
  if (!env.AUTH_PEPPER) return false;
  const ipHash = await sha256(env.AUTH_PEPPER + ":" + clientAddress(request));
  const bucket = Math.floor(Date.now() / 60000);
  const key = await sha256(action + ":" + ipHash);
  await env.DB.prepare("DELETE FROM auth_rate_limits WHERE window_started_at < ?").bind(bucket - 1440).run();
  await env.DB.prepare(
    `INSERT INTO auth_rate_limits(bucket_key, window_started_at, attempt_count)
     VALUES (?, ?, 1)
     ON CONFLICT(bucket_key) DO UPDATE SET
       attempt_count = CASE WHEN window_started_at = excluded.window_started_at
         THEN attempt_count + 1 ELSE 1 END,
       window_started_at = excluded.window_started_at,
       updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`,
  ).bind(key, bucket).run();
  const row = await env.DB.prepare(
    "SELECT attempt_count FROM auth_rate_limits WHERE bucket_key = ?",
  ).bind(key).first<{ attempt_count: number }>();
  return (row?.attempt_count ?? 999) <= 5;
}
async function audit(env: AuthEnv, type: string, id: string, event: string, request: Request): Promise<void> {
  const ipHash = env.AUTH_PEPPER
    ? await sha256(env.AUTH_PEPPER + ":" + clientAddress(request))
    : null;
  await env.DB.prepare(
    "INSERT INTO auth_events(subject_type, subject_id, event_type, ip_hash) VALUES (?, ?, ?, ?)",
  ).bind(type, id, event, ipHash).run();
}
async function sendOtp(env: AuthEnv, telegramId: string, code: string, role: string): Promise<void> {
  if (!env.TELEGRAM_BOT_TOKEN) throw new Error("telegram_not_configured");
  const response = await fetch("https://api.telegram.org/bot" + env.TELEGRAM_BOT_TOKEN + "/sendMessage", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      chat_id: Number(telegramId),
      text: `🔐 کد ورود پنل ${role} FXI\n\n${code}\n\nاین کد فقط ۶۰ ثانیه معتبر است و یک‌بار مصرف است. آن را در اختیار هیچ‌کس نگذار.`,
    }),
  });
  if (!response.ok) throw new Error("telegram_delivery_failed");
}
async function createChallenge(
  env: AuthEnv, subjectType: "owner" | "manager", subjectId: string, telegramId: string,
): Promise<Response> {
  const pepper = env.AUTH_PEPPER;
  if (!pepper) return json({ detail: "پیکربندی امن ورود کامل نیست." }, 503);
  const challengeId = subjectType + ":" + subjectId;
  const old = await env.DB.prepare(
    "SELECT created_at FROM auth_challenges WHERE id = ? AND consumed_at IS NULL",
  ).bind(challengeId).first<{ created_at: string }>();
  if (old && Date.now() - Date.parse(old.created_at + (old.created_at.endsWith("Z") ? "" : "Z")) < 30000) {
    return json({ detail: "برای دریافت کد تازه ۳۰ ثانیه صبر کن." }, 429);
  }
  const code = String(crypto.getRandomValues(new Uint32Array(1))[0] % 1000000).padStart(6, "0");
  const salt = randomToken(16);
  const digest = await codeDigest(subjectType + ":" + subjectId, salt, code, pepper);
  await env.DB.prepare(
    `INSERT INTO auth_challenges(id, subject_type, subject_id, code_hash, expires_at, attempts, consumed_at)
     VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '+60 seconds'), 0, NULL)
     ON CONFLICT(id) DO UPDATE SET subject_type=excluded.subject_type,
       subject_id=excluded.subject_id, code_hash=excluded.code_hash,
       expires_at=excluded.expires_at, attempts=0, consumed_at=NULL,
       created_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`,
  ).bind(challengeId, subjectType, subjectId, salt + ":" + digest).run();
  try {
    await sendOtp(env, telegramId, code, subjectType === "owner" ? "مالک" : "مدیر");
  } catch {
    await env.DB.prepare("DELETE FROM auth_challenges WHERE id = ?").bind(challengeId).run();
    return json({ detail: "ارسال کد به تلگرام ممکن نشد؛ ابتدا ربات را Start کن." }, 503);
  }
  return json({ message: "کد ورود ارسال شد.", expires_in: OTP_SECONDS });
}
async function issueSession(
  env: AuthEnv, subjectType: "owner" | "manager", subjectId: string, version: number,
): Promise<{ token: string; tokenHash: string }> {
  const token = randomToken(32);
  const tokenHash = await sha256(token);
  await env.DB.prepare(
    "INSERT INTO sessions(session_id_hash, subject_type, subject_id, session_version, expires_at) VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '+7 days'))",
  ).bind(tokenHash, subjectType, subjectId, version).run();
  return { token, tokenHash };
}
async function verifyManagerPin(stored: string | null, pin: string): Promise<boolean> {
  if (!stored) return false;
  const parts = stored.split("$");
  if (parts.length !== 4 || parts[0] !== "pbkdf2-sha256") return false;
  const iterations = Number(parts[1]);
  const saltHex = parts[2];
  const expectedHex = parts[3];
  if (!Number.isInteger(iterations) || iterations < 100000 || iterations > 500000 ||
      !/^[a-f0-9]{32}$/.test(saltHex) || !/^[a-f0-9]{64}$/.test(expectedHex)) return false;
  const salt = new Uint8Array(saltHex.match(/.{2}/g)!.map((v) => parseInt(v, 16)));
  const key = await crypto.subtle.importKey("raw", encoder.encode(pin), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations }, key, 256);
  const actualHex = [...new Uint8Array(bits)].map((v) => v.toString(16).padStart(2, "0")).join("");
  return safeEqual(actualHex, expectedHex);
}
async function verifyOtp(
  env: AuthEnv, subjectType: "owner" | "manager", subjectId: string, code: string,
): Promise<boolean> {
  const challengeId = subjectType + ":" + subjectId;
  const challenge = await env.DB.prepare(
    "SELECT code_hash, expires_at, attempts FROM auth_challenges WHERE id = ? AND consumed_at IS NULL",
  ).bind(challengeId).first<{ code_hash: string; expires_at: string; attempts: number }>();
  if (!challenge || challenge.attempts >= 5 || Date.parse(challenge.expires_at + (challenge.expires_at.endsWith("Z") ? "" : "Z")) <= Date.now()) {
    return false;
  }
  const [salt, expected] = challenge.code_hash.split(":");
  const actual = await codeDigest(subjectType + ":" + subjectId, salt ?? "", code, env.AUTH_PEPPER ?? "");
  if (!safeEqual(actual, expected ?? "")) {
    await env.DB.prepare("UPDATE auth_challenges SET attempts = attempts + 1 WHERE id = ? AND consumed_at IS NULL").bind(challengeId).run();
    return false;
  }
  const consumed = await env.DB.prepare(
    "UPDATE auth_challenges SET consumed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ? AND consumed_at IS NULL AND attempts < 5 AND expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
  ).bind(challengeId).run();
  return (consumed.meta?.changes ?? 0) === 1;
}

export async function resolveSession(request: Request, env: AuthEnv): Promise<AuthActor | null> {
  const cookie = request.headers.get("cookie") ?? "";
  const match = cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith(COOKIE + "="));
  const token = match?.slice(COOKIE.length + 1) ?? "";
  if (!/^[A-Za-z0-9_-]{40,64}$/.test(token)) return null;
  const tokenHash = await sha256(token);
  const session = await env.DB.prepare(
    "SELECT subject_type, subject_id, session_version FROM sessions WHERE session_id_hash = ? AND revoked_at IS NULL AND expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
  ).bind(tokenHash).first<{ subject_type: string; subject_id: string; session_version: number }>();
  if (!session) return null;
  if (session.subject_type === "owner") {
    if (session.subject_id !== env.OWNER_TELEGRAM_ID) return null;
    const ownerState = await env.DB.prepare(
      "SELECT session_version FROM owner_auth_state WHERE owner_telegram_id = ?",
    ).bind(session.subject_id).first<{ session_version: number }>();
    if (!ownerState || ownerState.session_version !== session.session_version) return null;
    return { role: "owner", subjectId: session.subject_id, permissions: ["*"], sessionIdHash: tokenHash };
  }
  if (session.subject_type !== "manager") return null;
  const manager = await env.DB.prepare(
    "SELECT id, username, is_active, session_version FROM managers WHERE id = ?",
  ).bind(Number(session.subject_id)).first<{ id: number; username: string; is_active: number; session_version: number }>();
  if (!manager || manager.is_active !== 1 || manager.session_version !== session.session_version) return null;
  const rows = await env.DB.prepare(
    "SELECT permission_key FROM manager_permissions WHERE manager_id = ?",
  ).bind(manager.id).all<{ permission_key: string }>();
  const permissions = [...new Set((rows.results ?? []).map((row) => row.permission_key))]
    .filter((permission) => MANAGER_PERMISSIONS.has(permission));
  if (!permissions.includes("dashboard")) permissions.push("dashboard");
  return { role: "manager", subjectId: String(manager.id), username: manager.username, permissions, sessionIdHash: tokenHash };
}
export function permissionForPath(path: string): string {
  if (path === "/admin/api" || path === "/admin/api/" || path.endsWith("/status") || path.endsWith("/metrics")) return "dashboard";
  if (path.includes("/admins") || path.includes("/managers") || path.includes("/manager-")) return "admins";
  if (path.includes("/users/") || path.endsWith("/users")) return "users";
  if (path.includes("/community")) return "community";
  if (path.includes("/conversations")) return "conversations";
  if (path.includes("/audit")) return "audit";
  if (path.includes("/payments")) return "payments";
  if (path.includes("/broadcast")) return "broadcast";
  if (path.includes("/prompt")) return "prompt";
  if (path.includes("/providers")) return "providers";
  if (path.includes("/bot-state") || path.includes("/features")) return "system";
  return "__unmapped__";
}
export async function authorize(
  request: Request, env: AuthEnv, required?: string,
): Promise<{ actor: AuthActor | null; response?: Response }> {
  const actor = await resolveSession(request, env);
  if (!actor) return { actor: null, response: json({ detail: "نشست معتبر نیست؛ دوباره وارد شو." }, 401) };
  if (actor.role === "manager" && required && !actor.permissions.includes(required)) {
    return { actor, response: json({ detail: "این عملیات در سطح دسترسی فعلی مجاز نیست." }, 403) };
  }
  return { actor };
}

export async function handleAuthRequest(request: Request, env: AuthEnv): Promise<Response | null> {
  const url = new URL(request.url);
  if (!url.pathname.startsWith("/auth/")) return null;
  if (request.method === "POST" && !(await allowedOrigin(request, env))) {
    return json({ detail: "درخواست مبدأ معتبر نیست." }, 403);
  }
  if (request.method === "POST" && !(await rateLimit(request, env, url.pathname))) {
    return json({ detail: "تعداد درخواست‌ها زیاد است؛ یک دقیقه دیگر تلاش کن." }, 429);
  }
  if (request.method === "POST" && request.headers.get("content-type")?.split(";")[0] !== "application/json") {
    return json({ detail: "نوع محتوای درخواست باید JSON باشد." }, 415);
  }
  if (request.method === "POST" && url.pathname === "/auth/owner-request-code") {
    const ownerId = env.OWNER_TELEGRAM_ID ?? "";
    if (!/^\d{5,15}$/.test(ownerId)) return json({ detail: "شناسه مالک در تنظیمات Worker معتبر نیست." }, 503);
    return createChallenge(env, "owner", ownerId, ownerId);
  }
  if (request.method === "POST" && url.pathname === "/auth/owner-login") {
    const body = await readJson<{ code?: string }>(request);
    const code = String(body?.code ?? "");
    const ownerId = env.OWNER_TELEGRAM_ID ?? "";
    if (!/^\d{5,15}$/.test(ownerId) || !/^\d{6}$/.test(code) || !(await verifyOtp(env, "owner", ownerId, code))) {
      await audit(env, "owner", ownerId || "unknown", "login_failed", request);
      return json({ detail: "کد ورود معتبر نیست یا منقضی شده است." }, 401);
    }
    await env.DB.prepare("INSERT OR IGNORE INTO owner_auth_state(owner_telegram_id, session_version) VALUES (?, 1)").bind(ownerId).run();
    const ownerState = await env.DB.prepare("SELECT session_version FROM owner_auth_state WHERE owner_telegram_id = ?").bind(ownerId).first<{ session_version: number }>();
    const session = await issueSession(env, "owner", ownerId, ownerState?.session_version ?? 1);
    await audit(env, "owner", ownerId, "login_success", request);
    const response = json({ redirect: "/owner" });
    response.headers.append("set-cookie", cookieHeader(session.token, SESSION_SECONDS));
    return response;
  }
  if (request.method === "POST" && url.pathname === "/auth/manager-request-code") {
    return json({ detail: "ورود مدیر با نام کاربری و رمز چهاررقمی انجام می‌شود." }, 410);
  }
  if (request.method === "POST" && url.pathname === "/auth/manager-login") {
    const body = await readJson<{ username?: string; password?: string; pin?: string }>(request);
    const username = String(body?.username ?? "").trim().toLowerCase();
    const pin = String(body?.password ?? body?.pin ?? "");
    if (!/^[a-z0-9_.-]{3,32}$/.test(username) || !/^\d{4}$/.test(pin)) {
      return json({ detail: "نام کاربری یا رمز چهاررقمی معتبر نیست." }, 400);
    }
    const manager = await env.DB.prepare(
      "SELECT id, password_hash, is_active, session_version, failed_login_attempts, locked_until FROM managers WHERE username = ? COLLATE NOCASE",
    ).bind(username).first<{
      id: number; password_hash: string | null; is_active: number; session_version: number;
      failed_login_attempts: number; locked_until: string | null;
    }>();
    if (!manager || manager.is_active !== 1) {
      await audit(env, "manager", username, "login_failed", request);
      return json({ detail: "نام کاربری یا رمز ورود اشتباه است." }, 401);
    }
    if (manager.locked_until && Date.parse(manager.locked_until + (manager.locked_until.endsWith("Z") ? "" : "Z")) > Date.now()) {
      return json({ detail: "حساب موقتاً قفل شده است؛ کمی بعد دوباره تلاش کن." }, 423);
    }
    const valid = await verifyManagerPin(manager.password_hash, pin);
    if (!valid) {
      await env.DB.prepare(
        "UPDATE managers SET failed_login_attempts = CASE WHEN locked_until IS NOT NULL AND locked_until <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now') THEN 1 ELSE failed_login_attempts + 1 END, locked_until = CASE WHEN (CASE WHEN locked_until IS NOT NULL AND locked_until <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now') THEN 1 ELSE failed_login_attempts + 1 END) >= 5 THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '+15 minutes') ELSE NULL END WHERE id = ?",
      ).bind(manager.id).run();
      await audit(env, "manager", String(manager.id), "login_failed", request);
      return json({ detail: "نام کاربری یا رمز ورود اشتباه است." }, 401);
    }
    await env.DB.prepare("UPDATE managers SET failed_login_attempts = 0, locked_until = NULL WHERE id = ?")
      .bind(manager.id).run();
    const session = await issueSession(env, "manager", String(manager.id), manager.session_version);
    await audit(env, "manager", String(manager.id), "login_success", request);
    const response = json({ redirect: "/admin" });
    response.headers.append("set-cookie", cookieHeader(session.token, SESSION_SECONDS));
    return response;
  }
  if (request.method === "GET" && url.pathname === "/auth/me") {
    const actor = await resolveSession(request, env);
    if (!actor) return json({ authenticated: false }, 401);
    return json({ authenticated: true, role: actor.role, username: actor.username ?? null, permissions: actor.permissions });
  }
  if (request.method === "POST" && url.pathname === "/auth/logout") {
    const actor = await resolveSession(request, env);
    if (actor) {
      await env.DB.prepare("UPDATE sessions SET revoked_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE session_id_hash = ? AND revoked_at IS NULL")
        .bind(actor.sessionIdHash).run();
      await audit(env, actor.role, actor.subjectId, "logout", request);
    }
    const response = json({ ok: true, redirect: actor?.role === "manager" ? "/admin/login" : "/login" });
    response.headers.append("set-cookie", clearCookie());
    return response;
  }
  return json({ detail: "مسیر احراز هویت پیدا نشد." }, 404);
}
