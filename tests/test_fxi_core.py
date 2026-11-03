"""Focused regression tests for the FXI Telegram Community Manager.

These tests intentionally avoid network access and never start Telegram polling.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

_PROJECT_DIR = Path(__file__).resolve().parents[1] / "telegram-delete-assistant-pro"
_TEST_STATE = tempfile.TemporaryDirectory(prefix="fxi-test-")
os.environ["DATABASE_URL"] = ""
os.environ["ZEUS_BOT_TOKEN"] = ""
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["ADMIN_DATA_FILE"] = str(Path(_TEST_STATE.name) / "admin-state.json")
os.environ["ADMIN_PANEL_USERNAME"] = "ci-owner"
os.environ["ADMIN_PANEL_PASSWORD"] = "ci-owner-password-only"
os.environ["SESSION_SECRET"] = "ci-session-secret-not-for-production"
sys.path.insert(0, str(_PROJECT_DIR))

import zeus_bot  # noqa: E402


class NaturalLanguageIntentTests(unittest.TestCase):
    def test_rule_update_is_not_swallowed_by_rule_lookup(self):
        self.assertEqual(zeus_bot._natural_intent("ثبت قوانین لطفاً محترمانه باشید"), "set_rules")
        self.assertEqual(zeus_bot._natural_intent("قوانین جدید: تبلیغ ممنوع"), "set_rules")

    def test_read_only_rules_lookup_remains_available(self):
        self.assertEqual(zeus_bot._natural_intent("قوانین"), "rules")
        self.assertEqual(zeus_bot._natural_intent("قوانین گروه"), "rules")

    def test_common_natural_moderation_phrases(self):
        cases = {
            "پین": "pin",
            "آنپین": "unpin",
            "آنبن": "unban",
            "حذف": "delete",
            "سکوت ۱۰ دقیقه": "mute",
            "آزاد": "unmute",
            "بن": "ban",
            "گفتگوی رفاقتی روشن": "enable_conversation",
            "گفتگوی رفاقتی خاموش": "disable_conversation",
            "فیلتر کلمه تبلیغ": "filter_word",
            "حذف فیلتر تبلیغ": "unfilter_word",
        }
        for phrase, expected in cases.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(zeus_bot._natural_intent(phrase), expected)


class ConfigurationTests(unittest.TestCase):
    def test_only_openrouter_is_configured(self):
        self.assertEqual(set(zeus_bot.PROVIDERS), {"openrouter"})
        self.assertFalse(zeus_bot.provider_ready("openrouter"))
        self.assertFalse(zeus_bot.provider_ready("unknown"))

    def test_voice_tools_are_explicitly_disabled(self):
        self.assertFalse(zeus_bot.feature_enabled("voice_tools"))

    def test_community_settings_limits_are_validated(self):
        valid = zeus_bot.CommunitySettingsPayload(
            settings={"anti_flood_enabled": True},
            warn_limit=4,
            blocked_words=["spam", "advert"],
        )
        self.assertEqual(valid.warn_limit, 4)
        with self.assertRaises(ValidationError):
            zeus_bot.CommunitySettingsPayload(warn_limit=1)
        with self.assertRaises(ValidationError):
            zeus_bot.CommunitySettingsPayload(warn_limit=6)

    def test_ephemeral_admin_state_is_pruned_before_persist(self):
        state = zeus_bot.admin_data
        original = dict(state)
        try:
            now = 2_000_000_000.0
            state["manager_otp_challenges"] = {
                "expired": {"expires_at": now - 1},
                "valid": {"expires_at": now + 60},
            }
            state["owner_otp_challenge"] = {"expires_at": now - 1}
            state["manager_invite_attempts"] = {"ip-a": [now - 61, now - 5], "ip-b": [now - 90]}
            state["manager_invite_global_attempts"] = [now - 61, now - 1]
            state["audit_log"] = [{"n": i} for i in range(510)]
            zeus_bot.prune_ephemeral_admin_state(now)
            self.assertEqual(list(state["manager_otp_challenges"]), ["valid"])
            self.assertNotIn("owner_otp_challenge", state)
            self.assertEqual(state["manager_invite_attempts"], {"ip-a": [now - 5]})
            self.assertEqual(state["manager_invite_global_attempts"], [now - 1])
            self.assertEqual(len(state["audit_log"]), 500)
        finally:
            state.clear()
            state.update(original)

    def test_community_archive_uses_postgres_and_keyset_pagination(self):
        source = (_PROJECT_DIR / "zeus_bot.py").read_text(encoding="utf-8")
        owner_source = (_PROJECT_DIR / "group_owner.py").read_text(encoding="utf-8")
        owner_js = (_PROJECT_DIR / "static" / "group-owner.js").read_text(encoding="utf-8")
        admin_js = (_PROJECT_DIR / "static" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS fxi_community_messages", source)
        self.assertIn("UNIQUE (chat_id, message_id)", source)
        self.assertIn("idx_fxi_community_chat_message", source)
        self.assertIn("ON CONFLICT (chat_id, message_id)", source)
        self.assertIn("before_message_id", source)
        self.assertIn("%s::BIGINT IS NULL", source)
        self.assertIn("_list_community_messages_sync", owner_source)
        self.assertIn("before_message_id", owner_source)
        self.assertIn("now - stamp < 60", owner_source)
        self.assertIn("len(stamps) >= 20", owner_source)
        self.assertIn("loadMoreMessages", owner_js)
        self.assertIn("filterMessages", owner_js)
        self.assertIn("loadOlderCommunityMessages", admin_js)
        self.assertIn("filterCommunityMessages", admin_js)

    def test_storage_diagnostics_are_aggregate_and_visible_to_system_admins(self):
        source = (_PROJECT_DIR / "zeus_bot.py").read_text(encoding="utf-8")
        html = (_PROJECT_DIR / "static" / "admin.html").read_text(encoding="utf-8")
        script = (_PROJECT_DIR / "static" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("_community_storage_diagnostics_sync", source)
        self.assertIn("pg_database_size(current_database())", source)
        self.assertIn('if "system" in permissions:', source)
        self.assertIn('id="archiveStoredMessages"', html)
        self.assertIn('id="databaseSize"', html)
        self.assertIn("op.storage_backend", script)
        self.assertIn("هیچ پاک‌سازی خودکاری", html)

    def test_manager_request_payload_requires_only_name_and_owner_invite_code(self):
        payload = zeus_bot.ManagerRequestPayload(username="ali_manager", invite_code="4821")
        self.assertEqual(payload.username, "ali_manager")
        self.assertEqual(payload.invite_code, "4821")
        self.assertFalse(hasattr(payload, "telegram_id"))
        self.assertFalse(hasattr(payload, "permissions"))
        with self.assertRaises(ValidationError):
            zeus_bot.ManagerRequestPayload(username="ali_manager", invite_code="123")
        with self.assertRaises(ValidationError):
            zeus_bot.ManagerRequestPayload(username="bad name", invite_code="1234")

    def test_manager_request_is_name_and_invite_only_then_telegram_bind(self):
        panel = (_PROJECT_DIR / "static" / "admin.html").read_text(encoding="utf-8")
        auth = (_PROJECT_DIR / "panel_auth.py").read_text(encoding="utf-8")
        script = (_PROJECT_DIR / "static" / "admin.js").read_text(encoding="utf-8")
        self.assertIn('id="username"', auth)
        self.assertIn('id="invite"', auth)
        self.assertIn("telegram_link", auth)
        self.assertIn("manager_bind_", (_PROJECT_DIR / "zeus_bot.py").read_text(encoding="utf-8"))
        self.assertIn("schedule_temporary_message_cleanup", (_PROJECT_DIR / "zeus_bot.py").read_text(encoding="utf-8"))
        self.assertIn("item.telegram_linked", script)
        self.assertNotIn('id="managerCreateForm"', panel)

    def test_manager_otp_flow_replaces_static_password_login(self):
        auth = (_PROJECT_DIR / "panel_auth.py").read_text(encoding="utf-8")
        self.assertIn("/auth/manager-request-code", auth)
        self.assertIn("manager_otp_challenges", auth)
        self.assertIn("len(login_attempts[address]) >= 20", auth)
        self.assertIn("now - stamp < 60", auth)
        self.assertIn("ADMIN_AUTH_WINDOW_SECONDS = 60", (_PROJECT_DIR / "zeus_bot.py").read_text(encoding="utf-8"))
        self.assertIn("ADMIN_AUTH_MAX_FAILURES = 20", (_PROJECT_DIR / "zeus_bot.py").read_text(encoding="utf-8"))
        self.assertIn("len(recent) >= 15", (_PROJECT_DIR / "zeus_bot.py").read_text(encoding="utf-8"))
        self.assertIn("len(global_recent) >= 100", (_PROJECT_DIR / "zeus_bot.py").read_text(encoding="utf-8"))
        self.assertIn("کد یک‌بارمصرف", auth)
        self.assertNotIn("password.length!==4", auth)
        self.assertNotIn('id="telegram" type="number"', auth)

    def test_manager_api_permissions_are_classified(self):
        self.assertEqual(zeus_bot._permission_for_path("/admin/api/community"), "community")
        self.assertEqual(zeus_bot._permission_for_path("/admin/api/users/123/block"), "users")
        self.assertEqual(zeus_bot._permission_for_path("/admin/api/managers"), "admins")
        self.assertEqual(zeus_bot._permission_for_path("/admin/api/audit"), "audit")
        self.assertEqual(zeus_bot._permission_for_path("/admin/api/features"), "system")
        self.assertEqual(zeus_bot._permission_for_path("/admin/api/new-unmapped-route"), "__unmapped__")


if __name__ == "__main__":
    unittest.main()
