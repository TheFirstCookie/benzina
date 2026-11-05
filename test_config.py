import unittest
from fuelbot.config import Settings


class ConfigTests(unittest.TestCase):
    def test_defaults_need_no_telegram_secrets_for_dry_run(self):
        settings = Settings.from_env({})
        self.assertEqual(str(settings.timezone), "Europe/Chisinau")
        with self.assertRaisesRegex(ValueError, "BOT_TOKEN.*CHAT_ID"):
            settings.require_telegram()

    def test_send_time_is_validated_before_starting(self):
        for value in ("24:00", "12:60", "12:50:00", "9:50", "garbage"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "SEND_AT"):
                Settings.from_env({"SEND_AT": value})
        self.assertEqual(Settings.from_env({"SEND_AT": "12:50"}).send_at, "12:50")

    def test_secrets_are_stripped_and_excluded_from_repr(self):
        settings = Settings.from_env({"BOT_TOKEN": " secret-token ", "CHAT_ID": " 12345 ",
                                      "GITHUB_TOKEN": " github-secret "})
        settings.require_telegram()
        self.assertEqual(settings.bot_token, "secret-token")
        self.assertNotIn("secret-token", repr(settings))
        self.assertNotIn("12345", repr(settings))
        self.assertNotIn("github-secret", repr(settings))
