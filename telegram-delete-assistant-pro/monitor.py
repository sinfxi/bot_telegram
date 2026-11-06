#!/usr/bin/env python3
"""Independent FXI monitor for a Render Cron Job (recommended: every 10 minutes).

Recovery is deliberately conservative:
- Telegram API failures alone never trigger a Render deploy.
- The web liveness endpoint must fail three consecutive checks.
- A PostgreSQL-backed 30-minute cooldown prevents deploy loops.
- Without durable DATABASE_URL state, the monitor alerts but does not auto-deploy.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

SERVICE_URL = os.getenv("SERVICE_URL", "https://telegram-delete-assistant-pro.onrender.com").rstrip("/")
BOT_TOKEN = os.getenv("ZEUS_BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
DEPLOY_HOOK_URL = os.getenv("RENDER_DEPLOY_HOOK_URL", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
TIMEOUT = max(5.0, min(float(os.getenv("CHECK_TIMEOUT_SECONDS", "15")), 45.0))
FAILURES_BEFORE_RECOVERY = max(2, int(os.getenv("FAILURES_BEFORE_RECOVERY", "3")))
RECOVERY_COOLDOWN_MINUTES = max(15, int(os.getenv("RECOVERY_COOLDOWN_MINUTES", "30")))


def request(url, method="GET", data=None, headers=None):
    payload = None if data is None else json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def telegram_notify(message):
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        print("WARN: ZEUS_BOT_TOKEN or ADMIN_CHAT_ID missing; notification skipped.")
        return False
    try:
        status, body = request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            "POST",
            {"chat_id": ADMIN_CHAT_ID, "text": message},
            {"Content-Type": "application/json"},
        )
        ok = status == 200 and json.loads(body).get("ok") is True
        if not ok:
            print(f"WARN: Telegram notification rejected (HTTP {status}).")
        return ok
    except Exception as exc:
        print(f"WARN: Telegram notification failed: {type(exc).__name__}.")
        return False


def check_web():
    # Use liveness, not /ready: optional AI/database configuration must not
    # make a live web process look dead and cause unnecessary redeploys.
    try:
        status, _ = request(SERVICE_URL + "/health", headers={"User-Agent": "FXI-Uptime-Monitor/2.0"})
        return 200 <= status < 400
    except urllib.error.HTTPError as exc:
        print(f"Web liveness returned HTTP {exc.code}.")
        return 200 <= exc.code < 400
    except Exception as exc:
        print(f"Web liveness failed: {type(exc).__name__}: {exc}")
        return False


def check_telegram():
    if not BOT_TOKEN:
        return False
    try:
        status, body = request(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe")
        return status == 200 and json.loads(body).get("ok") is True
    except Exception as exc:
        print(f"Telegram getMe failed: {type(exc).__name__}: {exc}")
        return False


def record_web_result(web_ok):
    """Persist failure streak and reserve a cooldown slot before recovery."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required for safe automatic recovery")

    import psycopg

    with psycopg.connect(DATABASE_URL, connect_timeout=8, application_name="fxi-independent-monitor") as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS fxi_monitor_state (
                    id SMALLINT PRIMARY KEY CHECK (id = 1),
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    last_deploy_at TIMESTAMPTZ NULL,
                    last_web_ok BOOLEAN NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                INSERT INTO fxi_monitor_state (id) VALUES (1)
                ON CONFLICT (id) DO NOTHING
            """)
            cur.execute("""
                SELECT consecutive_failures, last_deploy_at, last_web_ok
                FROM fxi_monitor_state WHERE id = 1 FOR UPDATE
            """)
            failures, last_deploy_at, previous_web_ok = cur.fetchone()
            failures = 0 if web_ok else int(failures or 0) + 1
            now = datetime.now(timezone.utc)
            cooldown_done = (
                last_deploy_at is None
                or now - last_deploy_at >= timedelta(minutes=RECOVERY_COOLDOWN_MINUTES)
            )
            should_recover = (not web_ok) and failures >= FAILURES_BEFORE_RECOVERY and cooldown_done

            # Reserve the cooldown before the network call, so overlapping cron
            # invocations cannot trigger multiple deploys.
            cur.execute("""
                UPDATE fxi_monitor_state
                SET consecutive_failures = %s,
                    last_deploy_at = CASE WHEN %s THEN NOW() ELSE last_deploy_at END,
                    last_web_ok = %s,
                    updated_at = NOW()
                WHERE id = 1
            """, (failures, should_recover, web_ok))
        return failures, should_recover, previous_web_ok


def trigger_recovery():
    if not DEPLOY_HOOK_URL:
        print("ERROR: RENDER_DEPLOY_HOOK_URL is missing; recovery was not requested.")
        return False
    try:
        status, body = request(DEPLOY_HOOK_URL, method="POST")
        print(f"Render recovery hook response: HTTP {status}; body={body[:300]}")
        return 200 <= status < 300
    except Exception as exc:
        print(f"Render recovery hook failed: {type(exc).__name__}: {exc}")
        return False


def main():
    web_ok = check_web()
    telegram_ok = check_telegram()
    print(f"web_liveness_ok={web_ok} telegram_api_ok={telegram_ok}")

    try:
        failures, should_recover, previous_web_ok = record_web_result(web_ok)
    except Exception as exc:
        telegram_notify(
            "⚠️ FXI Monitor: نتیجه بررسی ثبت شد، اما ذخیره‌سازی امن وضعیت مانیتور در دسترس نیست؛ "
            "برای جلوگیری از Deploy تکراری، بازیابی خودکار انجام نشد. "
            f"Web={'OK' if web_ok else 'FAIL'}، Telegram API={'OK' if telegram_ok else 'FAIL'}."
        )
        print(f"Safe recovery state unavailable: {type(exc).__name__}: {exc}")
        return 2

    if web_ok:
        if previous_web_ok is False:
            telegram_notify("✅ FXI Monitor: سرویس وب دوباره پاسخ‌گو شده است.")
        elif not telegram_ok:
            telegram_notify("⚠️ FXI Monitor: پنل آنلاین است، اما API تلگرام پاسخ‌گو نیست؛ Deploy انجام نشد.")
        print("Service web process is alive; no recovery deploy required.")
        return 0

    if not should_recover:
        telegram_notify(
            f"🚨 FXI Monitor: مسیر /health پاسخ‌گو نیست؛ شکست متوالی {failures}/"
            f"{FAILURES_BEFORE_RECOVERY}. هنوز Deploy خودکار انجام نمی‌شود."
        )
        return 1

    telegram_notify(
        f"🚨 FXI Monitor: وب‌سرویس پس از {failures} بررسی متوالی ناموفق است؛ "
        "یک درخواست بازیابی کنترل‌شده به Render ارسال می‌کنم."
    )
    recovered = trigger_recovery()
    telegram_notify(
        "🔁 درخواست بازیابی Render " +
        ("پذیرفته شد؛ نتیجه نهایی باید از وضعیت Deploy بررسی شود."
         if recovered else "ناموفق بود؛ لاگ Cron و تنظیمات Deploy Hook را بررسی کن.")
    )
    return 0 if recovered else 1


if __name__ == "__main__":
    sys.exit(main())
