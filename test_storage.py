import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from fuelbot.delivery import deliver_once
from fuelbot.storage import GitHubLedger, SQLiteLedger, StorageError
from fuelbot.telegram import TelegramRejected, TelegramUncertain


class LedgerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "deliveries.sqlite3"
        self.ledger = SQLiteLedger(self.path)
        self.key = "2026-11-05"

    def test_confirmed_message_survives_restart_and_prevents_resend(self):
        send = Mock(return_value=42)
        self.assertEqual(deliver_once(self.ledger, self.key, send), 42)
        restarted = SQLiteLedger(self.path)
        self.assertEqual(restarted.get(self.key)["message_id"], 42)
        self.assertIsNone(deliver_once(restarted, self.key, send))
        send.assert_called_once()

    def test_concurrent_processes_can_only_reserve_once(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: SQLiteLedger(self.path).reserve(self.key), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_ambiguous_timeout_and_interrupted_process_block_automatic_retry(self):
        send = Mock(side_effect=TelegramUncertain("timeout"))
        with self.assertRaises(TelegramUncertain):
            deliver_once(self.ledger, self.key, send)
        self.assertEqual(self.ledger.get(self.key)["status"], "uncertain")
        self.assertIsNone(deliver_once(SQLiteLedger(self.path), self.key, send))
        send.assert_called_once()
        self.assertIsNotNone(self.ledger.reserve("2026-11-06"))
        self.assertIsNone(SQLiteLedger(self.path).reserve("2026-11-06"))

    def test_explicit_rejection_allows_retry_and_force_is_explicit(self):
        with self.assertRaises(TelegramRejected):
            deliver_once(self.ledger, self.key, Mock(side_effect=TelegramRejected("Forbidden")))
        self.assertEqual(self.ledger.get(self.key)["status"], "failed")
        self.assertEqual(deliver_once(self.ledger, self.key, Mock(return_value=43)), 43)
        self.assertEqual(deliver_once(self.ledger, self.key, Mock(return_value=44), force=True), 44)

    def test_storage_failure_prevents_sending(self):
        ledger = Mock()
        ledger.reserve.side_effect = StorageError("offline")
        send = Mock()
        with self.assertRaises(StorageError):
            deliver_once(ledger, self.key, send)
        send.assert_not_called()

    def test_recording_failure_keeps_reservation_after_confirmed_send(self):
        original_finish = self.ledger.finish
        self.ledger.finish = Mock(side_effect=StorageError("disk full"))
        send = Mock(return_value=42)
        with self.assertRaisesRegex(RuntimeError, "accepted message 42"):
            deliver_once(self.ledger, self.key, send)
        self.assertEqual(SQLiteLedger(self.path).get(self.key)["status"], "reserved")
        self.ledger.finish = original_finish
        self.assertIsNone(deliver_once(self.ledger, self.key, send))
        send.assert_called_once()


class GitHubLedgerTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.ledger = GitHubLedger("TheFirstCookie/benzina", "fake-token", session=self.session)

    def response(self, status, payload=None):
        response = Mock(status_code=status)
        response.json.return_value = payload
        return response

    def content(self, record):
        return {"sha": "existing-sha", "content": base64.b64encode(json.dumps(record).encode()).decode()}

    def test_create_record_then_confirm_using_current_sha(self):
        self.session.request.side_effect = [self.response(200), self.response(404), self.response(201)]
        reservation = self.ledger.reserve("2026-11-05")
        record = json.loads(base64.b64decode(self.session.request.call_args.kwargs["json"]["content"]))
        self.assertEqual(record["status"], "reserved")
        self.session.request.side_effect = [self.response(200, self.content(record)), self.response(200)]
        self.ledger.finish(reservation, "sent", 42)
        payload = self.session.request.call_args.kwargs["json"]
        self.assertEqual(payload["sha"], "existing-sha")
        self.assertEqual(payload["branch"], "bot-deliveries")
        self.assertEqual(json.loads(base64.b64decode(payload["content"]))["message_id"], 42)

    def test_conflict_cannot_create_a_second_delivery(self):
        record = {"status": "reserved", "owner": "another-process"}
        self.session.request.side_effect = [self.response(200), self.response(404), self.response(422),
                                            self.response(200, self.content(record))]
        self.assertIsNone(self.ledger.reserve("2026-11-05"))

    def test_forbidden_or_malformed_records_fail_closed(self):
        for response in (self.response(403), self.response(200, {"content": "bad"})):
            self.session.request.side_effect = None
            self.session.request.return_value = response
            with self.assertRaises(StorageError):
                self.ledger.get("2026-11-05")
