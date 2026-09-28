"""Seed the memory banks.

A warm bank is what makes the demo honest: the agent should be recalling real prior
experience, not performing a cold start in front of an audience. Seeding writes two
historical incidents into Hindsight:

1. A **resolved** pool-sizing incident — the fix that the agent will be tempted to reuse
   in the connection-leak scenario, where it does not apply.
2. An incident whose first attempt **failed** — so the agent has a negative example to
   avoid, which is the half of memory most implementations throw away.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..config import Settings
from ..logging_setup import get_logger
from ..memory import MemoryStore
from ..models import (
    Attempt,
    AttemptSource,
    AttemptStatus,
    Classification,
    ErrorClass,
    Evidence,
    Fixability,
    Incident,
    Outcome,
    Patch,
    TestReport,
)

log = get_logger("seed")


def _historical_pool_incident(settings: Settings, now: datetime) -> Incident:
    """The lesson the agent should have learned: size the pool from the concurrency."""
    incident = Incident(
        id="INC-HIST-1001",
        repository=settings.repo_dir.name,
        error="RedisConnectionError: connection pool exhausted",
        trigger="ci",
        branch="main",
        commit_sha="a82f91cd4e0b7f5c9d31a6e2b8f4c0d7e5a91b34",
        previous_good_commit="b71e20aa1c9f4d3e8a2b6c5d7e9f0a1b2c3d4e5f",
        created_at=now - timedelta(days=12),
        resolved_at=now - timedelta(days=12) + timedelta(minutes=6),
        root_cause=(
            "Worker concurrency was raised from 4 to 40 in app/config.py while the Redis "
            "connection pool stayed at its previous fixed size of 10. Delivery workers "
            "outnumbered available connections and the pool was exhausted."
        ),
        final_resolution=(
            "Derived REDIS_POOL_SIZE from WORKER_CONCURRENCY "
            "(max(8, worker_concurrency * 2)) instead of hardcoding it."
        ),
        verification="Full suite green: 17 passed. No new failures relative to the baseline.",
        outcome=Outcome.RECOVERED,
        classification=Classification(
            error_class=ErrorClass.CONNECTION_EXHAUSTION,
            confidence=0.93,
            reasoning=(
                "Failure is a bounded resource being over-subscribed: worker concurrency 40 "
                "against a pool of 10 connections."
            ),
            affected_files=["app/config.py"],
            likely_fixability=Fixability.CODE_FIXABLE,
            source="llm",
        ),
    )
    incident.evidence = Evidence(
        error_message="RedisConnectionError: connection pool exhausted",
        repo_path=str(settings.repo_dir),
        branch="main",
        commit_sha=incident.commit_sha,
        previous_good_commit=incident.previous_good_commit,
        changed_files=["app/config.py"],
        diff_summary="app/config.py | 4 ++--\n  WORKER_CONCURRENCY: 4 -> 40\n  REDIS_POOL_SIZE: derived -> 10",
        failing_tests=["tests/test_worker.py::test_all_jobs_complete"],
        test_report=TestReport(suite_label="full", exit_code=1, failed=4, passed=13),
        env_info={"env": "ci", "python": "3.11"},
    )
    time_patch = Patch(
        attempt_number=1,
        source=AttemptSource.GENERATED_FIX,
        proposed_fix="Increase the Redis command timeout from 5s to 60s.",
        summary="Raise the Redis timeout so slow commands stop failing",
    )
    sizing_patch = Patch(
        attempt_number=2,
        source=AttemptSource.GENERATED_FIX,
        proposed_fix="Derive REDIS_POOL_SIZE from WORKER_CONCURRENCY.",
        summary="Derive the pool size from the worker concurrency",
    )
    incident.attempts = [
        Attempt(
            number=1,
            source=AttemptSource.GENERATED_FIX,
            status=AttemptStatus.VERIFICATION_FAILED,
            patch=time_patch,
            error=(
                "Original failure persisted: the pool was still exhausted because the "
                "timeout was never the constraint."
            ),
            explanation="Timed out on the first attempt; the symptom was not the cause.",
        ),
        Attempt(
            number=2,
            source=AttemptSource.GENERATED_FIX,
            status=AttemptStatus.SUCCEEDED,
            patch=sizing_patch,
            explanation="Derived the pool size from the concurrency; all tests passed.",
        ),
    ]
    incident.metrics.attempts_used = 2
    incident.metrics.memories_recalled = 0
    return incident


def _historical_leak_incident(settings: Settings, now: datetime) -> Incident:
    """A second, differently-caused exhaustion so the bank has more than one shape."""
    incident = Incident(
        id="INC-HIST-1002",
        repository=settings.repo_dir.name,
        error="RedisConnectionError: connection pool exhausted",
        trigger="ci",
        branch="main",
        commit_sha="c19d3f0a7b2e4856d9c1a3f5e7b90d2c4a6f8e10",
        previous_good_commit="b71e20aa1c9f4d3e8a2b6c5d7e9f0a1b2c3d4e5f",
        created_at=now - timedelta(days=5),
        resolved_at=now - timedelta(days=5) + timedelta(minutes=9),
        root_cause=(
            "A retry loop acquired a second connection without returning the first one, so "
            "each retried job permanently consumed an extra connection."
        ),
        final_resolution=(
            "Released the connection on every path (try/finally) so a retry cannot leak one."
        ),
        verification="Full suite green: 17 passed, including the connection-leak assertion.",
        outcome=Outcome.RECOVERED,
        classification=Classification(
            error_class=ErrorClass.CONNECTION_EXHAUSTION,
            confidence=0.88,
            reasoning="Pool exhausted even though the pool size was correct, pointing at a release bug.",
            affected_files=["app/redis_client.py"],
            likely_fixability=Fixability.CODE_FIXABLE,
            source="llm",
        ),
    )
    incident.evidence = Evidence(
        error_message="RedisConnectionError: connection pool exhausted",
        repo_path=str(settings.repo_dir),
        branch="main",
        commit_sha=incident.commit_sha,
        previous_good_commit=incident.previous_good_commit,
        changed_files=["app/redis_client.py"],
        diff_summary="app/redis_client.py | 12 +++++-------",
        failing_tests=["tests/test_worker.py::test_retry_path_does_not_leak_connections"],
        env_info={"env": "ci"},
    )
    incident.attempts = [
        Attempt(
            number=1,
            source=AttemptSource.GENERATED_FIX,
            status=AttemptStatus.SUCCEEDED,
            patch=Patch(
                attempt_number=1,
                proposed_fix="Release the connection in a finally block on every path.",
                summary="Release connections on the retry path",
            ),
            explanation="The pool was correctly sized; the bug was a missing release.",
        )
    ]
    incident.metrics.attempts_used = 1
    return incident


def seed_conventions(memory: MemoryStore, conventions: list[str]) -> int:
    """Seed the standing conventions into the convention bank. Idempotent."""
    if not conventions:
        log.warning("no conventions to seed")
        return 0
    result = memory.retain_conventions(conventions)
    return int(result.get("conventions", 0))


def seed_history(memory: MemoryStore, settings: Settings) -> list[dict]:
    """Retain the historical incidents. Idempotent via stable document ids."""
    now = datetime.now(timezone.utc)
    seeded: list[dict] = []
    for incident in (
        _historical_pool_incident(settings, now),
        _historical_leak_incident(settings, now),
    ):
        result = memory.retain_incident(incident)
        seeded.append(
            {
                "incident_id": incident.id,
                "error_class": incident.error_class.value,
                "outcome": incident.outcome.value if incident.outcome else None,
                "items_count": result.get("items_count", 0),
            }
        )
        log.info("seeded historical incident %s", incident.id)
    return seeded
