import asyncio
import json
import logging
import os
import re
import secrets
import signal
import sqlite3
import time
import uuid
from pathlib import Path

from aiohttp import web

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("xray-manager")

PROTOCOL = os.getenv("XRAY_PROTOCOL", "vless").lower()
if PROTOCOL not in {"vless", "vmess"}:
    raise RuntimeError("XRAY_PROTOCOL must be vless or vmess")
LISTEN_PORT = int(os.getenv("XRAY_LISTEN_PORT", "8443" if PROTOCOL == "vless" else "8444"))
API_PORT = int(os.getenv("PORT", "8080"))
TOKEN = os.getenv("XRAY_MANAGER_TOKEN", "")
REALITY_TARGET = os.getenv("XRAY_REALITY_TARGET", "www.microsoft.com:443")
REALITY_SNI = os.getenv("XRAY_REALITY_SERVER_NAME", "www.microsoft.com")
DATA = Path(os.getenv("XRAY_DATA_DIR", "/data"))
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / "clients.sqlite3"
CONFIG_PATH = DATA / "xray-config.json"
KEYS_PATH = DATA / "reality-keys.json"
XRAY_BIN = os.getenv("XRAY_BIN", "/usr/local/bin/xray")
xray_process = None
xray_log_task = None
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")
db.executescript("""
CREATE TABLE IF NOT EXISTS clients (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  enabled INTEGER NOT NULL DEFAULT 1,
  expiry_at INTEGER NOT NULL,
  total_bytes INTEGER NOT NULL,
  used_bytes INTEGER NOT NULL DEFAULT 0,
  last_up INTEGER NOT NULL DEFAULT 0,
  last_down INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
""")
db.commit()


class ApiError(Exception):
    pass


def public_client(row):
    return {
        "id": row["id"], "email": row["email"], "enabled": bool(row["enabled"]),
        "expiryAt": row["expiry_at"], "totalBytes": row["total_bytes"],
        "usedBytes": row["used_bytes"], "createdAt": row["created_at"],
        "remainingBytes": max(0, row["total_bytes"] - row["used_bytes"]),
    }


def get_keys():
    if KEYS_PATH.exists():
        return json.loads(KEYS_PATH.read_text())
    import subprocess
    result = subprocess.run([XRAY_BIN, "x25519"], capture_output=True, text=True, timeout=15)
    output = result.stdout + "\n" + result.stderr
    if result.returncode:
        raise RuntimeError("Could not generate Xray REALITY key pair: " + output[-500:])
    private_match = re.search(r"Private\s*key:\s*(\S+)", output, re.I)
    public_match = re.search(r"(?:Public\s*key|Password(?:\s*\(PublicKey\))?):\s*(\S+)", output, re.I)
    if not private_match or not public_match:
        raise RuntimeError("Could not parse xray x25519 output: " + output[-500:])
    keys = {"privateKey": private_match.group(1), "publicKey": public_match.group(1),
            "shortId": secrets.token_hex(8)}
    KEYS_PATH.write_text(json.dumps(keys))
    KEYS_PATH.chmod(0o600)
    return keys


KEYS = get_keys()


def xray_config():
    users = []
    for row in db.execute("SELECT id,email FROM clients WHERE enabled=1 AND expiry_at>? AND used_bytes<total_bytes", (int(time.time()),)):
        item = {"id": row["id"], "email": row["email"], "level": 0}
        if PROTOCOL == "vless":
            item["flow"] = "xtls-rprx-vision"
        users.append(item)
    settings = {"clients": users}
    if PROTOCOL == "vless":
        settings["decryption"] = "none"
    return {
        "log": {"loglevel": "warning"},
        "stats": {},
        "api": {"tag": "api", "services": ["StatsService"]},
        "policy": {
            "levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True}},
            "system": {"statsInboundUplink": True, "statsInboundDownlink": True,
                       "statsOutboundUplink": True, "statsOutboundDownlink": True},
        },
        "inbounds": [
            {
                "tag": "public-in", "listen": "0.0.0.0", "port": LISTEN_PORT,
                "protocol": PROTOCOL, "settings": settings,
                "streamSettings": {
                    "network": "raw", "security": "reality",
                    "realitySettings": {
                        "show": False, "target": REALITY_TARGET, "xver": 0,
                        "serverNames": [REALITY_SNI], "privateKey": KEYS["privateKey"],
                        "shortIds": [KEYS["shortId"]],
                    },
                },
                "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
            },
            {
                "tag": "api-in", "listen": "127.0.0.1", "port": 10085,
                "protocol": "dokodemo-door", "settings": {"address": "127.0.0.1"},
            },
        ],
        "outbounds": [
            {"tag": "direct", "protocol": "freedom", "settings": {}},
            {"tag": "blocked", "protocol": "blackhole", "settings": {}},
        ],
        "routing": {
            "rules": [{"type": "field", "inboundTag": ["api-in"], "outboundTag": "api"}],
        },
    }


