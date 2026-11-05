"""Durable delivery reservations: SQLite locally and a Git branch on Actions."""
import base64
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote
from uuid import uuid4

import requests


BLOCKED_STATES = frozenset({"reserved", "sent", "uncertain"})


class StorageError(RuntimeError):
    pass


def is_blocked(record):
    return record is not None and record.get("status") in BLOCKED_STATES


def decode_record(encoded):
    try:
        record = json.loads(encoded)
        if (not isinstance(record, dict) or record.get("status") not in BLOCKED_STATES | {"failed"}
                or not isinstance(record.get("owner"), str) or not record["owner"]):
            raise ValueError("Invalid delivery record")
        message_id = record.get("message_id")
        if record["status"] == "sent" and (isinstance(message_id, bool) or not isinstance(message_id, int) or message_id <= 0):
            raise ValueError("Missing Telegram message ID")
        return record
    except (ValueError, TypeError) as error:
        raise StorageError("Malformed delivery record; refusing to send") from error


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def new_record(owner, metadata=None):
    return {"status": "reserved", "owner": owner, "updated_at": timestamp(),
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"), "metadata": metadata or {}}


@dataclass(frozen=True)
class Reservation:
    key: str
    owner: str


class SQLiteLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS deliveries (key TEXT PRIMARY KEY, record TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS delivery_events (id INTEGER PRIMARY KEY, key TEXT NOT NULL, record TEXT NOT NULL)")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, key):
        with self._connect() as connection:
            row = connection.execute("SELECT record FROM deliveries WHERE key = ?", (key,)).fetchone()
        return decode_record(row[0]) if row else None

    @staticmethod
    def _write(connection, key, record):
        encoded = json.dumps(record)
        connection.execute("INSERT INTO deliveries VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET record=excluded.record", (key, encoded))
        connection.execute("INSERT INTO delivery_events(key, record) VALUES (?, ?)", (key, encoded))

    def reserve(self, key, force=False, metadata=None):
        owner = uuid4().hex
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT record FROM deliveries WHERE key = ?", (key,)).fetchone()
            if row and is_blocked(decode_record(row[0])) and not force:
                return None
            self._write(connection, key, new_record(owner, metadata))
        return Reservation(key, owner)

    def finish(self, reservation, status, message_id=None):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT record FROM deliveries WHERE key = ?", (reservation.key,)).fetchone()
            record = decode_record(row[0]) if row else None
            update_record(record, reservation, status, message_id)
            self._write(connection, reservation.key, record)


def update_record(record, reservation, status, message_id):
    if not record or record.get("owner") != reservation.owner or record.get("status") != "reserved":
        raise StorageError("Delivery reservation is no longer owned by this process")
    if status not in {"sent", "failed", "uncertain"}:
        raise StorageError("Invalid delivery status")
    if status == "sent" and (isinstance(message_id, bool) or not isinstance(message_id, int) or message_id <= 0):
        raise StorageError("Confirmed delivery requires a Telegram message ID")
    record.update(status=status, updated_at=timestamp(), message_id=message_id)


class GitHubLedger:
    def __init__(self, repository, token, branch="bot-deliveries", session=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise StorageError("GITHUB_REPOSITORY must use owner/repository")
        if not token:
            raise StorageError("GitHub delivery tracking requires GITHUB_TOKEN")
        self.base = f"https://api.github.com/repos/{repository}"
        self.branch = branch
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})

    def _request(self, method, path, **kwargs):
        try:
            return self.session.request(method, self.base + path, timeout=(10, 30), **kwargs)
        except requests.RequestException as error:
            raise StorageError(f"GitHub delivery storage unavailable ({type(error).__name__})") from error

    @staticmethod
    def _check(response, allowed=(200, 201)):
        if response.status_code not in allowed:
            raise StorageError(f"GitHub delivery storage returned HTTP {response.status_code}")

    def _read(self, key):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:--[a-z0-9-]+)?", key):
            raise StorageError("Invalid delivery key")
        response = self._request("GET", f"/contents/deliveries/{key}.json", params={"ref": self.branch})
        if response.status_code == 404:
            return None, None
        self._check(response)
        try:
            payload = response.json()
            record = decode_record(base64.b64decode(payload["content"]).decode("utf-8"))
            return record, payload["sha"]
        except (ValueError, KeyError, TypeError) as error:
            raise StorageError("Malformed GitHub delivery record") from error

    def get(self, key):
        return self._read(key)[0]

    def _ensure_branch(self):
        branch_path = "/git/ref/heads/" + quote(self.branch, safe="/")
        response = self._request("GET", branch_path)
        if response.status_code == 200:
            return
        self._check(response, (404,))
        repository = self._request("GET", "")
        self._check(repository)
        default = repository.json()["default_branch"]
        head = self._request("GET", "/git/ref/heads/" + quote(default, safe="/"))
        self._check(head)
        created = self._request("POST", "/git/refs", json={"ref": "refs/heads/" + self.branch,
                                                          "sha": head.json()["object"]["sha"]})
        if created.status_code == 422:
            # Another process may have initialized the branch first.
            self._check(self._request("GET", branch_path))
        else:
            self._check(created)

    def _write(self, key, record, sha=None):
        payload = {"branch": self.branch,
                   "message": f"Record fuel delivery {key}: {record['status']}",
                   "content": base64.b64encode((json.dumps(record, indent=2) + "\n").encode()).decode()}
        if sha:
            payload["sha"] = sha
        return self._request("PUT", f"/contents/deliveries/{key}.json", json=payload)

    def reserve(self, key, force=False, metadata=None):
        self._ensure_branch()
        record, sha = self._read(key)
        if is_blocked(record) and not force:
            return None
        owner = uuid4().hex
        response = self._write(key, new_record(owner, metadata), sha)
        if response.status_code in (409, 422):
            if is_blocked(self.get(key)):
                return None
        self._check(response)
        return Reservation(key, owner)

    def finish(self, reservation, status, message_id=None):
        record, sha = self._read(reservation.key)
        update_record(record, reservation, status, message_id)
        self._check(self._write(reservation.key, record, sha))


def make_ledger(settings):
    if settings.github_token:
        return GitHubLedger(settings.github_repository, settings.github_token, settings.delivery_branch)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        raise StorageError("GitHub Actions requires GITHUB_TOKEN for durable delivery tracking")
    return SQLiteLedger(settings.state_path)
