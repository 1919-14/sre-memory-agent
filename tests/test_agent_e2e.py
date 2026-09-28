"""End-to-end test of the complete incident loop.

Runs with a scripted LLM and no memory layer, so it is deterministic and offline. It
proves the plumbing: evidence -> classify -> propose -> validate -> review -> sandbox
(reproduce, verify, regress) -> recover.

A second test asserts the escalation path makes no attempt to patch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sre_agent.agent import SREAgent
from sre_agent.config import Settings
from sre_agent.llm import ScriptedLLM
from sre_agent.logging_setup import setup_logging
from sre_agent.models import (
    AttemptStatus,
    ErrorClass,
    EventStatus,
    ExecutionEvent,
    Incident,
    Outcome,
)

pytestmark = [pytest.mark.slow]


def _fix_concurrency_patch(_messages):
    """Deterministic 'LLM': correct the pool sizing in the demo service."""
    from sre_agent.config import settings

    path = settings.live_repo_dir / "app" / "config.py"
    content = path.read_text(encoding="utf-8")
    content = content.replace(
        "# Pool size tuned for our previous traffic level.\nREDIS_POOL_SIZE = 10",
        "# Derived from the worker concurrency so the pool can never be outrun.\n"
        "REDIS_POOL_SIZE = max(8, WORKER_CONCURRENCY * 2)",
    )
    return {
        "root_cause": (
            "Worker concurrency was raised to 40 while the Redis connection pool was "
            "hardcoded at 10, so delivery workers outnumbered available connections."
        ),
        "proposed_fix": "Derive REDIS_POOL_SIZE from WORKER_CONCURRENCY.",
        "summary": "Derive the Redis pool size from the worker concurrency",
        "files": [{"path": "app/config.py", "content": content, "rationale": "size pool from load"}],
        "expected_outcome": "the pool grows with concurrency and the suite passes",
        "risk": "low",
        "test_strategy": "run the full suite",
    }


def _no_op_patch(_messages):
    """A patch that survives validation and review but does not fix anything.

    Used to drive the failure path: the interface has to make a rollback as observable as a
    recovery, and it can only do that from events the agent really emits.
    """
    from sre_agent.config import settings

    path = settings.live_repo_dir / "app" / "config.py"
    content = path.read_text(encoding="utf-8")
    content = content.replace(
        "# Pool size tuned for our previous traffic level.",
        "# Pool size reviewed; the sizing logic is unchanged.",
    )
    return {
        "root_cause": "Assumed the pool comment was stale.",
        "proposed_fix": "Update the comment next to the pool constant.",
        "summary": "Comment-only change to the pool configuration",
        "files": [
            {"path": "app/config.py", "content": content, "rationale": "cosmetic"}
        ],
        "expected_outcome": "no change to behaviour",
        "risk": "low",
        "test_strategy": "run the full suite",
    }


def _classify_payload():
    return {
        "error_class": "connection-exhaustion",
        "confidence": 0.95,
        "reasoning": "a bounded resource is over-subscribed: concurrency 40 vs a pool of 10",
        "affected_files": ["app/config.py"],
        "likely_fixability": "code-fixable",
        "evidence_required": ["configured pool size", "worker concurrency"],
    }


@pytest.fixture
def agent_settings(scenario, demo_repo: Path) -> Settings:
    scenario("concurrency")
    return Settings(
        max_repair_attempts=2,
        regression_flake_reruns=0,
        code_review_enabled=True,
        convention_memory_enabled=False,
        sandbox_backend="local",
    )


def test_full_loop_recovers_the_incident(agent_settings: Settings, demo_repo: Path) -> None:
    setup_logging()
    llm = ScriptedLLM({"classify": _classify_payload(), "generate_patch": _fix_concurrency_patch})
    agent = SREAgent(settings=agent_settings, llm=llm, memory=None)

    incident = Incident(
        repository=demo_repo.name,
        error="RedisConnectionError: connection pool exhausted",
        trigger="test-run",
        previous_good_commit="good",
    )

    result = agent.run_incident(incident)

    assert result.outcome is Outcome.RECOVERED, result.warnings
    assert result.status.value == "RECOVERED"
    assert result.classification is not None
    assert result.classification.error_class is ErrorClass.CONNECTION_EXHAUSTION

    executed = [a for a in result.attempts if a.sandbox is not None]
    assert len(executed) == 1
    assert executed[0].status is AttemptStatus.SUCCEEDED
    # The failure must have been reproduced before the patch was trusted.
    assert executed[0].sandbox is not None
    assert executed[0].sandbox.error_reproduced is True
    assert executed[0].sandbox.test_report is not None
    assert executed[0].sandbox.test_report.green is True
    assert executed[0].regression is not None
    assert executed[0].regression.acceptable is True

    stages = [event.stage.value for event in result.events]
    assert "incident_detected" in stages
    assert "classified" in stages
    assert "review_gate" in stages
    assert "sandbox_execution" in stages
    assert "regression_check" in stages
    assert "resolved" in stages


def test_every_reached_stage_announces_itself(agent_settings: Settings, demo_repo: Path) -> None:
    """A live run must be observable while it happens, not only after it finishes.

    The dashboard can only say "the agent is searching Hindsight right now" if the agent says
    so itself. That requires two things from every stage: an opening RUNNING event, and a
    measured `duration_ms` on the event that closes it — never a guess, never an estimate.
    """
    setup_logging()
    llm = ScriptedLLM({"classify": _classify_payload(), "generate_patch": _fix_concurrency_patch})
    agent = SREAgent(settings=agent_settings, llm=llm, memory=None)

    result = agent.run_incident(
        Incident(
            repository=demo_repo.name,
            error="RedisConnectionError: connection pool exhausted",
            trigger="test-run",
            previous_good_commit="good",
        )
    )
    assert result.outcome is Outcome.RECOVERED, result.warnings

    by_stage: dict[str, list[ExecutionEvent]] = {}
    for event in result.events:
        by_stage.setdefault(event.stage.value, []).append(event)

    # Every step this run reached opened by saying it had started.
    for stage in (
        "incident_detected",
        "classified",
        "recalling_memory",
        "fix_generated",
        "review_gate",
        "sandbox_execution",
        "verification",
        "regression_check",
    ):
        assert stage in by_stage, f"no event was emitted for {stage}"
        assert any(
            event.status is EventStatus.RUNNING for event in by_stage[stage]
        ), f"{stage} never reported that it was running"

    # ...and closed with a duration the interface can display as measured.
    for stage in ("classified", "sandbox_execution", "verification", "regression_check"):
        terminal = [e for e in by_stage[stage] if e.status is not EventStatus.RUNNING]
        assert terminal, f"{stage} never reported a result"
        assert any(
            isinstance(event.metadata.get("duration_ms"), int) for event in terminal
        ), f"{stage} reported no measured duration"

    # Verification carries both sides of the comparison, so the panel can show the real delta.
    verify = [e for e in by_stage["verification"] if e.status is not EventStatus.RUNNING][-1]
    assert verify.metadata["original_error_resolved"] is True
    assert "failed" in str(verify.metadata["reproduce"])
    assert "failed" in str(verify.metadata["verify"])


def test_failed_repair_and_rollback_are_equally_observable(scenario, demo_repo: Path) -> None:
    """Spec: a rollback must be as visible as a recovery.

    Nothing about a failed run may be silent — the operator has to see the attempt fail, the
    verification fail and the rollback run, in that order, without reading a log file.
    """
    scenario("concurrency")
    setup_logging()
    rollout_settings = Settings(
        max_repair_attempts=1,
        regression_flake_reruns=0,
        code_review_enabled=True,
        convention_memory_enabled=False,
        sandbox_backend="local",
        require_approval_for_rollback=False,
    )
    llm = ScriptedLLM({"classify": _classify_payload(), "generate_patch": _no_op_patch})
    agent = SREAgent(settings=rollout_settings, llm=llm, memory=None)

    result = agent.run_incident(
        Incident(
            repository=demo_repo.name,
            error="RedisConnectionError: connection pool exhausted",
            trigger="test-run",
            previous_good_commit="good",
        )
    )

    assert result.outcome is not Outcome.RECOVERED
    rollback = [event for event in result.events if event.stage.value == "rollback"]
    assert rollback, "the rollback produced no event at all"
    assert any(
        event.status is EventStatus.RUNNING for event in rollback
    ), "the rollback never announced that it had started"
    assert any(
        event.status is not EventStatus.RUNNING for event in rollback
    ), "the rollback never reported its result"

    # The verification step must have reported the failure, not stayed silent about it.
    verify = [event for event in result.events if event.stage.value == "verification"]
    assert any(event.status is EventStatus.FAILED for event in verify)


def test_credential_failure_escalates_without_patching(scenario, demo_repo: Path) -> None:
    scenario("auth")
    setup_logging()
    settings = Settings(
        max_repair_attempts=2,
        sandbox_backend="local",
        convention_memory_enabled=False,
    )
    llm = ScriptedLLM({"classify": {
        "error_class": "auth-credential",
        "confidence": 0.97,
        "reasoning": "the billing token expired; HTTP 401 is not a code defect",
        "affected_files": ["app/billing.py"],
        "likely_fixability": "escalate",
        "evidence_required": ["which credential failed"],
    }})
    agent = SREAgent(settings=settings, llm=llm, memory=None)

    incident = Incident(
        repository=demo_repo.name,
        error="AuthenticationError: billing API token expired (HTTP 401)",
        trigger="test-run",
        previous_good_commit="good",
    )

    result = agent.run_incident(incident)

    assert result.outcome is Outcome.ESCALATED
    assert result.attempts == [], "no patch may be attempted for a credential failure"
    assert "cannot fix" in result.escalation_reason
    assert any(event.stage.value == "escalated" for event in result.events)


def test_degraded_run_is_reported_honestly(agent_settings: Settings, demo_repo: Path) -> None:
    """With no memory layer the run must still complete, and must say so."""
    setup_logging()
    llm = ScriptedLLM({"classify": _classify_payload(), "generate_patch": _fix_concurrency_patch})
    agent = SREAgent(settings=agent_settings, llm=llm, memory=None)

    result = agent.run_incident(
        Incident(repository=demo_repo.name, error="boom", trigger="test-run",
                 previous_good_commit="good")
    )

    assert result.metrics.memories_recalled == 0
    assert any(event.stage.value == "recalling_memory" for event in result.events)
