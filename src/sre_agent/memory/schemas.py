"""Hindsight memory schema: tags, narrative rendering, and recall conversion.

Three rules drive this module:

1. **Tags scope recall; metadata is provenance.** Hindsight does not filter on
   metadata, so anything used for retrieval scope must be a tag.
2. **The tag space must generalize.** `error-class:*` lets recall find similar
   incidents; per-incident identifiers (`incident_id`, commit SHA) live in metadata so
   they cannot fragment the tag space.
3. **Retain is LLM-extracted.** Narrative structure is what produces reusable facts,
   so we retain a written incident report, never a raw diff dump.
"""

from __future__ import annotations

from datetime import timezone
from typing import Any

from ..models import AttemptStatus, Incident, MemoryRef, Outcome

# ── tag vocabulary ──────────────────────────────────────────

KIND_INCIDENT = "kind:incident"
KIND_CONVENTION = "kind:convention"
KIND_REJECTED = "kind:rejected-pattern"

_COMPONENT_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("redis", ("redis", "connection pool", "pool exhausted", "connectionpool")),
    ("database", ("postgres", "psycopg", "sqlalchemy", "deadlock", "database is locked")),
    ("config", ("config", "settings", "environment variable", "env var", "missing key")),
    ("http", ("timeout", "httpx", "requests", "connection reset", "429", "503")),
    ("cache", ("memcach", "cache")),
    ("auth", ("token", "unauthorized", "401", "403", "credential", "permission")),
    ("serialization", ("json", "pydantic", "validation", "schema", "decode", "encode")),
    ("filesystem", ("no space", "permission denied", "file not found", "disk")),
    ("concurrency", ("deadlock", "race", "lock", "thread", "worker")),
]


def derive_component(incident: Incident) -> str:
    """Best-effort component bucket used for tag-scoped recall."""
    haystack = " ".join(
        [
            incident.error or "",
            " ".join(incident.evidence.changed_files),
            incident.evidence.diff_summary or "",
            incident.evidence.error_message or "",
        ]
    ).lower()
    for component, keywords in _COMPONENT_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return component
    return "unknown"


def incident_tags(incident: Incident) -> list[str]:
    """Visibility scope for one incident. Must stay stable across runs."""
    cls = incident.error_class.value
    tags = [
        KIND_INCIDENT,
        f"error-class:{cls}",
        f"component:{derive_component(incident)}",
        f"service:{incident.repository or 'unknown'}",
    ]
    if incident.outcome:
        tags.append(f"outcome:{incident.outcome.value}")
    if incident.evidence.env_info.get("env"):
        tags.append(f"env:{incident.evidence.env_info['env']}")
    if incident.evidence.env_info.get("version"):
        tags.append(f"version:{incident.evidence.env_info['version']}")
    for test in incident.evidence.failing_tests[:3]:
        # Test-scoped tag: lets a repeated failure in the same test recall its history.
        tags.append(f"test:{test.split('::')[-1]}")
    return tags


def recall_query_tags(incident: Incident) -> list[str]:
    """What we scope a recall to.

    Recall is deliberately BROAD and judgement is strict:\n
    * `error-class:*` finds failures with the same mechanism.\n    * `component:*` finds failures in the same part of the system even when the class\n      differs (a pool exhaustion and a pool leak are different classes but the same\n      component, and that is exactly the pair the comparability judge should see).\n    * `outcome:*` is never included, so failed incidents are recallable too —\n      remembering what did not work is the point.\n    """
    tags = [
        f"service:{incident.repository or 'unknown'}",
        f"error-class:{incident.error_class.value}",
    ]
    component = derive_component(incident)
    if component != "unknown":
        tags.append(f"component:{component}")
    return tags


def convention_tags(component: str = "", language: str = "python") -> list[str]:
    tags = [KIND_CONVENTION, f"language:{language}"]
    if component:
        tags.append(f"component:{component}")
    return tags


def rejected_pattern_tags(incident: Incident) -> list[str]:
    return [
        KIND_REJECTED,
        f"error-class:{incident.error_class.value}",
        f"component:{derive_component(incident)}",
    ]


