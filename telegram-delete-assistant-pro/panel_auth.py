"""Username/password authentication for the FXI panel."""
import os, hmac, hashlib, secrets, re
from datetime import datetime, timezone
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from itsdangerous import URLSafeTimedSerializer

def install_panel_auth(app, bot):
    secret = os.getenv("SESSION_SECRET", "").strip() or bot.BOT_TOKEN
    signer = URLSafeTimedSerializer(secret, salt="fxi-panel-session") if secret else None
    admin_name = os.getenv("ADMIN_PANEL_USERNAME", "fxi-admin").strip()
    admin_pass = os.getenv("ADMIN_PANEL_PASSWORD", "").strip()
    allow_signup = os.getenv("PANEL_ALLOW_REGISTRATION", "true").lower() in {"1","true","yes","on"}

    def decode(token, age):
        try: return signer.loads(token, max_age=age) if signer and token else {}
        except Exception: return {}
    def is_root(request):
        data = decode(request.cookies.get("fxi_admin_session", ""), 43200)
        return data.get("role") == "admin" and hmac.compare_digest(str(data.get("username","")), admin_name)
    def hash_password(password):
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310000)
        return salt.hex() + "$" + digest.hex()
    def verify_password(password, stored):
        try:
            salt, expected = stored.split("$", 1)
            digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 310000)
            return hmac.compare_digest(digest.hex(), expected)
        except Exception: return False

    def require_admin(request: Request):
        if is_root(request):
            return {"user_id": bot.ADMIN_PANEL_AUTH_ID, "auth_type": "username_password", "permissions": sorted(bot.ADMIN_PERMISSIONS)}
        # Keep existing Telegram invite sessions and their permission scopes.
        token = request.cookies.get("fxi_admin_session", "")
        if token and bot.SESSION_SERIALIZER:
            try:
                session = bot.SESSION_SERIALIZER.loads(token, max_age=43200)
                uid = int(session.get("user_id", 0))
                if uid and bot.is_admin(uid):
                    perms = bot._admin_permissions_for(uid)
                    needed = bot._permission_for_path(request.url.path)
                    if needed not in perms: raise HTTPException(403, "این قابلیت در سطح دسترسی فعلی شما فعال نیست.")
                    return {"user_id": uid, "auth_type": "telegram", "permissions": sorted(perms)}
            except HTTPException: raise
            except Exception: pass
        raise HTTPException(401, "ابتدا با حساب مدیر وارد شو.")
    app.dependency_overrides[bot.require_admin] = require_admin

    @app.middleware("http")
    async def panel_login_guard(request, call_next):
        if request.url.path == "/admin" and not is_root(request):
            token = request.cookies.get("fxi_admin_session", "")
            try:
                old = bot.SESSION_SERIALIZER.loads(token, max_age=43200) if token and bot.SESSION_SERIALIZER else {}
                uid = int(old.get("user_id", 0))
            except Exception: uid = 0
            if not uid or not bot.is_admin(uid): return RedirectResponse("/login", status_code=303)
        return await call_next(request)

    @app.get("/login", response_class=HTMLResponse)
    async def panel_login():
        page = """<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>ورود FXI</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#09111e;color:#eef4ff;font:14px Tahoma}.card{width:min(430px,90%);padding:28px;border:1px solid #344761;border-radius:22px;background:#142238}input,button{box-sizing:border-box;width:100%;padding:13px;margin:8px 0;border-radius:10px}input{background:#0a1423;border:1px solid #344761;color:white}button{border:0;background:#aef8df;font-weight:bold;cursor:pointer}.tabs{display:flex;gap:8px}.tabs button{background:#293e59;color:white}#msg{min-height:25px;color:#ffcf9b}</style><main class="card"><h2>FXI · پنل</h2><div class="tabs"><button type="button" onclick="mode('user')">کاربر</button><button type="button" onclick="mode('admin')">مدیر</button></div><form id="form"><input id="username" placeholder="نام کاربری" required><input id="password" type="password" placeholder="رمز عبور" required><button id="submit">ورود</button></form><button id="register" type="button" onclick="mode('register')">ساخت حساب کاربری</button><div id="msg"></div></main><script>let modeNow='user';function mode(v){modeNow=v;submit.textContent=v==='register'?'ثبت‌نام':'ورود';register.hidden=v!=='user';msg.textContent=''}form.onsubmit=async e=>{e.preventDefault();let path=modeNow==='admin'?'/auth/admin-login':modeNow==='register'?'/auth/register':'/auth/user-login';try{let r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:username.value,password:password.value})});let d=await r.json();if(!r.ok)throw Error(d.detail||'خطا');msg.textContent=d.message||'';if(d.redirect)location.href=d.redirect}catch(err){msg.textContent=err.message}}</script></html>"""
        return HTMLResponse(page, headers={"Cache-Control":"no-store"})

    @app.post("/auth/admin-login")
    async def admin_login(request: Request):
        if not bot._admin_origin_allowed(request): raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        data = await request.json()
        if not signer or not admin_pass or not hmac.compare_digest(str(data.get("username","")), admin_name) or not hmac.compare_digest(str(data.get("password","")), admin_pass):
            raise HTTPException(401, "نام کاربری یا رمز مدیر اشتباه است.")
        response = JSONResponse({"redirect":"/admin"})
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto","").split(",")[0].strip() == "https"
        response.set_cookie("fxi_admin_session", signer.dumps({"role":"admin","username":admin_name}), max_age=43200, httponly=True, secure=secure, samesite="strict", path="/")
        return response

    @app.post("/auth/register")
    async def register(request: Request):
        if not bot._admin_origin_allowed(request): raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        if not allow_signup: raise HTTPException(403, "ثبت‌نام کاربران بسته است.")
        data = await request.json()
        username = str(data.get("username","")).strip().lower()
        password = str(data.get("password",""))
        if not re.fullmatch(r"[a-z0-9_.-]{3,32}", username): raise HTTPException(422, "نام کاربری باید ۳ تا ۳۲ نویسه انگلیسی یا عدد باشد.")
        if not 10 <= len(password) <= 128: raise HTTPException(422, "رمز عبور باید ۱۰ تا ۱۲۸ نویسه باشد.")
        if username == admin_name.lower(): raise HTTPException(409, "این نام کاربری رزرو شده است.")
        users = bot.admin_data.setdefault("panel_users", {})
        if username in users: raise HTTPException(409, "این نام کاربری قبلاً ثبت شده است.")
        users[username] = {"password_hash":hash_password(password), "created_at":datetime.now(timezone.utc).isoformat(), "disabled":False}
        bot.save_admin_data()
        return {"message":"حساب ساخته شد؛ حالا وارد شو.","redirect":"/login"}

    @app.post("/auth/user-login")
    async def user_login(request: Request):
        if not bot._admin_origin_allowed(request): raise HTTPException(403, "درخواست بین‌مبدأیی مجاز نیست.")
        data = await request.json()
        username = str(data.get("username","")).strip().lower()
        user = bot.admin_data.get("panel_users",{}).get(username)
        if not user or user.get("disabled") or not verify_password(str(data.get("password","")), user.get("password_hash","")):
            raise HTTPException(401, "نام کاربری یا رمز عبور اشتباه است.")
        if not signer: raise HTTPException(503, "SESSION_SECRET تنظیم نشده است.")
        response = JSONResponse({"redirect":"/account"})
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto","").split(",")[0].strip() == "https"
        response.set_cookie("fxi_user_session", signer.dumps({"role":"user","username":username}), max_age=604800, httponly=True, secure=secure, samesite="strict", path="/")
        return response

    @app.get("/account", response_class=HTMLResponse)
    async def account(request: Request):
        data = decode(request.cookies.get("fxi_user_session",""), 604800)
        username = str(data.get("username","")) if data.get("role") == "user" else ""
        if not username or username not in bot.admin_data.get("panel_users",{}): return RedirectResponse("/login", status_code=303)
        import html
        return HTMLResponse("<html lang='fa' dir='rtl'><meta charset='utf-8'><h1>حساب کاربری</h1><p>خوش اومدی "+html.escape(username)+"</p><p>این حساب دسترسی مدیریت ندارد.</p></html>", headers={"Cache-Control":"no-store"})
