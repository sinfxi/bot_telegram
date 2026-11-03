"""Admin-only username/password authentication for the FXI control panel."""
import hashlib
import hmac
import os
import time
import secrets
from collections import defaultdict

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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
        login_attempts[address] = [stamp for stamp in login_attempts[address] if now - stamp < 900]
        if len(login_attempts[address]) >= 8:
            raise HTTPException(429, "تعداد تلاش‌ها زیاد است؛ ۱۵ دقیقه دیگر امتحان کن.")
        return address

    def decode(token):
        try:
            return signer.loads(token, max_age=43200) if signer and token else {}
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

    @app.middleware("http")
    async def panel_login_guard(request, call_next):
        path = request.url.path
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

    @app.get("/admin/request", response_class=HTMLResponse)
    async def manager_access_request_page():
        options = []
        for key, label in bot.ADMIN_PERMISSIONS.items():
            if key == "admins":
                continue
            checked = " checked disabled" if key == "dashboard" else ""
            options.append(
                '<label class="perm"><input type="checkbox" value="' + key + '"' + checked + '>'
                + label + '</label>'
            )
        page = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>درخواست دسترسی مدیریت · FXI</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;background:radial-gradient(ellipse at 15% 10%,#183b36,transparent 42%),#09131b;color:#edf7f2;font:14px Tahoma,Arial}
.card{width:min(560px,100%);padding:28px;border:1px solid #34534b;border-radius:22px;background:linear-gradient(145deg,#142a2b,#12202b);box-shadow:0 25px 80px #0007}
h1{font-size:21px;margin:0 0 8px}.sub{color:#9cb5ac;line-height:2;font-size:12px;margin:0 0 20px}
label.field-label{display:block;color:#c9ded4;font-size:12px;margin:14px 0 7px}
input[type=text],input[type=number]{width:100%;padding:13px;border-radius:11px;border:1px solid #38534f;background:#0b191f;color:#fff;outline:none}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px;margin-top:12px}
.perm{display:flex;gap:8px;align-items:center;padding:10px;border:1px solid #34534b;border-radius:10px;color:#c9ded4;font-size:12px}
button{width:100%;padding:14px;margin-top:18px;border:0;border-radius:12px;background:linear-gradient(110deg,#b8efd1,#72c99c);color:#10251b;font-weight:bold;cursor:pointer}
#msg{min-height:25px;margin-top:14px;color:#b8efd1;line-height:1.8;font-size:12px}
.hint{color:#8ca99d;font-size:11px;line-height:1.9;margin-top:14px}
a{color:#b8efd1}
</style></head><body><main class="card"><h1>درخواست دسترسی مدیریت FXI</h1>
<p class="sub">کد دعوتی را که مالک برایت فرستاده وارد کن. درخواست پس از بررسی و تأیید مالک به حساب مدیر تبدیل می‌شود؛ ثبت درخواست به‌تنهایی دسترسی مدیریتی ایجاد نمی‌کند.</p>
<form id="form">
<label class="field-label" for="invite">کد دعوت</label><input id="invite" type="text" autocomplete="off" required minlength="8" maxlength="64" placeholder="کد دعوت را وارد کن">
<label class="field-label" for="username">نام کاربری دلخواه</label><input id="username" type="text" autocomplete="username" required minlength="3" maxlength="64" pattern="[A-Za-z0-9_.-]{3,64}" placeholder="مثلاً ali_admin">
<label class="field-label" for="telegram">شناسه عددی تلگرام</label><input id="telegram" type="number" min="1" max="9007199254740991" step="1" required placeholder="شناسه عددی حساب تلگرام">
<label class="field-label">دسترسی‌های موردنیاز</label><div class="grid">""" + "".join(options) + """</div>
<button id="submit" type="submit">ارسال درخواست برای مالک</button></form>
<div id="msg" role="status"></div><div class="hint">نکته: برای دریافت پیام تأیید و کد ورود، ابتدا ربات FXI را در تلگرام باز کن و /start را بزن. <a href="/admin/login">قبلاً مدیر شده‌ای؟ ورود مدیر</a></div>
</main><script>
const form=document.getElementById('form'),msg=document.getElementById('msg'),btn=document.getElementById('submit');
form.addEventListener('submit',async e=>{e.preventDefault();const telegram_id=Number(document.getElementById('telegram').value);const raw=document.getElementById('telegram').value.trim();const username=document.getElementById('username').value.trim();if(!/^[1-9][0-9]{0,14}$/.test(raw)||!Number.isSafeInteger(telegram_id)){msg.textContent='شناسه عددی تلگرام معتبر وارد کن.';return}if(!/^[A-Za-z0-9_.-]{3,64}$/.test(username)){msg.textContent='نام کاربری باید ۳ تا ۶۴ کاراکتر و با حروف انگلیسی، عدد، نقطه، خط تیره یا زیرخط باشد.';return}const permissions=[...form.querySelectorAll('.perm input:checked')].map(x=>x.value);if(!permissions.includes('dashboard'))permissions.push('dashboard');btn.disabled=true;btn.textContent='در حال ارسال…';msg.textContent='';try{const r=await fetch('/admin/api/manager-requests',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify({invite_code:document.getElementById('invite').value.trim(),username,telegram_id,permissions})});const d=await r.json();if(!r.ok)throw Error(d.detail||'ثبت درخواست ممکن نشد');form.reset();msg.textContent='✅ '+(d.message||'درخواست ثبت شد. پس از بررسی مالک منتظر پیام تلگرام باش.')}catch(err){msg.textContent='❌ '+err.message}finally{btn.disabled=false;btn.textContent='ارسال درخواست برای مالک'}});
</script></body></html>"""
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

    @app.get("/admin/login", response_class=HTMLResponse)
    async def manager_login_page():
        page = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>ورود مدیر · FXI</title>
<style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;background:radial-gradient(ellipse at 15% 10%,#183b36,transparent 42%),#09131b;color:#edf7f2;font:14px Tahoma,Arial}.card{width:min(430px,100%);padding:30px;border:1px solid #34534b;border-radius:24px;background:linear-gradient(145deg,#142a2b,#12202b);box-shadow:0 25px 80px #0007}.logo{width:48px;height:48px;border-radius:15px;display:grid;place-items:center;background:#b8efd1;color:#10231a;font-weight:900;font-size:21px}h1{font-size:21px;margin:18px 0 7px}.sub{color:#9cb5ac;line-height:2;font-size:12px;margin:0 0 22px}label{display:block;color:#c9ded4;font-size:12px;margin:14px 0 7px}input{width:100%;padding:14px;border-radius:12px;border:1px solid #38534f;background:#0b191f;color:#fff;outline:none}input:focus{border-color:#9ce7c0}button{width:100%;padding:14px;margin-top:16px;border:0;border-radius:12px;background:linear-gradient(110deg,#b8efd1,#72c99c);color:#10251b;font-weight:bold;cursor:pointer}button:disabled{opacity:.55;cursor:not-allowed}#msg{min-height:24px;margin-top:14px;color:#ffb5a8;font-size:12px;line-height:1.8}.hint{color:#8ca99d;font-size:11px;line-height:1.9;margin-top:8px}.timer{color:#b8efd1;text-align:center;margin-top:12px;font-weight:bold}</style></head><body><main class="card"><div class="logo">F</div><h1>ورود امن مدیر</h1><p class="sub">برای ورود، یک کد ۶ رقمی تازه به تلگرام ثبت‌شده‌ات می‌فرستیم؛ کد ۲ دقیقه اعتبار دارد و فقط یک بار قابل استفاده است.</p>
<form id="requestForm"><label for="username">نام کاربری مدیر</label><input id="username" autocomplete="username" required maxlength="64" pattern="[A-Za-z0-9_.-]{3,64}"><div class="hint">اول ربات FXI را در تلگرام باز کن و /start را بزن تا بتوانیم کد را خصوصی برایت بفرستیم.</div><button id="requestBtn" type="submit">ارسال کد به تلگرام</button></form>
<form id="verifyForm" hidden><label for="otp">کد ۶ رقمی تلگرام</label><input id="otp" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" placeholder="••••••" required><div class="timer" id="timer">02:00</div><button id="verifyBtn" type="submit">تأیید کد و ورود</button><button id="resendBtn" type="button" hidden>ارسال مجدد کد</button></form><div id="msg" role="alert"></div><div class="hint" style="margin-top:14px"><a href="/admin/request" style="color:#b8efd1">برای دریافت دسترسی جدید، کد دعوت داری؟ ثبت درخواست مدیریت</a></div></main>
<script>
const req=document.getElementById('requestForm'),verify=document.getElementById('verifyForm'),msg=document.getElementById('msg'),reqBtn=document.getElementById('requestBtn'),verifyBtn=document.getElementById('verifyBtn'),resend=document.getElementById('resendBtn'),timer=document.getElementById('timer');let username='',expiresAt=0,clock=null;
function showTime(){const left=Math.max(0,Math.ceil((expiresAt-Date.now())/1000));timer.textContent=String(Math.floor(left/60)).padStart(2,'0')+':'+String(left%60).padStart(2,'0');if(!left){clearInterval(clock);resend.hidden=false;verifyBtn.disabled=true;msg.textContent='کد منقضی شد؛ برای دریافت کد تازه دوباره درخواست بده.'}}
async function requestCode(){reqBtn.disabled=true;reqBtn.textContent='در حال ارسال…';msg.textContent='';try{const r=await fetch('/auth/manager-request-code',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('username').value.trim()})});const d=await r.json();if(!r.ok)throw Error(d.detail||'ارسال کد انجام نشد');username=document.getElementById('username').value.trim().toLowerCase();req.hidden=true;verify.hidden=false;resend.hidden=true;verifyBtn.disabled=false;document.getElementById('otp').value='';expiresAt=Date.now()+120000;showTime();clock=setInterval(showTime,250);document.getElementById('otp').focus();msg.textContent='کد ورود به تلگرام شما ارسال شد.'}catch(e){msg.textContent=e.message}finally{reqBtn.disabled=false;reqBtn.textContent='ارسال کد به تلگرام'}}
req.addEventListener('submit',e=>{e.preventDefault();requestCode()});verify.addEventListener('submit',async e=>{e.preventDefault();const code=document.getElementById('otp').value;if(!/^[0-9]{6}$/.test(code)){msg.textContent='کد باید دقیقاً ۶ رقم باشد.';return}verifyBtn.disabled=true;verifyBtn.textContent='در حال بررسی…';msg.textContent='';try{const r=await fetch('/auth/manager-login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,code})});const d=await r.json();if(!r.ok)throw Error(d.detail||'کد ورود معتبر نیست');clearInterval(clock);location.assign(d.redirect||'/admin')}catch(e){msg.textContent=e.message;verifyBtn.disabled=Date.now()>=expiresAt}finally{verifyBtn.textContent='تأیید کد و ورود'}});resend.addEventListener('click',()=>{document.getElementById('username').value=username;req.hidden=false;verify.hidden=true;reqBtn.focus()});
</script></body></html>"""
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

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
        if not username or len(username) > 64:
            raise HTTPException(400, "نام کاربری معتبر وارد کن.")
        record = bot.admin_data.get("panel_managers", {}).get(username, {})
        telegram_id = int(record.get("telegram_id", 0)) if isinstance(record, dict) else 0
        if not isinstance(record, dict) or not record.get("enabled", True) or telegram_id <= 0:
            login_attempts[address].append(time.time())
            raise HTTPException(401, "اطلاعات ورود معتبر نیست یا شناسه تلگرام مدیر ثبت نشده است.")
        now = time.time()
        challenges = bot.admin_data.setdefault("manager_otp_challenges", {})
        previous = challenges.get(username, {})
        if now - float(previous.get("sent_at", 0)) < 60:
            raise HTTPException(429, "برای دریافت کد جدید باید کمی صبر کنی.")
        code = f"{secrets.randbelow(1000000):06d}"
        salt = secrets.token_hex(16)
        digest = hashlib.sha256(f"{username}:{salt}:{code}".encode()).hexdigest()
        challenges[username] = {"salt": salt, "hash": digest, "expires_at": now + 120, "sent_at": now, "attempts": 0}
        bot.save_admin_data()
        try:
            if not getattr(bot, "bot", None):
                raise RuntimeError("Telegram bot is not running")
            await bot.bot.send_message(telegram_id, "🔐 کد یک‌بارمصرف ورود به پنل FXI:\n\n" + f"<code>{code}</code>\n\nاین کد فقط ۲ دقیقه معتبر است و پس از یک‌بار استفاده باطل می‌شود.", parse_mode="HTML")
        except Exception:
            challenges.pop(username, None)
            bot.save_admin_data()
            login_attempts[address].append(now)
            raise HTTPException(503, "ارسال پیام به تلگرام مدیر ممکن نشد. مدیر باید ابتدا ربات را Start کند و شناسه تلگرام بررسی شود.")
        return {"message": "کد ورود به تلگرام ارسال شد.", "expires_in": 120}

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
        if not username or not __import__("re").fullmatch(r"[0-9]{6}", code):
            raise HTTPException(400, "نام کاربری و کد ۶ رقمی معتبر وارد کن.")
        record = bot.admin_data.get("panel_managers", {}).get(username, {})
        challenges = bot.admin_data.setdefault("manager_otp_challenges", {})
        challenge = challenges.get(username, {})
        now = time.time()
        if not isinstance(record, dict) or not record.get("enabled", True) or not isinstance(challenge, dict):
            raise HTTPException(401, "کد ورود معتبر نیست یا منقضی شده است.")
        if now >= float(challenge.get("expires_at", 0)):
            challenges.pop(username, None)
            bot.save_admin_data()
            raise HTTPException(401, "مهلت کد تمام شده است؛ کد تازه درخواست بده.")
        if int(challenge.get("attempts", 0)) >= 5:
            challenges.pop(username, None)
            bot.save_admin_data()
            raise HTTPException(429, "به‌دلیل ۵ تلاش ناموفق، کد باطل شد. کد تازه درخواست بده.")
        expected = hashlib.sha256(f"{username}:{challenge.get('salt','')}:{code}".encode()).hexdigest()
        if not hmac.compare_digest(expected, str(challenge.get("hash", ""))):
            challenge["attempts"] = int(challenge.get("attempts", 0)) + 1
            if challenge["attempts"] >= 5:
                challenges.pop(username, None)
            bot.save_admin_data()
            raise HTTPException(401, "کد ورود اشتباه است.")
        challenges.pop(username, None)
        record["last_login_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        record["last_login_ip_hash"] = hashlib.sha256(address.encode("utf-8")).hexdigest()[:16]
        bot.save_admin_data()
        login_attempts.pop(address, None)
        response = JSONResponse({"redirect": "/admin"})
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
        response.set_cookie("fxi_admin_session", signer.dumps({"role": "manager", "manager": username, "version": int(record.get("session_version", 1))}), max_age=43200, httponly=True, secure=secure, samesite="strict", path="/")
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
            await telegram_bot.send_message(
                owner_id,
                "🔐 <b>کد ورود مالک پنل FXI</b>\n\n"
                f"<code>{code}</code>\n\n"
                "⏳ این کد فقط <b>۶۰ ثانیه</b> معتبر است.\n"
                "♻️ پس از اولین ورود موفق فوراً باطل می‌شود و دوباره قابل استفاده نیست.\n"
                "🛡 آن را برای هیچ‌کس ارسال نکن.",
                parse_mode="HTML",
            )
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
            raise HTTPException(429, "پس از ۵ تلاش ناموفق، کد باطل شد. کد تازه درخواست بده.")
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
            max_age=43200, httponly=True, secure=secure, samesite="strict", path="/",
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
