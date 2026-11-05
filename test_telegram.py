import unittest
from unittest.mock import Mock, patch
import requests

from fuelbot.config import Settings
from fuelbot.telegram import TelegramRejected, TelegramUncertain, send_photo


class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(bot_token="test-secret", chat_id="123")

    @patch("fuelbot.telegram.requests.post")
    def test_success_requires_a_confirmed_message_id(self, post):
        post.return_value = Mock(ok=True, status_code=200)
        post.return_value.json.return_value = {"ok": True, "result": {"message_id": 42}}
        self.assertEqual(send_photo(self.settings, b"image", "caption"), 42)
        post.assert_called_once()

    @patch("fuelbot.telegram.requests.post", side_effect=requests.ReadTimeout("ambiguous timeout"))
    def test_timeout_is_uncertain_and_never_retried(self, post):
        with self.assertRaises(TelegramUncertain):
            send_photo(self.settings, b"image", "caption")
        post.assert_called_once()

    @patch("fuelbot.telegram.requests.post")
    def test_rejection_and_unverifiable_responses_are_distinguished(self, post):
        post.return_value = Mock(ok=False, status_code=403)
        post.return_value.json.return_value = {"ok": False, "description": "Forbidden"}
        with self.assertRaises(TelegramRejected):
            send_photo(self.settings, b"image", "caption")
        for payload in (None, [], {}, {"ok": True}, {"ok": True, "result": {"message_id": True}}):
            post.return_value = Mock(ok=True, status_code=200)
            post.return_value.json.return_value = payload
            with self.subTest(payload=payload), self.assertRaises(TelegramUncertain):
                send_photo(self.settings, b"image", "caption")