async def drain_xray_logs(proc):
    if not proc.stdout:
        return
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        log.info("xray: %s", line.decode(errors="replace").rstrip()[:1000])


async def restart_xray():
    global xray_process, xray_log_task
    config = xray_config()
    CONFIG_PATH.write_text(json.dumps(config, separators=(",", ":")))
    CONFIG_PATH.chmod(0o600)
    test = await asyncio.create_subprocess_exec(
        XRAY_BIN, "run", "-test", "-config", str(CONFIG_PATH),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    test_out, _ = await test.communicate()
    if test.returncode:
        raise RuntimeError("Xray rejected generated config: " + test_out.decode(errors="replace")[-1800:])
    if xray_process and xray_process.returncode is None:
        xray_process.terminate()
        try:
            await asyncio.wait_for(xray_process.wait(), timeout=8)
        except asyncio.TimeoutError:
            xray_process.kill()
            await xray_process.wait()
    if xray_log_task:
        xray_log_task.cancel()
    xray_process = await asyncio.create_subprocess_exec(
        XRAY_BIN, "run", "-config", str(CONFIG_PATH),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    xray_log_task = asyncio.create_task(drain_xray_logs(xray_process))
    await asyncio.sleep(0.35)
    if xray_process.returncode is not None:
        raise RuntimeError(f"Xray exited during startup with code {xray_process.returncode}")
    log.info("Xray %s started on port %s with %s active users", PROTOCOL, LISTEN_PORT, len(config["inbounds"][0]["settings"]["clients"]))


async def query_stats():
    proc = await asyncio.create_subprocess_exec(
        XRAY_BIN, "api", "statsquery", "--server=127.0.0.1:10085",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(stderr.decode(errors="replace")[-500:] or "Xray stats query failed")
    raw = stdout.decode(errors="replace")
    start = raw.find("{")
    if start < 0:
        raise RuntimeError("Xray stats query returned no JSON")
    data = json.loads(raw[start:])
    result = {}
    for stat in data.get("stat", []):
        name = stat.get("name", "")
        match = re.match(r"user>>>(.+)>>>traffic>>>(uplink|downlink)$", name)
        if match:
            result.setdefault(match.group(1), {})[match.group(2)] = int(stat.get("value", 0))
    return result


async def usage_monitor():
    while True:
        try:
            now = int(time.time())
            stats = await query_stats()
            changed = False
            for row in db.execute("SELECT * FROM clients").fetchall():
                values = stats.get(row["email"], {})
                current_up, current_down = values.get("uplink", 0), values.get("downlink", 0)
                old_up, old_down = row["last_up"], row["last_down"]
                # Xray counters can reset after a process restart. Preserve the cumulative quota.
                delta_up = current_up - old_up if current_up >= old_up else current_up
                delta_down = current_down - old_down if current_down >= old_down else current_down
                used = row["used_bytes"] + max(0, delta_up) + max(0, delta_down)
                enabled = bool(row["enabled"])
                if enabled and (now >= row["expiry_at"] or used >= row["total_bytes"]):
                    enabled = False
                    changed = True
                    log.info("Client %s disabled: quota or expiry reached", row["email"])
                db.execute("UPDATE clients SET used_bytes=?,last_up=?,last_down=?,enabled=? WHERE id=?",
                           (used, current_up, current_down, int(enabled), row["id"]))
            db.commit()
            if changed:
                await restart_xray()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Usage monitor iteration failed")
        await asyncio.sleep(20)


@web.middleware
async def auth_middleware(request, handler):
    if request.path.startswith("/admin/"):
        if not TOKEN:
            return web.json_response({"error": "XRAY_MANAGER_TOKEN is not configured"}, status=503)
        if request.headers.get("Authorization", "") != f"Bearer {TOKEN}":
            return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def health(_request):
    alive = bool(xray_process and xray_process.returncode is None)
    return web.json_response({"ok": alive, "protocol": PROTOCOL, "xrayPid": xray_process.pid if alive else None},
                             status=200 if alive else 503)


async def meta(_request):
    return web.json_response({
        "protocol": PROTOCOL, "listenPort": LISTEN_PORT,
        "publicKey": KEYS["publicKey"], "shortId": KEYS["shortId"],
        "serverName": REALITY_SNI, "network": "tcp", "security": "reality",
    })


async def list_clients(_request):
    rows = db.execute("SELECT * FROM clients ORDER BY created_at DESC LIMIT 200").fetchall()
    return web.json_response({"protocol": PROTOCOL, "clients": [public_client(r) for r in rows]})


async def create_client(request):
    body = await request.json()
    try:
        days = int(body.get("days", 30))
        gb = float(body.get("gb", 20))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="days and gb must be numeric")
    if not 1 <= days <= 3650 or not 0.1 <= gb <= 100000:
        raise web.HTTPBadRequest(text="days must be 1..3650 and gb must be 0.1..100000")
    client_id = str(uuid.uuid4())
    email = "tg-" + str(body.get("telegramUserId", "admin")) + "-" + secrets.token_hex(4)
    now = int(time.time())
    db.execute("INSERT INTO clients(id,email,enabled,expiry_at,total_bytes,used_bytes,last_up,last_down,created_at) VALUES(?,?,?,?,?,0,0,0,?)",
               (client_id, email, 1, now + days * 86400, int(gb * 1024**3), now))
    db.commit()
    try:
        await restart_xray()
    except Exception:
        db.execute("DELETE FROM clients WHERE id=?", (client_id,))
        db.commit()
        raise
    row = db.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    return web.json_response({**public_client(row), "reality": {
        "publicKey": KEYS["publicKey"], "shortId": KEYS["shortId"],
        "serverName": REALITY_SNI, "network": "tcp", "security": "reality",
    }}, status=201)


async def update_client(request):
    client_id = request.match_info["client_id"]
    row = db.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    if not row:
        raise web.HTTPNotFound(text="client not found")
    body = await request.json()
    try:
        days = int(body.get("days", 30))
        if not 1 <= days <= 3650:
            raise ValueError
        expiry = max(int(time.time()), row["expiry_at"]) + days * 86400
        if "gb" in body:
            gb = float(body["gb"])
            if not 0.1 <= gb <= 100000:
                raise ValueError
            total, used = int(gb * 1024**3), 0
            # Start the renewed quota from the current Xray counters, not from zero,
            # otherwise the next poll would count all pre-renewal traffic again.
            try:
                current = (await query_stats()).get(row["email"], {})
                last_up, last_down = current.get("uplink", row["last_up"]), current.get("downlink", row["last_down"])
            except Exception:
                last_up, last_down = row["last_up"], row["last_down"]
        else:
            total, used, last_up, last_down = row["total_bytes"], row["used_bytes"], row["last_up"], row["last_down"]
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="days must be 1..3650; optional gb must be 0.1..100000")
    db.execute("UPDATE clients SET enabled=1,expiry_at=?,total_bytes=?,used_bytes=?,last_up=?,last_down=? WHERE id=?",
               (expiry, total, used, last_up, last_down, client_id))
    db.commit()
    await restart_xray()
    return web.json_response(public_client(db.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()))


async def delete_client(request):
    client_id = request.match_info["client_id"]
    row = db.execute("SELECT id FROM clients WHERE id=?", (client_id,)).fetchone()
    if not row:
        raise web.HTTPNotFound(text="client not found")
    db.execute("DELETE FROM clients WHERE id=?", (client_id,))
    db.commit()
    await restart_xray()
    return web.json_response({"ok": True, "id": client_id})


async def main():
    if not TOKEN:
        raise RuntimeError("XRAY_MANAGER_TOKEN is required")
    await restart_xray()
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_get("/health", health)
    app.router.add_get("/admin/meta", meta)
    app.router.add_get("/admin/clients", list_clients)
    app.router.add_post("/admin/clients", create_client)
    app.router.add_patch("/admin/clients/{client_id}", update_client)
    app.router.add_delete("/admin/clients/{client_id}", delete_client)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", API_PORT).start()
    monitor = asyncio.create_task(usage_monitor())
    try:
        while True:
            if xray_process and xray_process.returncode is not None:
                log.error("Xray exited unexpectedly; restarting")
                await restart_xray()
            await asyncio.sleep(5)
    finally:
        monitor.cancel()
        if xray_process and xray_process.returncode is None:
            xray_process.terminate()
            await xray_process.wait()
        await runner.cleanup()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
