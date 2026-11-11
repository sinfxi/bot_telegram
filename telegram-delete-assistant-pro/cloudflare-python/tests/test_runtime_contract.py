from pathlib import Path
import sqlite3
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
INITIAL = (ROOT / "migrations" / "0001_initial.sql").read_text(encoding="utf-8")


def test_worker_is_webhook_driven_and_does_not_start_polling():
    assert "class Default(WorkerEntrypoint)" in SOURCE
    assert 'path == "/telegram/webhook"' in SOURCE
    assert "start_polling" not in SOURCE
    assert "getUpdates" not in SOURCE
    assert not re.search(r"^\\s*(?:from\\s+zeus_bot|import\\s+zeus_bot)", SOURCE, re.MULTILINE)


def test_webhook_requires_telegram_secret_header():
    assert 'x-telegram-bot-api-secret-token' in SOURCE
    assert "_constant_time_equal(supplied, expected)" in SOURCE
    assert "return _json({\"ok\": False}, 401)" in SOURCE


def test_update_claim_is_idempotent_and_retryable_after_failure():
    assert "INSERT OR IGNORE INTO fxi_py_updates(update_id)" in SOURCE
    assert "status IN ('received','failed')" in SOURCE
    assert "claimed_at < datetime('now','-2 minutes')" in SOURCE
    assert "status='processed'" in SOURCE
    assert "status='failed'" in SOURCE


def test_initial_migration_has_expected_tables_and_claim_lease():
    db = sqlite3.connect(":memory:")
    db.executescript(INITIAL)
    tables = {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"fxi_py_updates", "fxi_py_messages", "fxi_py_channel_posts"} <= tables
    columns = {
        row[1] for row in db.execute("PRAGMA table_info(fxi_py_updates)")
    }
    assert {"update_id", "status", "claimed_at", "processed_at"} <= columns


def test_no_production_database_identifier_is_embedded_in_staging_config():
    config = (ROOT / "wrangler.toml").read_text(encoding="utf-8")
    assert "fxi-telegram-assistant-stage" in config
    assert "c31fe782-6cc2-41ff-a9a3-3e7504d3f319" not in config
