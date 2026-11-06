"""Owner and manager authentication using Telegram one-time codes."""
import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import time
import secrets
from datetime import datetime, timezone
from collections import defaultdict

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.background import BackgroundTask
from itsdangerous import URLSafeTimedSerializer


def install_panel_auth(app, bot):
    secret = os.getenv("SESSION_SECRET", "").strip() or bot.BOT_TOKEN
    signer = URLSafeTimedSerializer(secret, salt="fxi-panel-session") if secret else None
    # Owner identity is a Telegram account, never a shared panel password.
    # Prefer an explicit owner ID; for backward compatibility accept ADMIN_IDS
    # only when it contains exactly one account (ambiguous lists fail closed).
    def configured_owner_id():
        # ZEUS_ADMIN_ID is the existing owner identity setting used by this bot.
        raw = os.getenv("ZEUS_ADMIN_ID", "").strip() or os.getenv("OWNER_TELEGRAM_ID", "").strip()
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        stored = bot.admin_data.get("owner_telegram_id")
        if str(stored or "").isdigit() and int(stored) > 0:
            return int(stored)
        configured = sorted(int(value) for value in getattr(bot, "ADMIN_IDS", set()) if int(value) > 0)
        return configured[0] if len(configured) == 1 else 0

    login_attempts = defaultdict(list)

    def enforce_login_limit(request):
        address = request.client.host if request.client else "unknown"
        now = time.time()
        login_attempts[address] = [stamp for stamp in login_attempts[address] if now - stamp < 60]
        if len(login_attempts[address]) >= 20:
            raise HTTPException(429, "تعداد تلاش‌ها زیاد است؛ یک دقیقه دیگر امتحان کن.")
        return address

    def decode(token):
        try:
            return signer.loads(token, max_age=30 * 24 * 60 * 60) if signer and token else {}
        except Exception:
            return {}

    def is_root(request):
        data = decode(request.cookies.get("fxi_admin_session", ""))
        owner_id = configured_owner_id()
        try:
            session_owner_id = int(data.get("owner_id", 0))
            session_version = int(data.get("session_version", 0))
            current_version = int(bot.admin_data.get("owner_session_version", 1))
        except (TypeError, ValueError):
            return False
        return (
            data.get("role") == "owner"
            and owner_id > 0
            and session_owner_id == owner_id
            and session_version == current_version
        )

    def require_admin(request: Request):
        if is_root(request):
            return {
                "user_id": bot.ADMIN_PANEL_AUTH_ID,
                "auth_type": "owner",
                "permissions": sorted(bot.ADMIN_PERMISSIONS),
            }
        token = request.cookies.get("fxi_admin_session", "")
        session = decode(token)
        if session.get("role") == "manager":
            manager_name = str(session.get("manager", "")).strip().lower()
            record = bot.admin_data.get("panel_managers", {}).get(manager_name, {})
            if manager_name and isinstance(record, dict) and record.get("enabled", True) and int(session.get("version", 0)) == int(record.get("session_version", 1)):
                perms = set(record.get("permissions", ["dashboard"])).intersection(bot.ADMIN_PERMISSIONS) - {"admins"}
                needed = bot._permission_for_path(request.url.path)
                if needed not in perms:
                    raise HTTPException(403, "این قابلیت در سطح دسترسی فعلی شما فعال نیست.")
                return {"user_id": 0, "manager": manager_name, "auth_type": "manager_account", "permissions": sorted(perms)}
        raise HTTPException(401, "ابتدا مدیر ربات وارد شود.")

    def require_owner(request: Request):
        if not is_root(request):
            raise HTTPException(401, "ورود مالک لازم است.")
        return {
            "user_id": bot.ADMIN_PANEL_AUTH_ID,
            "auth_type": "owner",
            "permissions": sorted(bot.ADMIN_PERMISSIONS),
        }

    app.dependency_overrides[bot.require_admin] = require_admin

    def active_manager_name(request):
        session = decode(request.cookies.get("fxi_admin_session", ""))
        if session.get("role") != "manager":
            return ""
        manager_name = str(session.get("manager", "")).strip().lower()
        record = bot.admin_data.get("panel_managers", {}).get(manager_name, {})
        try:
            valid_version = int(session.get("version", 0)) == int(record.get("session_version", 1))
        except (TypeError, ValueError, AttributeError):
            return ""
        if manager_name and isinstance(record, dict) and record.get("enabled", True) and valid_version:
            return manager_name
        return ""

    @app.middleware("http")
    async def panel_login_guard(request, call_next):
        path = request.url.path
        # Keep an authenticated owner/manager on their own dashboard when they
        # open a saved login URL or the generic panel link again.
        if path in {"/login", "/admin/login"}:
            if is_root(request):
                return RedirectResponse("/owner", status_code=303)
            if active_manager_name(request):
                return RedirectResponse("/admin", status_code=303)
        if path == "/owner" and not is_root(request):
            token = request.cookies.get("fxi_admin_session", "")
            manager = decode(token)
            manager_name = str(manager.get("manager", "")).strip().lower() if manager.get("role") == "manager" else ""
            record = bot.admin_data.get("panel_managers", {}).get(manager_name, {})
            if manager_name and isinstance(record, dict) and record.get("enabled", True):
                return RedirectResponse("/admin", status_code=303)
            return RedirectResponse("/login", status_code=303)
        if path == "/admin":
            if is_root(request):
                return RedirectResponse("/owner", status_code=303)
            token = request.cookies.get("fxi_admin_session", "")
            manager = decode(token)
            manager_name = str(manager.get("manager", "")).strip().lower() if manager.get("role") == "manager" else ""
            manager_record = bot.admin_data.get("panel_managers", {}).get(manager_name, {})
            if manager_name and isinstance(manager_record, dict) and manager_record.get("enabled", True) and int(manager.get("version", 0)) == int(manager_record.get("session_version", 1)):
                return await call_next(request)
            return RedirectResponse("/admin/login", status_code=303)
        return await call_next(request)

    @app.get("/owner", response_class=HTMLResponse)
    async def owner_panel(auth=Depends(require_owner)):
        html = bot.ADMIN_PANEL_HTML.replace(
            "</head>",
            '<meta name="fxi-permissions" content="' + ",".join(auth["permissions"]) + '">'
            '<meta name="fxi-panel-role" content="owner">'
            '<meta name="fxi-panel-user" content="مالک"></head>',
        )
        return HTMLResponse(html, headers={"Cache-Control": "no-store, max-age=0"})

    def build_database_backup_file():
        if not bot.DATABASE_URL or not bot.DATABASE_READY:
            raise HTTPException(503, "پایگاه داده PostgreSQL آماده نیست؛ ابتدا DATABASE_URL و اتصال دیتابیس را بررسی کن.")

        # Export only the application's known tables. Never interpolate user input into SQL identifiers.
        tables = (
            ("fxi_bot_state", "id"),
            ("fxi_chat_messages", "id"),
            ("fxi_community_messages", "id"),
        )
        fd, path = tempfile.mkstemp(prefix="fxi-db-backup-", suffix=".jsonl")
        digest = hashlib.sha256()
        counts = {}
        max_bytes = 256 * 1024 * 1024

        def write_record(stream, record):
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"
            encoded = line.encode("utf-8")
            if stream.tell() + len(encoded) > max_bytes:
                raise HTTPException(413, "حجم نسخه پشتیبان از سقف ۲۵۶ مگابایت بیشتر است؛ از ابزار پشتیبان‌گیری خود میزبان دیتابیس استفاده کن.")
            stream.write(line)
            digest.update(encoded)

        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                write_record(stream, {
                    "type": "manifest",
                    "format": "fxi-postgresql-jsonl",
                    "version": 1,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "tables": [name for name, _ in tables],
                    "note": "Sensitive owner-only export. Footer sha256 covers all preceding lines.",
                })
                with bot._db_connect() as conn:
                    for table, order_column in tables:
                        count = 0
                        with conn.cursor(name=f"fxi_backup_{table}") as cursor:
                            cursor.itersize = 500
                            cursor.execute(
                                f"SELECT row_to_json(t)::text FROM {table} AS t ORDER BY {order_column}"
                            )
                            for row in cursor:
                                payload = row[0]
                                data = json.loads(payload) if isinstance(payload, str) else payload
                                write_record(stream, {"type": "row", "table": table, "data": data})
                                count += 1
                        counts[table] = count
                footer = {
                    "type": "footer",
                    "counts": counts,
                    "sha256": digest.hexdigest(),
                }
                stream.write(json.dumps(footer, ensure_ascii=False, separators=(",", ":")) + "\n")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            return path, f"fxi-postgresql-backup-{stamp}.jsonl", counts
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise

    @app.get("/owner/api/backup")
    async def owner_database_backup(auth=Depends(require_owner)):
        path, filename, counts = await asyncio.to_thread(build_database_backup_file)
        bot.log_admin_action(
            "database_backup_downloaded",
            "tables=" + ",".join(f"{name}:{count}" for name, count in counts.items()),
        )
        return FileResponse(
            path,
            media_type="application/x-ndjson",
            filename=filename,
            headers={"Cache-Control": "no-store, private", "Pragma": "no-cache"},
            background=BackgroundTask(lambda: os.path.exists(path) and os.unlink(path)),
        )

    @app.get("/admin/request", response_class=HTMLResponse)
    async def manager_access_request_page():
        page = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>درخواست مدیریت · FXI</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;background:radial-gradient(ellipse at 15% 10%,#183b36,transparent 42%),#09131b;color:#edf7f2;font:14px Tahoma,Arial}
.card{width:min(470px,100%);padding:28px;border:1px solid #34534b;border-radius:22px;background:linear-gradient(145deg,#142a2b,#12202b);box-shadow:0 25px 80px #0007}
h1{font-size:21px;margin:0 0 8px}.sub{color:#9cb5ac;line-height:2;font-size:12px;margin:0 0 20px}
label{display:block;color:#c9ded4;font-size:12px;margin:14px 0 7px}input{width:100%;padding:14px;border-radius:11px;border:1px solid #38534f;background:#0b191f;color:#fff;outline:none}
button,.link{display:block;text-align:center;width:100%;padding:14px;margin-top:16px;border:0;border-radius:12px;background:linear-gradient(110deg,#b8efd1,#72c99c);color:#10251b;font-weight:bold;cursor:pointer;text-decoration:none}
button:disabled{opacity:.55;cursor:not-allowed}#msg{min-height:25px;margin-top:14px;color:#b8efd1;line-height:1.9;font-size:12px}.hint{color:#8ca99d;font-size:11px;line-height:1.9;margin-top:14px}#telegramLink{display:none}
</style></head><body><main class="card"><h1>درخواست دسترسی مدیریت FXI</h1>
<p class="sub">لینک دعوت اختصاصی مالک را باز کن؛ توکن خودکار تکمیل می‌شود. فقط نام کاربری دلخواهت را وارد کن و بعد حساب تلگرامت را به درخواست پیوند بده تا مالک بتواند آن را بررسی کند.</p>
<form id="form">
<label for="username">نام کاربری دلخواه</label><input id="username" autocomplete="username" required minlength="3" maxlength="64" pattern="[A-Za-z0-9_.-]{3,64}" placeholder="مثلاً ali_manager">
<label for="invite">توکن دعوت یک‌بارمصرف</label><input id="invite" type="text" autocomplete="off" required minlength="32" maxlength="128" pattern="[A-Za-z0-9_-]{32,128}" placeholder="با بازکردن لینک دعوت، خودکار تکمیل می‌شود">
<button id="submit" type="submit">ثبت درخواست</button></form>
<a id="telegramLink" class="link" target="_blank" rel="noopener">🔗 اتصال حساب تلگرام</a>
<div id="msg" role="status" aria-live="polite"></div>
<div class="hint">برای اتصال حساب، دکمه زیر را بزن و ربات را Start کن. لینک دعوت یک‌بارمصرف است و پس از ۱۵ دقیقه منقضی می‌شود. <a href="/admin/login" style="color:#b8efd1">قبلاً تأیید شده‌ای؟ ورود مدیر</a></div>
</main><script>
const form=document.getElementById('form'),msg=document.getElementById('msg'),btn=document.getElementById('submit'),link=document.getElementById('telegramLink'),inviteInput=document.getElementById('invite');
const fragment=new URLSearchParams(location.hash.slice(1)),sharedInvite=fragment.get('invite')||'';
if(/^[A-Za-z0-9_-]{32,128}$/.test(sharedInvite)){inviteInput.value=sharedInvite;history.replaceState(null,'',location.pathname+location.search);msg.textContent='لینک دعوت شناسایی شد؛ نام کاربری را وارد و درخواست را ثبت کن.'}
form.addEventListener('submit',async e=>{e.preventDefault();const username=document.getElementById('username').value.trim(),invite_code=inviteInput.value.trim();
if(!/^[A-Za-z0-9_.-]{3,64}$/.test(username)){msg.textContent='نام کاربری باید ۳ تا ۶۴ کاراکتر معتبر باشد.';return}
if(!/^[A-Za-z0-9_-]{32,128}$/.test(invite_code)){msg.textContent='لینک دعوت معتبر را از مالک دریافت و باز کن.';return}
btn.disabled=true;btn.textContent='در حال ثبت…';msg.textContent='';link.style.display='none';
try{const r=await fetch('/admin/api/manager-requests',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify({username,invite_code})});const d=await r.json();if(!r.ok)throw Error(d.detail||'ثبت درخواست ممکن نشد');msg.textContent='✅ '+d.message;link.href=d.telegram_link;link.style.display='block';form.reset();}
catch(err){msg.textContent='❌ '+err.message}finally{btn.disabled=false;btn.textContent='ثبت درخواست'}});
</script></body></html>"""
        return HTMLResponse(page, headers={"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer"})

    @app.get("/admin/login", response_class=HTMLResponse)
    async def manager_login_page():
        page = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>ورود مدیر · FXI</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;background:radial-gradient(ellipse at 15% 10%,#183b36,transparent 42%),#09131b;color:#edf7f2;font:14px Tahoma,Arial}
.card{width:min(430px,100%);padding:30px;border:1px solid #34534b;border-radius:24px;background:#14252a;box-shadow:0 22px 65px #0006}
.logo{width:48px;height:48px;border-radius:15px;display:grid;place-items:center;background:#b8efd1;color:#10231a;font-weight:900;font-size:21px}
h1{font-size:21px;margin:18px 0 7px}.sub{color:#9cb5ac;line-height:2;font-size:12px;margin:0 0 22px}
label{display:block;color:#c9ded4;font-size:12px;margin:14px 0 7px}input{width:100%;padding:14px;border-radius:12px;border:1px solid #38534f;background:#0b191f;color:#fff;outline:none}
button{width:100%;padding:14px;margin-top:16px;border:0;border-radius:12px;background:#a8e7c7;color:#10251b;font-weight:bold;cursor:pointer}button:disabled{opacity:.55;cursor:not-allowed}
#msg{min-height:24px;margin-top:14px;color:#ffb5a8;font-size:12px;line-height:1.8}.hint{color:#8ca99d;font-size:11px;line-height:1.9;margin-top:14px}.timer{margin-top:10px;color:#b8efd1;font-size:12px}
</style></head><body><main class="card"><div class="logo">F</div><h1>ورود مدیر اجرایی</h1><p class="sub">نام کاربری تأییدشده را وارد کن و کد یک‌بارمصرف را مستقیم در تلگرام دریافت کن. رمز ثابت لازم نیست.</p>
<form id="requestForm"><label for="username">نام کاربری مدیر</label><input id="username" autocomplete="username" required maxlength="64" pattern="[A-Za-z0-9_.-]{3,64}"><button id="requestBtn" type="submit">🔐 دریافت کد ورود در تلگرام</button></form>
<form id="verifyForm" hidden><label for="otp">کد ۶ رقمی تلگرام</label><input id="otp" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" placeholder="••••••" required><div class="timer" id="timer">01:00</div><button id="verifyBtn" type="submit">تأیید کد و ورود</button><button id="resendBtn" type="button" hidden>دریافت کد تازه</button></form>
<div id="msg" role="alert" aria-live="polite"></div><div class="hint">اگر هنوز درخواستت تأیید نشده یا حساب تلگرامت را متصل نکرده‌ای، ابتدا از صفحه درخواست مدیریت اقدام کن. <a href="/login" style="color:#b8efd1">ورود مالک</a></div></main>
<script>
const req=document.getElementById('requestForm'),verify=document.getElementById('verifyForm'),msg=document.getElementById('msg'),reqBtn=document.getElementById('requestBtn'),verifyBtn=document.getElementById('verifyBtn'),resend=document.getElementById('resendBtn'),timer=document.getElementById('timer');let expiresAt=0,clock=null,activeUsername='';
function showTime(){const left=Math.max(0,Math.ceil((expiresAt-Date.now())/1000));timer.textContent='00:'+String(left).padStart(2,'0');if(!left){clearInterval(clock);resend.hidden=false;verifyBtn.disabled=true;msg.textContent='⏳ کد منقضی شد؛ کد تازه درخواست بده.'}}
async function requestCode(){activeUsername=document.getElementById('username').value.trim();if(!/^[A-Za-z0-9_.-]{3,64}$/.test(activeUsername)){msg.textContent='نام کاربری معتبر وارد کن.';return}
reqBtn.disabled=true;reqBtn.textContent='در حال ارسال کد…';msg.textContent='';
try{const r=await fetch('/auth/manager-request-code',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify({username:activeUsername})});const d=await r.json();if(!r.ok)throw Error(d.detail||'ارسال کد انجام نشد');req.hidden=true;verify.hidden=false;resend.hidden=true;verifyBtn.disabled=false;document.getElementById('otp').value='';expiresAt=Date.now()+60000;showTime();clock=setInterval(showTime,250);document.getElementById('otp').focus();msg.textContent='✅ کد ورود به تلگرام متصل‌شده ارسال شد.'}
catch(e){msg.textContent=e.message}finally{reqBtn.disabled=false;reqBtn.textContent='🔐 دریافت کد ورود در تلگرام'}}
req.addEventListener('submit',e=>{e.preventDefault();requestCode()});
verify.addEventListener('submit',async e=>{e.preventDefault();const code=document.getElementById('otp').value;if(!/^[0-9]{6}$/.test(code)){msg.textContent='کد باید دقیقاً ۶ رقم باشد.';return}
verifyBtn.disabled=true;verifyBtn.textContent='در حال بررسی…';msg.textContent='';
try{const r=await fetch('/auth/manager-login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify({username:activeUsername,code})});const d=await r.json();if(!r.ok)throw Error(d.detail||'کد ورود معتبر نیست');clearInterval(clock);location.assign(d.redirect||'/admin')}
catch(e){msg.textContent=e.message;verifyBtn.disabled=Date.now()>=expiresAt}
finally{verifyBtn.textContent='تأیید کد و ورود'}});
resend.addEventListener('click',()=>{clearInterval(clock);verify.hidden=true;req.hidden=false;reqBtn.focus()});
</script></body></html>"""
        return HTMLResponse(page, headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"})

    @app.post("/auth/manager-request-code")
    async def manager_request_code(request: Request):
        if not bot._admin_origin_allowed(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        address = enforce_login_limit(request)
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "درخواست معتبر نیست.")
        username = str(data.get("username", "")).strip().lower()
        if not __import__("re").fullmatch(r"[a-zA-Z0-9_.-]{3,64}", username):
            raise HTTPException(400, "نام کاربری معتبر نیست.")
        record = bot.admin_data.get("panel_managers", {}).get(username, {})
        telegram_id = int(record.get("telegram_id", 0) or 0) if isinstance(record, dict) else 0
        if not isinstance(record, dict) or not record.get("enabled", True) or telegram_id <= 0:
            login_attempts[address].append(time.time())
            raise HTTPException(401, "حساب مدیر فعال و متصل به تلگرام پیدا نشد.")
        now = time.time()
        challenges = bot.admin_data.setdefault("manager_otp_challenges", {})
        old = challenges.get(username, {})
        if isinstance(old, dict) and now - float(old.get("sent_at", 0)) < 30:
            raise HTTPException(429, "برای دریافت کد تازه ۳۰ ثانیه صبر کن.")
        code = f"{secrets.randbelow(1000000):06d}"
        salt = secrets.token_hex(16)
        digest = hashlib.sha256(f"manager:{username}:{salt}:{code}".encode()).hexdigest()
        challenges[username] = {"salt": salt, "hash": digest, "expires_at": now + 60, "sent_at": now, "attempts": 0}
        bot.save_admin_data()
        try:
            telegram_bot = getattr(bot, "bot", None)
            if telegram_bot is None:
                raise RuntimeError("Telegram bot is not initialized")
            sent_code = await telegram_bot.send_message(
                telegram_id,
                "🔐 <b>کد ورود پنل مدیر FXI</b>\n\n"
                f"<code>{code}</code>\n\n"
                "⏳ این کد فقط ۶۰ ثانیه معتبر است و پس از ورود موفق باطل می‌شود. آن را در اختیار هیچ‌کس نگذار.",
                parse_mode="HTML",
            )
            bot.schedule_temporary_message_cleanup(sent_code, 60)
        except Exception as exc:
            challenges.pop(username, None)
            bot.save_admin_data()
            log.warning("Manager OTP delivery failed (%s)", type(exc).__name__)
            raise HTTPException(503, "ارسال کد ممکن نشد؛ ابتدا ربات را در تلگرام Start کن.")
        login_attempts.pop(address, None)
        return {"message": "کد ورود ارسال شد.", "expires_in": 60}

    @app.post("/auth/manager-login")
    async def manager_login(request: Request):
        if not bot._admin_origin_allowed(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        address = enforce_login_limit(request)
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "درخواست ورود معتبر نیست.")
        username = str(data.get("username", "")).strip().lower()
        code = str(data.get("code", ""))
        if not __import__("re").fullmatch(r"[a-zA-Z0-9_.-]{3,64}", username) or not __import__("re").fullmatch(r"[0-9]{6}", code):
            login_attempts[address].append(time.time())
            raise HTTPException(401, "نام کاربری یا کد ورود معتبر نیست.")
        record = bot.admin_data.get("panel_managers", {}).get(username, {})
        if not isinstance(record, dict) or not record.get("enabled", True) or int(record.get("telegram_id", 0) or 0) <= 0:
            login_attempts[address].append(time.time())
            raise HTTPException(401, "نام کاربری یا کد ورود معتبر نیست.")
        challenges = bot.admin_data.setdefault("manager_otp_challenges", {})
        challenge = challenges.get(username, {})
        now = time.time()
        if not isinstance(challenge, dict) or now >= float(challenge.get("expires_at", 0)):
            challenges.pop(username, None)
            bot.save_admin_data()
            raise HTTPException(401, "کد ورود منقضی شده است؛ کد تازه درخواست بده.")
        if int(challenge.get("attempts", 0)) >= 10:
            challenges.pop(username, None)
            bot.save_admin_data()
            raise HTTPException(429, "پس از ۱۰ تلاش ناموفق، کد باطل شد.")
        expected = hashlib.sha256(f"manager:{username}:{challenge.get('salt','')}:{code}".encode()).hexdigest()
        if not hmac.compare_digest(expected, str(challenge.get("hash", ""))):
            challenge["attempts"] = int(challenge.get("attempts", 0)) + 1
            if challenge["attempts"] >= 10:
                challenges.pop(username, None)
            bot.save_admin_data()
            login_attempts[address].append(now)
            raise HTTPException(401, "کد ورود اشتباه است.")
        challenges.pop(username, None)
        record["last_login_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        record["last_login_ip_hash"] = hashlib.sha256(address.encode("utf-8")).hexdigest()[:16]
        bot.save_admin_data()
        login_attempts.pop(address, None)
        response = JSONResponse({"redirect": "/admin"})
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
        response.set_cookie("fxi_admin_session", signer.dumps({"role": "manager", "manager": username, "version": int(record.get("session_version", 1))}), max_age=30 * 24 * 60 * 60, httponly=True, secure=secure, samesite="strict", path="/")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/login", response_class=HTMLResponse)
    async def panel_login():
        page = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>ورود مالک · FXI Control</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;background:radial-gradient(ellipse at 15% 10%,#183b36,transparent 42%),#09131b;color:#edf7f2;font:14px Tahoma,Arial}
.card{width:min(430px,100%);padding:30px;border:1px solid #34534b;border-radius:24px;background:linear-gradient(145deg,#142a2b,#12202b);box-shadow:0 25px 80px #0007}
.logo{width:48px;height:48px;border-radius:15px;display:grid;place-items:center;background:#b8efd1;color:#10231a;font-weight:900;font-size:21px}
h1{font-size:21px;margin:18px 0 7px}.sub{color:#9cb5ac;line-height:2;font-size:12px;margin:0 0 22px}
label{display:block;color:#c9ded4;font-size:12px;margin:14px 0 7px}input{width:100%;padding:14px;border-radius:12px;border:1px solid #38534f;background:#0b191f;color:#fff;outline:none}input:focus{border-color:#9ce7c0;box-shadow:0 0 0 3px #9ce7c01c}
button{width:100%;padding:14px;margin-top:16px;border:0;border-radius:12px;background:linear-gradient(110deg,#b8efd1,#72c99c);color:#10251b;font-weight:bold;cursor:pointer}button:disabled{opacity:.55;cursor:not-allowed}
#msg{min-height:24px;margin-top:14px;color:#ffb5a8;font-size:12px;line-height:1.8}.hint{color:#8ca99d;font-size:11px;line-height:1.9;margin-top:8px}.timer{color:#b8efd1;text-align:center;margin-top:12px;font-weight:bold}
</style></head><body><main class="card"><div class="logo">F</div><h1>ورود امن مالک</h1>
<p class="sub">برای ورود، یک کد تصادفی یک‌بارمصرف به تلگرام مالک ارسال می‌شود. کد فقط ۶۰ ثانیه اعتبار دارد و پس از اولین ورود باطل می‌شود.</p>
<form id="requestForm"><button id="requestBtn" type="submit">🔐 دریافت کد ورود در تلگرام</button></form>
<form id="verifyForm" hidden><label for="otp">کد ۶ رقمی تلگرام</label><input id="otp" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" placeholder="••••••" required><div class="timer" id="timer">01:00</div><button id="verifyBtn" type="submit">تأیید کد و ورود</button><button id="resendBtn" type="button" hidden>دریافت کد تازه</button></form>
<div id="msg" role="alert"></div><div class="hint">🛡 کد را در اختیار هیچ‌کس قرار نده. تیم پشتیبانی هرگز کد ورودت را درخواست نمی‌کند.</div></main>
<script>
const req=document.getElementById('requestForm'),verify=document.getElementById('verifyForm'),msg=document.getElementById('msg'),reqBtn=document.getElementById('requestBtn'),verifyBtn=document.getElementById('verifyBtn'),resend=document.getElementById('resendBtn'),timer=document.getElementById('timer');let expiresAt=0,clock=null;
function showTime(){const left=Math.max(0,Math.ceil((expiresAt-Date.now())/1000));timer.textContent='00:'+String(left).padStart(2,'0');if(!left){clearInterval(clock);resend.hidden=false;verifyBtn.disabled=true;msg.textContent='⏳ کد منقضی شد؛ کد تازه درخواست بده.'}}
async function requestCode(){reqBtn.disabled=true;reqBtn.textContent='در حال ارسال کد…';msg.textContent='';try{const r=await fetch('/auth/owner-request-code',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const d=await r.json();if(!r.ok)throw Error(d.detail||'ارسال کد انجام نشد');req.hidden=true;verify.hidden=false;resend.hidden=true;verifyBtn.disabled=false;document.getElementById('otp').value='';expiresAt=Date.now()+60000;showTime();clock=setInterval(showTime,250);document.getElementById('otp').focus();msg.textContent='✅ کد ورود به تلگرام مالک ارسال شد.'}catch(e){msg.textContent=e.message}finally{reqBtn.disabled=false;reqBtn.textContent='🔐 دریافت کد ورود در تلگرام'}}
req.addEventListener('submit',e=>{e.preventDefault();requestCode()});
verify.addEventListener('submit',async e=>{e.preventDefault();const code=document.getElementById('otp').value;if(!/^[0-9]{6}$/.test(code)){msg.textContent='کد باید دقیقاً ۶ رقم باشد.';return}verifyBtn.disabled=true;verifyBtn.textContent='در حال بررسی…';msg.textContent='';try{const r=await fetch('/auth/owner-login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code})});const d=await r.json();if(!r.ok)throw Error(d.detail||'کد ورود معتبر نیست');clearInterval(clock);location.assign(d.redirect||'/owner')}catch(e){msg.textContent=e.message;verifyBtn.disabled=Date.now()>=expiresAt}finally{verifyBtn.textContent='تأیید کد و ورود'}});
resend.addEventListener('click',()=>{verify.hidden=true;req.hidden=false;reqBtn.focus()});
</script></body></html>"""
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

    @app.post("/auth/owner-request-code")
    async def owner_request_code(request: Request):
        if not bot._admin_origin_allowed(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        address = enforce_login_limit(request)
        owner_id = configured_owner_id()
        if owner_id <= 0:
            raise HTTPException(503, "حساب مالک مشخص نیست. OWNER_TELEGRAM_ID را تنظیم کن یا در ADMIN_IDS فقط شناسه مالک را قرار بده.")
        now = time.time()
        challenge = bot.admin_data.get("owner_otp_challenge", {})
        if isinstance(challenge, dict) and now - float(challenge.get("sent_at", 0)) < 30:
            raise HTTPException(429, "برای دریافت کد تازه کمی صبر کن.")
        code = f"{secrets.randbelow(1000000):06d}"
        salt = secrets.token_hex(16)
        digest = hashlib.sha256(f"owner:{owner_id}:{salt}:{code}".encode()).hexdigest()
        bot.admin_data["owner_otp_challenge"] = {
            "salt": salt, "hash": digest, "expires_at": now + 60,
            "sent_at": now, "attempts": 0,
        }
        bot.save_admin_data()
        try:
            telegram_bot = getattr(bot, "bot", None)
            if telegram_bot is None:
                raise RuntimeError("Telegram bot is not initialized")
            sent_code = await telegram_bot.send_message(
                owner_id,
                "🔐 <b>کد ورود مالک پنل FXI</b>\n\n"
                f"<code>{code}</code>\n\n"
                "⏳ این کد فقط <b>۶۰ ثانیه</b> معتبر است.\n"
                "♻️ پس از اولین ورود موفق فوراً باطل می‌شود و دوباره قابل استفاده نیست.\n"
                "🛡 آن را برای هیچ‌کس ارسال نکن.",
                parse_mode="HTML",
            )
            bot.schedule_temporary_message_cleanup(sent_code, 60)
        except Exception as exc:
            bot.admin_data.pop("owner_otp_challenge", None)
            bot.save_admin_data()
            log.warning("Owner OTP delivery failed (%s)", type(exc).__name__)
            raise HTTPException(503, "ارسال کد به تلگرام مالک ممکن نشد؛ مالک باید ابتدا ربات را Start کند.")
        return {"message": "کد ورود ارسال شد.", "expires_in": 60}

    @app.post("/auth/owner-login")
    async def owner_login(request: Request):
        if not bot._admin_origin_allowed(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        address = enforce_login_limit(request)
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "درخواست ورود معتبر نیست.")
        code = str(data.get("code", ""))
        if not __import__("re").fullmatch(r"[0-9]{6}", code):
            raise HTTPException(400, "کد ورود باید دقیقاً ۶ رقم باشد.")
        owner_id = configured_owner_id()
        challenge = bot.admin_data.get("owner_otp_challenge", {})
        now = time.time()
        if owner_id <= 0 or not isinstance(challenge, dict):
            raise HTTPException(401, "کد ورود معتبر نیست یا منقضی شده است.")
        if now >= float(challenge.get("expires_at", 0)):
            bot.admin_data.pop("owner_otp_challenge", None)
            bot.save_admin_data()
            raise HTTPException(401, "مهلت کد تمام شده است؛ کد تازه درخواست بده.")
        if int(challenge.get("attempts", 0)) >= 5:
            bot.admin_data.pop("owner_otp_challenge", None)
            bot.save_admin_data()
            raise HTTPException(429, "پس از ۱۰ تلاش ناموفق، کد باطل شد. کد تازه درخواست بده.")
        expected = hashlib.sha256(f"owner:{owner_id}:{challenge.get('salt','')}:{code}".encode()).hexdigest()
        if not hmac.compare_digest(expected, str(challenge.get("hash", ""))):
            challenge["attempts"] = int(challenge.get("attempts", 0)) + 1
            if challenge["attempts"] >= 5:
                bot.admin_data.pop("owner_otp_challenge", None)
            bot.save_admin_data()
            login_attempts[address].append(now)
            raise HTTPException(401, "کد ورود اشتباه است.")
        # Consume before issuing the session: the OTP can never be replayed.
        bot.admin_data.pop("owner_otp_challenge", None)
        bot.save_admin_data()
        login_attempts.pop(address, None)
        version = int(bot.admin_data.get("owner_session_version", 1))
        response = JSONResponse({"redirect": "/owner"})
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
        response.set_cookie(
            "fxi_admin_session",
            signer.dumps({"role": "owner", "owner_id": owner_id, "session_version": version}),
            max_age=30 * 24 * 60 * 60, httponly=True, secure=secure, samesite="strict", path="/",
        )
        return response

    @app.post("/auth/logout")
    async def panel_logout(request: Request):
        if not bot._admin_origin_allowed(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        session = decode(request.cookies.get("fxi_admin_session", ""))
        destination = "/admin/login" if session.get("role") == "manager" else "/login"
        response = RedirectResponse(destination, status_code=303)
        response.delete_cookie("fxi_admin_session", path="/")
        response.delete_cookie("fxi_user_session", path="/")
        return response
