"""Local structured persistence.

Hindsight is the agent's *memory*. This SQLite store is only the app's operational record:
what incidents happened, their state, and their event streams. Keeping the two separate
matters — wiping the local database must never erase what the agent has learned.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings, settings as default_settings
from .logging_setup import get_logger
from .models import ExecutionEvent, Incident, LearningStats, Outcome

log = get_logger("storage")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    repository TEXT,
    error TEXT,
    error_class TEXT,
    status TEXT,
    outcome TEXT,
    run_mode TEXT,
    attempts INTEGER,
    created_at TEXT,
    resolved_at TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incidents_created ON incidents (created_at DESC);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT,
    timestamp TEXT,
    stage TEXT,
    status TEXT,
    message TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_incident ON events (incident_id, id);
"""


class Storage:
    """Thread-safe SQLite wrapper (the agent runs in a worker thread)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings
        self.path: Path = self.settings.sqlite_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ── writes ──────────────────────────────────────────────
    def save_incident(self, incident: Incident) -> None:
        payload = incident.model_dump_json()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO incidents (
                    id, repository, error, error_class, status, outcome, run_mode,
                    attempts, created_at, resolved_at, payload
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    error=excluded.error,
                    error_class=excluded.error_class,
                    status=excluded.status,
                    outcome=excluded.outcome,
                    attempts=excluded.attempts,
                    resolved_at=excluded.resolved_at,
                    payload=excluded.payload
                """,
                (
                    incident.id,
                    incident.repository,
                    incident.error[:500],
                    incident.error_class.value,
                    incident.status.value,
                    incident.outcome.value if incident.outcome else None,
                    incident.run_mode.value,
                    len(incident.attempts),
                    incident.created_at.isoformat(),
                    incident.resolved_at.isoformat() if incident.resolved_at else None,
                    payload,
                ),
            )

    def append_event(self, event: ExecutionEvent) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO events (incident_id, timestamp, stage, status, message, payload)"
                " VALUES (?,?,?,?,?,?)",
                (
                    event.incident_id,
                    event.timestamp.isoformat(),
                    event.stage.value,
                    getattr(event.status, "value", str(event.status)),
                    event.message[:1000],
                    event.model_dump_json(),
                ),
            )

    # ── reads ───────────────────────────────────────────────
    def get_incident(self, incident_id: str) -> Incident | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            return Incident.model_validate_json(row["payload"])
        except Exception as exc:  # noqa: BLE001
            log.warning("stored incident %s could not be parsed: %s", incident_id, exc)
            return None

    def list_incidents(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, repository, error, error_class, status, outcome, run_mode,
                       attempts, created_at, resolved_at
                FROM incidents ORDER BY created_at DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_events(self, incident_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM events WHERE incident_id = ? ORDER BY id ASC LIMIT ?",
                (incident_id, limit),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                events.append(json.loads(row["payload"]))
            except json.JSONDecodeError:
                continue
        return events

    def count(self) -> int:
        with self._lock, self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS c FROM incidents").fetchone()["c"])

    # ── aggregates ──────────────────────────────────────────
    def learning_stats(self) -> LearningStats:
        incidents = [self.get_incident(row["id"]) for row in self.list_incidents(limit=500)]
        incidents = [i for i in incidents if i is not None]
        stats = LearningStats(total_incidents=len(incidents))
        if not incidents:
            return stats

        attempts: list[int] = []
        for incident in sorted(incidents, key=lambda i: i.created_at):
            executed = sum(1 for a in incident.attempts if a.sandbox is not None)
            attempts.append(executed)
            if incident.outcome is Outcome.RECOVERED:
                stats.resolved += 1
            elif incident.outcome is Outcome.ROLLED_BACK:
                stats.rolled_back += 1
            elif incident.outcome is Outcome.ESCALATED:
                stats.escalated += 1
            stats.memories_recalled += incident.metrics.memories_recalled
            stats.historical_fixes_reused += incident.metrics.memories_reused
            stats.failed_approaches_avoided += sum(
                1 for a in incident.attempts if a.review is not None and not a.review.approved
            )
            stats.per_incident.append(
                {
                    "id": incident.id,
                    "error_class": incident.error_class.value,
                    "outcome": incident.outcome.value if incident.outcome else None,
                    "attempts": executed,
                    "memories_recalled": incident.metrics.memories_recalled,
                    "reused_memory": incident.metrics.memories_reused > 0,
                    "duration_s": round(incident.metrics.duration_s, 2),
                    "created_at": incident.created_at.isoformat(),
                }
            )

        attempted = [a for a in attempts if a > 0]
        if attempted:
            stats.avg_attempts = round(sum(attempted) / len(attempted), 2)
        stats.repair_success_rate = round(100.0 * stats.resolved / len(incidents), 1)
        first_try = sum(1 for i in incidents if i.metrics.first_attempt_success)
        stats.first_attempt_success_rate = round(100.0 * first_try / len(incidents), 1)
        regressions = sum(1 for i in incidents if i.metrics.regression_rate)
        stats.regression_rate = round(100.0 * regressions / len(incidents), 1)
        return stats

    def dashboard_metrics(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT status, outcome, error_class, COUNT(*) AS c FROM incidents"
                " GROUP BY status, outcome, error_class"
            ).fetchall()
        by_status: dict[str, int] = {}
        by_outcome: dict[str, int] = {}
        by_class: dict[str, int] = {}
        for row in rows:
            count = int(row["c"])
            by_status[row["status"]] = by_status.get(row["status"], 0) + count
            if row["outcome"]:
                by_outcome[row["outcome"]] = by_outcome.get(row["outcome"], 0) + count
            by_class[row["error_class"]] = by_class.get(row["error_class"], 0) + count

        active = sum(
            count
            for status, count in by_status.items()
            if status
            not in (
                "RECOVERED",
                "ROLLED_BACK",
                "ESCALATED",
                "FAILED",
                "NO_FAILURE",
            )
        )
        return {
            "active_incidents": active,
            "total_incidents": self.count(),
            "resolved": by_outcome.get(Outcome.RECOVERED.value, 0),
            "rolled_back": by_outcome.get(Outcome.ROLLED_BACK.value, 0),
            "escalated": by_outcome.get(Outcome.ESCALATED.value, 0),
            "by_status": by_status,
            "by_outcome": by_outcome,
            "by_error_class": by_class,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def clear(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM events")
            conn.execute("DELETE FROM incidents")
