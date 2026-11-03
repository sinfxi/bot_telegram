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
os.environ["MANAGER_CREATION_CODE"] = "ci-manager-code-2026"
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

    def test_manager_creation_requires_owner_code_and_four_character_password(self):
        payload = zeus_bot.ManagerAccountPayload(
            username="new_manager",
            password="A7b9",
            setup_code="ci-manager-code-2026",
            permissions=["dashboard"],
        )
        self.assertEqual(payload.password, "A7b9")
        self.assertTrue(zeus_bot.verify_manager_password("A7b9", zeus_bot.hash_manager_password("A7b9")))
        self.assertFalse(zeus_bot.verify_manager_password("bad!", zeus_bot.hash_manager_password("A7b9")))
        with self.assertRaises(ValidationError):
            zeus_bot.ManagerAccountPayload(
                username="short_pin",
                password="123",
                setup_code="ci-manager-code-2026",
            )
        with self.assertRaises(ValidationError):
            zeus_bot.ManagerAccountPayload(
                username="long_pin",
                password="12345",
                setup_code="ci-manager-code-2026",
            )
        with self.assertRaises(ValidationError):
            zeus_bot.ManagerAccountPayload(
                username="no_code",
                password="1234",
            )

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
