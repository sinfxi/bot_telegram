"""Admin-only username/password authentication for the FXI control panel."""
import hmac
import os
import time
from collections import defaultdict

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from itsdangerous import URLSafeTimedSerializer


def install_panel_auth(app, bot):
    secret = os.getenv("SESSION_SECRET", "").strip() or bot.BOT_TOKEN
    signer = URLSafeTimedSerializer(secret, salt="fxi-panel-session") if secret else None
    admin_name = os.getenv("ADMIN_PANEL_USERNAME", "").strip()
    admin_pass = os.getenv("ADMIN_PANEL_PASSWORD", "").strip()
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
        return (
            data.get("role") == "admin"
            and bool(admin_name)
            and hmac.compare_digest(str(data.get("username", "")), admin_name)
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
            if manager_name and isinstance(record, dict) and record.get("enabled", True):
                perms = set(record.get("permissions", ["dashboard"])).intersection(bot.ADMIN_PERMISSIONS) - {"admins"}
                needed = bot._permission_for_path(request.url.path)
                if needed not in perms:
                    raise HTTPException(403, "این قابلیت در سطح دسترسی فعلی شما فعال نیست.")
                return {"user_id": 0, "manager": manager_name, "auth_type": "manager_account", "permissions": sorted(perms)}
        # Backward compatibility for valid one-time Telegram invite sessions.
        if token and bot.SESSION_SERIALIZER:
            try:
                legacy = bot.SESSION_SERIALIZER.loads(token, max_age=43200)
                uid = int(legacy.get("user_id", 0))
                if uid and bot.is_admin(uid) and not bot._is_primary_admin(uid):
                    perms = bot._admin_permissions_for(uid)
                    needed = bot._permission_for_path(request.url.path)
                    if needed not in perms:
                        raise HTTPException(403, "این قابلیت در سطح دسترسی فعلی شما فعال نیست.")
                    return {"user_id": uid, "auth_type": "telegram", "permissions": sorted(perms)}
            except HTTPException:
                raise
            except Exception:
                pass
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
            try:
                uid = int(manager.get("user_id", 0)) if manager.get("role") == "manager" else 0
            except (TypeError, ValueError):
                uid = 0
            if uid and bot.is_admin(uid) and not bot._is_primary_admin(uid):
                return RedirectResponse("/admin", status_code=303)
            return RedirectResponse("/login", status_code=303)
        if path == "/admin":
            if is_root(request):
                return RedirectResponse("/owner", status_code=303)
            token = request.cookies.get("fxi_admin_session", "")
            manager = decode(token)
            manager_name = str(manager.get("manager", "")).strip().lower() if manager.get("role") == "manager" else ""
            manager_record = bot.admin_data.get("panel_managers", {}).get(manager_name, {})
            if manager_name and isinstance(manager_record, dict) and manager_record.get("enabled", True):
                return await call_next(request)
            return RedirectResponse("/admin/login", status_code=303)
        return await call_next(request)

    @app.get("/owner", response_class=HTMLResponse)
    async def owner_panel(auth=Depends(require_owner)):
        html = bot.ADMIN_PANEL_HTML.replace(
            "</head>",
            '<meta name="fxi-permissions" content="' + ",".join(auth["permissions"]) + '">'
            '<meta name="fxi-panel-role" content="owner"></head>',
        )
        return HTMLResponse(html, headers={"Cache-Control": "no-store, max-age=0"})

    @app.get("/admin/login", response_class=HTMLResponse)
    async def manager_login_page():
        page = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>ورود مدیر ربات · FXI</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;background:radial-gradient(ellipse at 15% 10%,#183b36,transparent 42%),#09131b;color:#edf7f2;font:14px Tahoma,Arial}
.card{width:min(430px,100%);padding:30px;border:1px solid #34534b;border-radius:24px;background:linear-gradient(145deg,#142a2b,#12202b);box-shadow:0 25px 80px #0007}
.logo{width:48px;height:48px;border-radius:15px;display:grid;place-items:center;background:#b8efd1;color:#10231a;font-weight:900;font-size:21px}
h1{font-size:21px;margin:18px 0 7px}.sub{color:#9cb5ac;line-height:2;font-size:12px;margin:0 0 22px}
label{display:block;color:#c9ded4;font-size:12px;margin:14px 0 7px}input{width:100%;padding:14px;border-radius:12px;border:1px solid #38534f;background:#0b191f;color:#fff;outline:none}input:focus{border-color:#9ce7c0}
button{width:100%;padding:14px;margin-top:20px;border:0;border-radius:12px;background:linear-gradient(110deg,#b8efd1,#72c99c);color:#10251b;font-weight:bold;cursor:pointer}
#msg{min-height:24px;margin-top:14px;color:#ffb5a8;font-size:12px;line-height:1.8}.hint{color:#8ca99d;font-size:11px;line-height:1.9;margin-top:8px}
</style></head><body><main class="card"><div class="logo">F</div><h1>ورود مدیر ربات</h1>
<p class="sub">مالک ربات برای تو یک نام کاربری و رمز تعیین کرده است. با همان اطلاعات وارد پنل اختصاصی مدیر ربات شو.</p>
<form id="loginForm">
<label for="username">نام کاربری مدیر</label><input id="username" autocomplete="username" required maxlength="64">
<label for="password">رمز عبور شخصی</label><input id="password" type="password" autocomplete="current-password" required minlength="10" maxlength="256">
<label for="activation_code">کد فعال‌سازی (فقط بار اول)</label><input id="activation_code" autocomplete="one-time-code" maxlength="80">
<div class="hint">رمز باید حداقل ۱۰ کاراکتر داشته باشد. کد فعال‌سازی پس از ثبت رمز دیگر لازم نیست.</div>
<button id="submit" type="submit">ورود به پنل مدیر ربات</button></form><div id="msg" role="alert"></div></main>
<script>
const form=document.getElementById('loginForm'),msg=document.getElementById('msg'),btn=document.getElementById('submit');
form.addEventListener('submit',async e=>{e.preventDefault();btn.disabled=true;btn.textContent='در حال بررسی…';msg.textContent='';
try{const response=await fetch('/auth/manager-login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:form.username.value,password:form.password.value})});
const data=await response.json();if(!response.ok)throw new Error(data.detail||'ورود ناموفق بود');location.assign(data.redirect||'/admin');
}catch(error){msg.textContent=error.message;}finally{btn.disabled=false;btn.textContent='ورود به پنل مدیر ربات';}});
</script></body></html>"""
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

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
        password = str(data.get("password", ""))
        if not username or len(username) > 64 or len(password) < 12 or len(password) > 256:
            raise HTTPException(400, "نام کاربری و رمز معتبر وارد کن.")
        record = bot.admin_data.get("panel_managers", {}).get(username, {})
        valid = False
        if isinstance(record, dict) and record.get("enabled", True):
            try:
                salt = bytes.fromhex(str(record["salt"]))
                iterations = max(200000, min(600000, int(record.get("iterations", 310000))))
                actual = __import__("hashlib").pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()
                valid = hmac.compare_digest(actual, str(record.get("hash", "")))
            except (KeyError, ValueError, TypeError):
                valid = False
        if not valid:
            login_attempts[address].append(time.time())
            raise HTTPException(401, "نام کاربری یا رمز عبور اشتباه است.")
        login_attempts.pop(address, None)
        response = JSONResponse({"redirect": "/admin"})
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
        response.set_cookie("fxi_admin_session", signer.dumps({"role": "manager", "manager": username}), max_age=43200, httponly=True, secure=secure, samesite="strict", path="/")
        return response

    @app.get("/login", response_class=HTMLResponse)
    async def panel_login():
        page = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>ورود مالک · FXI Control</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;background:radial-gradient(ellipse at 15% 10%,#183b36,transparent 42%),#09131b;color:#edf7f2;font:14px Tahoma,Arial}
.card{width:min(420px,100%);padding:30px;border:1px solid #34534b;border-radius:24px;background:linear-gradient(145deg,#142a2b,#12202b);box-shadow:0 25px 80px #0007}
.logo{width:48px;height:48px;border-radius:15px;display:grid;place-items:center;background:#b8efd1;color:#10231a;font-weight:900;font-size:21px}
h1{font-size:21px;margin:18px 0 7px}.sub{color:#9cb5ac;line-height:2;font-size:12px;margin:0 0 22px}
label{display:block;color:#c9ded4;font-size:12px;margin:14px 0 7px}input{width:100%;padding:14px;border-radius:12px;border:1px solid #38534f;background:#0b191f;color:#fff;outline:none}input:focus{border-color:#9ce7c0;box-shadow:0 0 0 3px #9ce7c01c}
button{width:100%;padding:14px;margin-top:20px;border:0;border-radius:12px;background:linear-gradient(110deg,#b8efd1,#72c99c);color:#10251b;font-weight:bold;cursor:pointer}
#msg{min-height:24px;margin-top:14px;color:#ffb5a8;font-size:12px;line-height:1.8}.foot{margin-top:18px;color:#78958a;font-size:10px;text-align:center}
</style></head><body><main class="card"><div class="logo">F</div><h1>ورود مالک ربات</h1>
<p class="sub">این بخش مخصوص مالک اصلی ربات است. مدیران اجرایی از پنل جداگانهٔ خودشان وارد می‌شوند.</p>
<form id="loginForm"><label for="username">نام کاربری مدیر</label><input id="username" name="username" autocomplete="username" required maxlength="128">
<label for="password">رمز عبور</label><input id="password" name="password" type="password" autocomplete="current-password" required maxlength="256">
<button id="submit" type="submit">ورود به پنل مالک</button></form><div id="msg" role="alert"></div><div class="foot">FXI Control · دسترسی محدود به مدیران</div></main>
<script>
const form=document.getElementById('loginForm'),msg=document.getElementById('msg'),btn=document.getElementById('submit');
form.addEventListener('submit',async e=>{e.preventDefault();btn.disabled=true;btn.textContent='در حال بررسی…';msg.textContent='';
try{const response=await fetch('/auth/admin-login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:form.username.value,password:form.password.value})});
const data=await response.json();if(!response.ok)throw new Error(data.detail||'ورود ناموفق بود');location.assign(data.redirect||'/owner');
}catch(error){msg.textContent=error.message;}finally{btn.disabled=false;btn.textContent='ورود به پنل مالک';}});
</script></body></html>"""
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

    @app.post("/auth/admin-login")
    async def admin_login(request: Request):
        if not bot._admin_origin_allowed(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        address = enforce_login_limit(request)
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "درخواست ورود معتبر نیست.")
        username = str(data.get("username", ""))
        password = str(data.get("password", ""))
        valid = (
            bool(signer and admin_name and admin_pass)
            and hmac.compare_digest(username, admin_name)
            and hmac.compare_digest(password, admin_pass)
        )
        if not valid:
            login_attempts[address].append(time.time())
            raise HTTPException(401, "نام کاربری یا رمز مدیر اشتباه است.")
        login_attempts.pop(address, None)
        response = JSONResponse({"redirect": "/owner"})
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
        response.set_cookie(
            "fxi_admin_session",
            signer.dumps({"role": "admin", "username": admin_name}),
            max_age=43200,
            httponly=True,
            secure=secure,
            samesite="strict",
            path="/",
        )
        return response

    @app.post("/auth/logout")
    async def panel_logout(request: Request):
        if not bot._admin_origin_allowed(request):
            raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie("fxi_admin_session", path="/")
        response.delete_cookie("fxi_user_session", path="/")
        return response
