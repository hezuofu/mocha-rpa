"""Lightweight embedded queue plugin backed by SQLite.

Uses only the stdlib ``sqlite3`` module — no extra dependencies.  Each queue
database is a single ``.db`` file on disk, making it ideal for:

* Task distribution between pipeline runs
* Retry / dead-letter queues
* Producer-consumer patterns across scheduled pipelines
* Persistent work-in-progress tracking

Usage::

    from mocharpa.plugins.queue.plugin import QueuePlugin

    q = QueuePlugin("tasks.db")
    q.initialize(None)

    mid = q.push("email_jobs", {"to": "a@b.com", "subject": "Hi"})
    msg = q.pop("email_jobs")
    if msg:
        msg_id, payload = msg
        try:
            send_email(payload)
            q.ack(msg_id)
        except Exception as e:
            q.fail(msg_id, str(e))

    q.cleanup()
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from mocharpa.plugins.base import Plugin

logger = logging.getLogger("rpa.queue")

Message = Tuple[int, dict]  # (id, payload)


class QueuePlugin:
    """Persistent, SQLite-backed message queue.

    Attributes:
        name: Plugin identifier (``"queue"``).
        path: Path to the SQLite database file.
    """

    name = "queue"

    def __init__(self, path: str = "mocharpa_queue.db") -> None:
        self._path = path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._context: Any = None

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def initialize(self, context: Any) -> None:
        self._context = context
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._create_table()
        logger.info("QueuePlugin initialized (%s)", self._path)

    def cleanup(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
        logger.info("QueuePlugin cleaned up")

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS mocharpa_queue (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                queue        TEXT    NOT NULL,
                payload      TEXT    NOT NULL,
                status       TEXT    DEFAULT 'pending',
                priority     INTEGER DEFAULT 0,
                scheduled_at REAL,
                max_retries  INTEGER DEFAULT 3,
                retries      INTEGER DEFAULT 0,
                error        TEXT,
                created_at   REAL,
                started_at   REAL,
                finished_at  REAL
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_queue_status
            ON mocharpa_queue (queue, status, priority DESC, scheduled_at)
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    def push(
        self,
        queue: str,
        payload: Any,
        *,
        priority: int = 0,
        delay: float = 0.0,
        max_retries: int = 3,
    ) -> int:
        """Enqueue a message.

        Args:
            queue: Queue name (e.g. ``"email_jobs"``).
            payload: JSON-serialisable data.
            priority: Higher = processed first.
            delay: Seconds to wait before the message becomes available.
            max_retries: Maximum retry attempts before giving up.

        Returns:
            The integer message ID.
        """
        now = time.monotonic()
        scheduled_at = now + delay if delay > 0 else now

        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO mocharpa_queue
                   (queue, payload, priority, scheduled_at, max_retries, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (queue, json.dumps(payload, ensure_ascii=False),
                 priority, scheduled_at, max_retries, now),
            )
            self._conn.commit()
            msg_id = cur.lastrowid

        logger.debug("push: queue=%s id=%s priority=%s delay=%s", queue, msg_id, priority, delay)
        return msg_id

    # ------------------------------------------------------------------
    # Pop
    # ------------------------------------------------------------------

    def pop(self, queue: str) -> Optional[Message]:
        """Atomically claim the next available message.

        Returns ``(message_id, payload_dict)`` or ``None`` if no message is
        ready (either the queue is empty or all messages are delayed /
        running).
        """
        now = time.monotonic()

        with self._lock:
            row = self._conn.execute(
                """SELECT id, payload FROM mocharpa_queue
                   WHERE queue = ?
                     AND status = 'pending'
                     AND scheduled_at <= ?
                   ORDER BY priority DESC, scheduled_at ASC
                   LIMIT 1""",
                (queue, now),
            ).fetchone()

            if row is None:
                return None

            msg_id = row["id"]
            self._conn.execute(
                """UPDATE mocharpa_queue
                   SET status = 'running', started_at = ?
                   WHERE id = ?""",
                (now, msg_id),
            )
            self._conn.commit()

        payload = json.loads(row["payload"])
        logger.debug("pop: queue=%s id=%s", queue, msg_id)
        return (msg_id, payload)

    # ------------------------------------------------------------------
    # Ack / Fail
    # ------------------------------------------------------------------

    def ack(self, msg_id: int) -> None:
        """Mark a message as successfully processed."""
        now = time.monotonic()
        with self._lock:
            self._conn.execute(
                """UPDATE mocharpa_queue
                   SET status = 'done', finished_at = ?
                   WHERE id = ?""",
                (now, msg_id),
            )
            self._conn.commit()
        logger.debug("ack: id=%s", msg_id)

    def fail(self, msg_id: int, error: str = "") -> Optional[int]:
        """Mark a message as failed.

        If retries remain, the message is re-queued as ``'pending'`` and
        its ID is returned.  Otherwise it is marked ``'failed'`` and
        ``None`` is returned.
        """
        now = time.monotonic()
        with self._lock:
            row = self._conn.execute(
                "SELECT retries, max_retries FROM mocharpa_queue WHERE id = ?",
                (msg_id,),
            ).fetchone()

            if row is None:
                logger.warning("fail: unknown id=%s", msg_id)
                return None

            retries = row["retries"] + 1
            if retries < row["max_retries"]:
                self._conn.execute(
                    """UPDATE mocharpa_queue
                       SET status = 'pending', retries = ?, error = ?,
                           started_at = NULL, scheduled_at = ?
                       WHERE id = ?""",
                    (retries, error, now, msg_id),
                )
                self._conn.commit()
                logger.debug("fail: id=%s retry %s/%s", msg_id, retries, row["max_retries"])
                return msg_id

            self._conn.execute(
                """UPDATE mocharpa_queue
                   SET status = 'failed', retries = ?, error = ?, finished_at = ?
                   WHERE id = ?""",
                (retries, error, now, msg_id),
            )
            self._conn.commit()
            logger.debug("fail: id=%s exhausted retries", msg_id)
            return None

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def peek(
        self,
        queue: str,
        status: str = "pending",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List messages in *queue* with the given *status*."""
        rows = self._conn.execute(
            """SELECT * FROM mocharpa_queue
               WHERE queue = ? AND status = ?
               ORDER BY priority DESC, created_at ASC
               LIMIT ?""",
            (queue, status, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def size(self, queue: str, status: str = "pending") -> int:
        """Return the count of messages in *queue* with *status*."""
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM mocharpa_queue WHERE queue = ? AND status = ?",
            (queue, status),
        ).fetchone()
        return row["cnt"]

    def stats(self) -> Dict[str, Dict[str, int]]:
        """Return per-queue / per-status counts."""
        rows = self._conn.execute(
            """SELECT queue, status, COUNT(*) as cnt
               FROM mocharpa_queue GROUP BY queue, status"""
        ).fetchall()
        result: Dict[str, Dict[str, int]] = {}
        for r in rows:
            result.setdefault(r["queue"], {})[r["status"]] = r["cnt"]
        return result

    def get(self, msg_id: int) -> Optional[Dict[str, Any]]:
        """Return the full record for a message by ID."""
        row = self._conn.execute(
            "SELECT * FROM mocharpa_queue WHERE id = ?", (msg_id,)
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def purge(self, queue: str, *, before_days: float = 7.0) -> int:
        """Delete done/failed messages older than *before_days*.

        Returns the number of deleted rows.
        """
        cutoff = time.monotonic() - before_days * 86400
        with self._lock:
            cur = self._conn.execute(
                """DELETE FROM mocharpa_queue
                   WHERE queue = ?
                     AND status IN ('done', 'failed')
                     AND finished_at < ?""",
                (queue, cutoff),
            )
            self._conn.commit()
        logger.info("Purged %d messages from queue '%s'", cur.rowcount, queue)
        return cur.rowcount

    def reset(self, queue: str) -> int:
        """Reset all 'running' messages back to 'pending' (for crash recovery).

        Returns the number of reset messages.
        """
        with self._lock:
            cur = self._conn.execute(
                """UPDATE mocharpa_queue
                   SET status = 'pending', started_at = NULL
                   WHERE queue = ? AND status = 'running'""",
                (queue,),
            )
            self._conn.commit()
        if cur.rowcount:
            logger.info("Reset %d stuck messages in queue '%s'", cur.rowcount, queue)
        return cur.rowcount

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> QueuePlugin:
        self.initialize(None)
        return self

    def __exit__(self, *args: Any) -> None:
        self.cleanup()
