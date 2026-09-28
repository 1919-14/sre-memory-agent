"""The memory schema decides whether recall can generalize, so it is tested directly."""

from __future__ import annotations

from sre_agent.memory import schemas
from sre_agent.models import (
    Attempt,
    AttemptStatus,
    Classification,
    ErrorClass,
    Evidence,
    Fixability,
    Incident,
    Outcome,
    Patch,
)


def build_incident() -> Incident:
    incident = Incident(
        repository="redis-worker-app",
        error="RedisConnectionError: connection pool exhausted",
        commit_sha="a82f91cd4e0b",
        previous_good_commit="b71e20aa1c9f",
        branch="main",
        root_cause="worker concurrency exceeded the pool size",
        final_resolution="derive the pool size from the concurrency",
        verification="17 passed",
        outcome=Outcome.RECOVERED,
    )
    incident.classification = Classification(
        error_class=ErrorClass.CONNECTION_EXHAUSTION,
        confidence=0.92,
        reasoning="bounded resource over-subscribed",
        affected_files=["app/config.py"],
        likely_fixability=Fixability.CODE_FIXABLE,
    )
    incident.evidence = Evidence(
        error_message="RedisConnectionError: connection pool exhausted",
        changed_files=["app/config.py"],
        failing_tests=["tests/test_worker.py::test_all_jobs_complete"],
        diff_summary="app/config.py | 4 ++--",
        env_info={"env": "ci", "version": "2.4.0"},
    )
    incident.attempts = [
        Attempt(
            number=1,
            status=AttemptStatus.VERIFICATION_FAILED,
            patch=Patch(proposed_fix="raise the timeout", summary="raise timeout"),
            error="original failure persisted",
        )
    ]
    return incident


def test_component_is_derived_from_the_evidence() -> None:
    assert schemas.derive_component(build_incident()) == "redis"


def test_incident_tags_scope_recall_by_class_and_component() -> None:
    tags = schemas.incident_tags(build_incident())

    assert "kind:incident" in tags
    assert "error-class:connection-exhaustion" in tags
    assert "component:redis" in tags
    assert "service:redis-worker-app" in tags
    assert "outcome:recovered" in tags
    assert "env:ci" in tags


def test_recall_query_tags_are_broad_but_exclude_outcome() -> None:
    """Recall must stay open to failures too, or the agent forgets what did not work."""
    tags = schemas.recall_query_tags(build_incident())

    assert f"error-class:{ErrorClass.CONNECTION_EXHAUSTION.value}" in tags
    assert "component:redis" in tags
    assert not any(tag.startswith("outcome:") for tag in tags)


def test_incident_metadata_is_provenance_only() -> None:
    metadata = schemas.incident_metadata(build_incident())

    assert metadata["incident_id"] == build_incident().id or metadata["incident_id"].startswith("INC")
    assert metadata["commit"] == "a82f91cd4e0b"
    assert metadata["error_class"] == "connection-exhaustion"
    assert all(isinstance(value, str) for value in metadata.values())


def test_document_renders_a_readable_postmortem() -> None:
    document = schemas.render_incident_document(build_incident())

    for section in (
        "INCIDENT REPORT",
        "SYMPTOM",
        "ENVIRONMENT",
        "SUSPECTED CHANGE",
        "CLASSIFICATION",
        "ROOT CAUSE",
        "REPAIR ATTEMPTS",
        "VERIFICATION",
        "RESOLUTION",
    ):
        assert section in document
    # The failed attempt must be recorded, not just the successful path.
    assert "FAILED" in document or "failed" in document
    assert "raise the timeout" in document


def test_document_mentions_rollback_and_escalation_when_present() -> None:
    incident = build_incident()
    incident.outcome = Outcome.ROLLED_BACK
    incident.rollback_commit = "b71e20aa1c9f"
    incident.escalation_reason = "budget exhausted"

    document = schemas.render_incident_document(incident)

    assert "Rolled back to commit" in document
    assert "budget exhausted" in document


def test_rejected_pattern_document_names_the_rules() -> None:
    from sre_agent.models import ReviewVerdict

    text = schemas.render_rejected_pattern(
        build_incident(),
        patch_summary="hardcode the pool size",
        summary="rejected: conventions require a derived pool",
        rules=["[high] no-hardcoded-limits: pool size must be derived"],
    )

    assert "REJECTED" in text
    assert "no-hardcoded-limits" in text
