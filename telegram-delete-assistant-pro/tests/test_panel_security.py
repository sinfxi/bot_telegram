import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from panel_security import install_admin_security


@pytest.fixture
def client():
    app = FastAPI()
    install_admin_security(
        app,
        lambda request: request.headers.get("origin") == "https://panel.example",
    )

    @app.post("/admin/logout")
    async def admin_logout():
        return {"ok": True}

    @app.post("/admin/api/action")
    async def admin_action():
        return {"ok": True}

    @app.post("/admin/invite/token")
    async def invite_accept():
        return {"ok": True}

    @app.post("/owner/action")
    async def owner_action():
        return {"ok": True}

    @app.post("/auth/owner-login")
    async def owner_login():
        return {"ok": True}

    @app.get("/admin")
    async def admin_page():
        return {"ok": True}

    return TestClient(app)


@pytest.mark.parametrize(
    "path",
    [
        "/admin/logout",
        "/admin/api/action",
        "/admin/invite/token",
        "/owner/action",
        "/auth/owner-login",
    ],
)
def test_cross_origin_mutations_are_blocked(client, path):
    response = client.post(path, headers={"Origin": "https://attacker.example"})
    assert response.status_code == 403


def test_same_origin_mutation_is_allowed(client):
    response = client.post(
        "/admin/api/action",
        headers={"Origin": "https://panel.example"},
    )
    assert response.status_code == 200


def test_fetch_metadata_blocks_cross_site_when_origin_is_absent(client):
    response = client.post(
        "/admin/logout",
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 403


def test_security_headers_and_proxy_aware_hsts(client):
    response = client.get(
        "/admin",
        headers={"X-Forwarded-Proto": "https"},
    )
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["strict-transport-security"].startswith("max-age=")


def test_real_admin_mutation_routes_have_auth_or_explicit_invite_flow():
    source = Path(__file__).resolve().parents[1].joinpath("zeus_bot.py").read_text(encoding="utf-8")
    decorators = list(re.finditer(r"@app\.(post|put|patch|delete)\(([^\n]+)\)\s*\n\s*(?:async\s+)?def\s+(\w+)\([^\n]*\):", source))
    explicit_flows = {"accept_admin_invite", "admin_logout", "submit_manager_request"}
    for index, match in enumerate(decorators):
        end = decorators[index + 1].start() if index + 1 < len(decorators) else len(source)
        body = source[match.end():end]
        name = match.group(3)
        if "/admin" in match.group(2) and name not in explicit_flows:
            signature = match.group(0)
            assert "Depends(require_admin)" in signature or "Depends(require_owner)" in signature, name


def test_owner_only_manager_mutations_keep_owner_checks():
    source = Path(__file__).resolve().parents[1].joinpath("zeus_bot.py").read_text(encoding="utf-8")
    for name in (
        "create_manager_invite",
        "revoke_manager_invite",
        "approve_manager_request",
        "reject_manager_request",
        "remove_manager",
        "set_manager_permissions",
        "set_admin_permissions",
    ):
        match = re.search(r"def\s+" + name + r"\([^\n]*\):", source)
        assert match, name
        next_route = re.search(r"\n@app\.", source[match.end():])
        end = match.end() + next_route.start() if next_route else len(source)
        body = source[match.end():end]
        assert 'auth.get("auth_type") != "owner"' in body or "_is_primary_admin" in body, name
