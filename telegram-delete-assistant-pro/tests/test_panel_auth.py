import hashlib
import sys
import time
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from panel_auth import install_panel_auth


class DummyBot:
    BOT_TOKEN = "test-session-secret"
    ADMIN_IDS = {123456}
    ADMIN_PANEL_AUTH_ID = 123456
    ADMIN_PERMISSIONS = {"dashboard", "users"}
    ADMIN_PANEL_HTML = "<html><head></head><body>FXI</body></html>"

    def __init__(self):
        self.admin_data = {
            "owner_session_version": 1,
            "panel_managers": {},
        }

    def save_admin_data(self):
        pass

    def require_admin(self, request):
        return {}

    def _permission_for_path(self, path):
        if "/users" in path:
            return "users"
        return "dashboard"

    def _admin_origin_allowed(self, request):
        origin = request.headers.get("origin")
        if not origin:
            return True
        return origin == f"{request.url.scheme}://{request.url.netloc}"


@pytest.fixture
def panel(monkeypatch):
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "123456")
    monkeypatch.delenv("ZEUS_ADMIN_ID", raising=False)
    bot = DummyBot()
    app = FastAPI()
    install_panel_auth(app, bot)

    @app.post("/owner/test")
    async def owner_test():
        return {"ok": True}

    @app.get("/admin/api/dashboard-test")
    async def dashboard_test(auth=Depends(bot.require_admin)):
        return {"role": auth["auth_type"]}

    @app.get("/admin/api/users/test")
    async def users_test(auth=Depends(bot.require_admin)):
        return {"role": auth["auth_type"]}

    client = TestClient(app)
    signer = URLSafeTimedSerializer(bot.BOT_TOKEN, salt="fxi-panel-session")
    return client, bot, signer


def owner_challenge(bot, code="123456"):
    salt = "fixed-test-salt"
    bot.admin_data["owner_otp_challenge"] = {
        "salt": salt,
        "hash": hashlib.sha256(f"owner:123456:{salt}:{code}".encode()).hexdigest(),
        "expires_at": time.time() + 60,
        "sent_at": time.time(),
        "attempts": 0,
    }
    return code


def test_owner_otp_is_single_use_and_cookie_is_hardened(panel):
    client, bot, _ = panel
    code = owner_challenge(bot)
    response = client.post(
        "/auth/owner-login",
        json={"code": code},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "fxi_admin_session" in response.cookies

    replay = client.post(
        "/auth/owner-login",
        json={"code": code},
        headers={"Origin": "http://testserver"},
    )
    assert replay.status_code == 401


def test_cross_origin_state_change_is_blocked(panel):
    client, _, _ = panel
    response = client.post(
        "/owner/test",
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403


def test_same_origin_state_change_and_security_headers(panel):
    client, _, _ = panel
    response = client.post(
        "/owner/test",
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_malformed_manager_session_version_fails_closed(panel):
    client, bot, signer = panel
    bot.admin_data["panel_managers"]["manager"] = {
        "enabled": True,
        "session_version": 1,
        "permissions": ["dashboard"],
    }
    token = signer.dumps({"role": "manager", "manager": "manager", "version": "not-a-number"})
    client.cookies.set("fxi_admin_session", token)
    response = client.get("/admin/api/dashboard-test")
    assert response.status_code == 401


def test_manager_permissions_are_enforced_per_route(panel):
    client, bot, signer = panel
    bot.admin_data["panel_managers"]["manager"] = {
        "enabled": True,
        "session_version": 3,
        "permissions": ["dashboard"],
    }
    token = signer.dumps({"role": "manager", "manager": "manager", "version": 3})
    client.cookies.set("fxi_admin_session", token)

    allowed = client.get("/admin/api/dashboard-test")
    denied = client.get("/admin/api/users/test")
    assert allowed.status_code == 200
    assert denied.status_code == 403