# ── narrative rendering ─────────────────────────────────────


def render_incident_document(incident: Incident) -> str:
    """Render an incident as a narrative report for Hindsight's extractor.

    Written as prose-with-structure rather than JSON: the extractor produces better
    facts (and better observations) from a readable postmortem than from a blob.
    """
    evidence = incident.evidence
    lines: list[str] = []
    lines.append(f"INCIDENT REPORT {incident.id}")
    lines.append("")

    lines.append("SYMPTOM")
    lines.append(f"Service {incident.repository} failed with: {incident.error}")
    if evidence.error_message and evidence.error_message != incident.error:
        lines.append(f"Primary error message: {evidence.error_message}")
    if evidence.failing_tests:
        lines.append(f"Failing tests: {', '.join(evidence.failing_tests)}")
    lines.append("")

    lines.append("ENVIRONMENT")
    lines.append(f"Branch {incident.branch}, commit {incident.commit_sha[:8]}")
    lines.append(f"Last known good commit: {incident.previous_good_commit[:8] or 'unknown'}")
    if evidence.env_info:
        pairs = ", ".join(f"{k}={v}" for k, v in sorted(evidence.env_info.items()))
        lines.append(f"Environment: {pairs}")
    lines.append("")

    changed = ", ".join(evidence.changed_files) or "no files detected"
    lines.append("SUSPECTED CHANGE")
    lines.append(f"Changed files: {changed}")
    if evidence.dependency_changes:
        lines.append(f"Dependency changes: {', '.join(evidence.dependency_changes)}")
    if evidence.diff_summary:
        lines.append("Diff:")
        lines.append(evidence.diff_summary)
    lines.append("")

    if incident.classification:
        c = incident.classification
        lines.append("CLASSIFICATION")
        lines.append(f"Error class: {c.error_class.value} (confidence {c.confidence:.2f})")
        if c.reasoning:
            lines.append(f"Classifier reasoning: {c.reasoning}")
        if c.affected_files:
            lines.append(f"Affected files: {', '.join(c.affected_files)}")
        lines.append("")

    if incident.root_cause:
        lines.append("ROOT CAUSE")
        lines.append(incident.root_cause)
        lines.append("")

    if incident.comparability:
        comp = incident.comparability
        lines.append("PRIOR MEMORY CHECK")
        if comp.comparable:
            lines.append(
                f"A comparable incident {comp.prior_incident_id} was found "
                f"(confidence {comp.confidence:.2f}): {comp.reason}"
            )
        else:
            lines.append(f"Prior experience was NOT applicable: {comp.reason}")
        lines.append("")

    lines.append("REPAIR ATTEMPTS")
    if incident.attempts:
        for attempt in incident.attempts:
            status = attempt.status.value.replace("-", " ").upper()
            origin = attempt.source.value.replace("-", " ")
            lines.append(f"Attempt {attempt.number} ({origin}) -> {status}")
            if attempt.patch:
                if attempt.patch.root_cause:
                    lines.append(f"  Believed root cause: {attempt.patch.root_cause}")
                if attempt.patch.proposed_fix:
                    lines.append(f"  Proposed fix: {attempt.patch.proposed_fix}")
                if attempt.patch.files:
                    paths = ", ".join(f.path for f in attempt.patch.files)
                    lines.append(f"  Files changed: {paths}")
            if attempt.review and not attempt.review.approved:
                lines.append(f"  Review blocked it: {attempt.review.summary}")
            if attempt.regression:
                reg = attempt.regression
                outcome_txt = "no regression" if reg.acceptable else "regression detected"
                extra = f" new failures: {', '.join(reg.new_failures)}" if reg.new_failures else ""
                lines.append(f"  Verification: {outcome_txt}.{extra}")
            if attempt.sandbox and attempt.sandbox.test_report:
                lines.append(f"  Tests: {attempt.sandbox.test_report.summary_line()}")
            if attempt.error:
                lines.append(f"  Failure detail: {attempt.error}")
    else:
        lines.append("No repair attempt was made before this record was written.")
    lines.append("")

    lines.append("VERIFICATION")
    lines.append(incident.verification or "No verification recorded.")
    lines.append("")

    lines.append("RESOLUTION")
    lines.append(f"Final resolution: {incident.final_resolution or 'none'}")
    lines.append(f"Outcome: {incident.outcome.value if incident.outcome else 'in progress'}")
    if incident.escalation_reason:
        lines.append(f"Escalated because: {incident.escalation_reason}")
    if incident.rollback_commit:
        lines.append(f"Rolled back to commit: {incident.rollback_commit[:8]}")

    return "\n".join(lines)


