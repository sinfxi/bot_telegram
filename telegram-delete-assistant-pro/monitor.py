#!/usr/bin/env python3
"""FXI uptime monitor for a Render Cron Job (run every 10 minutes)."""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

SERVICE_URL = os.getenv("SERVICE_URL", "https://telegram-delete-assistant-pro.onrender.com").rstrip("/")
BOT_TOKEN = os.getenv("ZEUS_BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
DEPLOY_HOOK_URL = os.getenv("RENDER_DEPLOY_HOOK_URL", "").strip()
TIMEOUT = float(os.getenv("CHECK_TIMEOUT_SECONDS", "15"))


def request(url, method="GET", data=None, headers=None):
    payload = None if data is None else json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def telegram_notify(message):
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        print("WARN: ZEUS_BOT_TOKEN or ADMIN_CHAT_ID missing; cannot send Telegram notification.")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        status, body = request(
            url, "POST",
            {"chat_id": ADMIN_CHAT_ID, "text": message},
            {"Content-Type": "application/json"},
        )
        ok = status == 200 and json.loads(body).get("ok") is True
        if not ok:
            print(f"WARN: Telegram notification was rejected: HTTP {status}")
        return ok
    except Exception as exc:
        print(f"WARN: Telegram notification failed: {type(exc).__name__}: {exc}")
        return False


def check_service():
    # /health can return 503 when an optional provider/database isn't configured.
    # The root endpoint's redirect to /admin is enough to confirm the web process responds.
    try:
        status, _ = request(SERVICE_URL + "/", headers={"User-Agent": "FXI-Uptime-Monitor/1.0"})
        http_ok = 200 <= status < 400
    except urllib.error.HTTPError as exc:
        http_ok = 200 <= exc.code < 400
    except Exception as exc:
        print(f"Web check failed: {type(exc).__name__}: {exc}")
        http_ok = False

    telegram_ok = False
    if BOT_TOKEN:
        try:
            status, body = request(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe")
            telegram_ok = status == 200 and json.loads(body).get("ok") is True
        except Exception as exc:
            print(f"Telegram getMe check failed: {type(exc).__name__}: {exc}")

    return http_ok and telegram_ok, http_ok, telegram_ok


def trigger_recovery():
    if not DEPLOY_HOOK_URL:
        print("ERROR: RENDER_DEPLOY_HOOK_URL is missing; cannot request recovery.")
        return False
    try:
        status, body = request(DEPLOY_HOOK_URL, method="POST")
        print(f"Recovery deploy hook accepted: HTTP {status}; response={body[:500]}")
        return 200 <= status < 300
    except Exception as exc:
        print(f"Recovery deploy hook failed: {type(exc).__name__}: {exc}")
        return False


def main():
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        print("ERROR: Set ZEUS_BOT_TOKEN and ADMIN_CHAT_ID in the Cron Job environment.")
        return 2

    online, web_ok, telegram_ok = check_service()
    print(f"service_online={online} web_ok={web_ok} telegram_getme_ok={telegram_ok}")

    if online:
        telegram_notify("✅ FXI Monitor: ربات را بررسی کردم؛ سرویس وب و اتصال API تلگرام پاسخ‌گو هستند.")
        return 0

    telegram_notify(
        "🚨 FXI Monitor: ربات در بررسی دوره‌ای پاسخ کامل نداد. "
        f"Web={'OK' if web_ok else 'FAIL'}، Telegram API={'OK' if telegram_ok else 'FAIL'}؛ "
        "در حال درخواست بازیابی از Render هستم."
    )
    recovered = trigger_recovery()
    telegram_notify(
        "🔁 درخواست Deploy مجدد به Render " + ("ارسال شد." if recovered else "ناموفق بود؛ تنظیمات Deploy Hook را بررسی کن.")
    )
    return 0 if recovered else 1


if __name__ == "__main__":
    sys.exit(main())