def incident_metadata(incident: Incident) -> dict[str, str]:
    """Provenance only — never used for filtering (Hindsight filters on tags)."""
    meta = {
        "incident_id": incident.id,
        "commit": incident.commit_sha or "",
        "previous_good_commit": incident.previous_good_commit or "",
        "repository": incident.repository or "",
        "error_class": incident.error_class.value,
        "attempts": str(len(incident.attempts)),
        "outcome": incident.outcome.value if incident.outcome else "",
        "run_mode": incident.run_mode.value,
    }
    return {k: v for k, v in meta.items() if v}


def render_rejected_pattern(incident: Incident, patch_summary: str, summary: str, rules: list[str]) -> str:
    return "\n".join(
        [
            "CODE REVIEW OUTCOME — PATCH REJECTED BEFORE EXECUTION",
            f"Repository: {incident.repository}",
            f"Error class: {incident.error_class.value}",
            f"Patch under review: {patch_summary}",
            f"Reviewer summary: {summary}",
            "Rules violated:",
            *[f"- {rule}" for rule in rules],
        ]
    )


# ── recall conversion ───────────────────────────────────────


def _score_of(result: Any) -> float:
    scores = getattr(result, "scores", None)
    if scores is None:
        return 0.0
    if isinstance(scores, dict):
        for key in ("final", "rerank", "total", "score"):
            if key in scores and scores[key] is not None:
                try:
                    return float(scores[key])
                except (TypeError, ValueError):
                    continue
        numeric = [
            float(v) for v in scores.values() if isinstance(v, (int, float))
        ]
        return max(numeric) if numeric else 0.0
    for attr in ("final", "rerank", "total"):
        value = getattr(scores, attr, None)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def to_memory_ref(result: Any, *, retrieved_for: str = "") -> MemoryRef:
    """Convert a Hindsight RecallResult into our domain model."""
    return MemoryRef(
        memory_id=str(getattr(result, "id", "") or ""),
        text=str(getattr(result, "text", "") or ""),
        kind=str(getattr(result, "type", "") or ""),
        document_id=getattr(result, "document_id", None),
        context=getattr(result, "context", None),
        tags=list(getattr(result, "tags", None) or []),
        metadata=dict(getattr(result, "metadata", None) or {}),
        relevance=_score_of(result),
        occurred_start=_iso(getattr(result, "occurred_start", None)),
        mentioned_at=_iso(getattr(result, "mentioned_at", None)),
        source_fact_ids=list(getattr(result, "source_fact_ids", None) or []),
        retrieved_for=retrieved_for,
    )


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "astimezone"):
        try:
            return value.astimezone(timezone.utc).isoformat()
        except (ValueError, OverflowError):
            return str(value)
    return str(value)


def attempt_sort_key(status: AttemptStatus) -> int:
    return {
        AttemptStatus.SUCCEEDED: 100,
        AttemptStatus.REJECTED_BY_VALIDATION: 20,
        AttemptStatus.BLOCKED_BY_REVIEW: 30,
        AttemptStatus.VERIFICATION_FAILED: 0,
        AttemptStatus.REGRESSION_FAILED: 0,
        AttemptStatus.SANDBOX_ERROR: 0,
        AttemptStatus.PENDING: -1,
    }[status]


def outcome_is_success(outcome: Outcome | None) -> bool:
    return outcome is Outcome.RECOVERED
