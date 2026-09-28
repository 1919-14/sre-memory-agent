"""Core domain models.

These are the contract between the agent orchestrator, the API layer and the
frontend. Everything the UI renders comes from one of these objects.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    AttemptSource,
    AttemptStatus,
    ErrorClass,
    EventStatus,
    Fixability,
    IncidentStatus,
    Outcome,
    ReviewDecision,
    ReviewerKind,
    RunMode,
    Severity,
    Stage,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class ExecutionEvent(BaseModel):
    """One step in the agent's observable trajectory."""

    model_config = ConfigDict(use_enum_values=False)

    id: str = Field(default_factory=lambda: new_id("evt"))
    incident_id: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)
    stage: Stage
    status: EventStatus = EventStatus.OK
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TestCaseResult(BaseModel):
    # `__test__ = False` keeps pytest from trying to collect these model classes.
    __test__ = False

    nodeid: str
    outcome: str  # passed | failed | error | skipped
    message: str = ""
    duration: float = 0.0


class TestReport(BaseModel):
    """Result of one pytest invocation. The unit of regression comparison."""

    __test__ = False

    suite_label: str = "full"
    exit_code: int = 0
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration: float = 0.0
    cases: list[TestCaseResult] = Field(default_factory=list)
    raw_output: str = ""
    exit_reason: str | None = None
    # Set only on the "after" report: which tests improved/worsened vs baseline.
    new_failures: list[str] = Field(default_factory=list)
    resolved_failures: list[str] = Field(default_factory=list)

    @property
    def green(self) -> bool:
        """True only when tests actually ran and none failed.

        `total > 0` is essential: an empty or unparseable run exits 0 with no failures,
        which would otherwise read as a clean pass and let an unverified fix be declared
        successful.
        """
        return (
            self.total > 0
            and self.exit_code == 0
            and self.failed == 0
            and self.errors == 0
        )

    def failing_ids(self) -> list[str]:
        return sorted(
            c.nodeid for c in self.cases if c.outcome in ("failed", "error")
        )

    def summary_line(self) -> str:
        return (
            f"{self.passed} passed, {self.failed} failed, "
            f"{self.errors} errors, {self.skipped} skipped"
        )


class Evidence(BaseModel):
    """Everything the agent knows about the failure before it reasons about it."""

    error_message: str = ""
    stack_trace: str = ""
    logs: str = ""
    source: str = "manual"  # manual | test-run | ci | log-input
    repo_path: str = ""
    branch: str = ""
    commit_sha: str = ""
    commit_message: str = ""
    previous_good_commit: str = ""
    changed_files: list[str] = Field(default_factory=list)
    diff: str = ""
    diff_summary: str = ""
    dependency_changes: list[str] = Field(default_factory=list)
    env_info: dict[str, str] = Field(default_factory=dict)
    failing_tests: list[str] = Field(default_factory=list)
    test_report: TestReport | None = None

    def compact(self) -> str:
        """Token-conscious view used in LLM prompts."""
        parts = [
            f"Error: {self.error_message}",
            f"Commit: {self.commit_sha[:8] or 'unknown'}",
            f"Changed files: {', '.join(self.changed_files) or 'none detected'}",
        ]
        if self.failing_tests:
            parts.append(f"Failing tests: {', '.join(self.failing_tests[:10])}")
        if self.diff_summary:
            parts.append(f"Diff summary:\n{self.diff_summary}")
        if self.stack_trace:
            parts.append(f"Stack trace (tail):\n{self.stack_trace[-1500:]}")
        return "\n".join(parts)


class Classification(BaseModel):
    error_class: ErrorClass = ErrorClass.UNKNOWN
    confidence: float = 0.0
    reasoning: str = ""
    affected_files: list[str] = Field(default_factory=list)
    likely_fixability: Fixability = Fixability.UNKNOWN
    specialist: str | None = None
    evidence_required: list[str] = Field(default_factory=list)
    model: str = ""
    source: str = "llm"  # llm | heuristic | replay

    @property
    def needs_escalation(self) -> bool:
        return self.likely_fixability is Fixability.ESCALATE


class MemoryRef(BaseModel):
    """A single recalled memory and why it mattered."""

    memory_id: str = ""
    text: str = ""
    kind: str = ""  # world | experience | observation
    document_id: str | None = None
    context: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    relevance: float = 0.0
    occurred_start: str | None = None
    mentioned_at: str | None = None
    source_fact_ids: list[str] = Field(default_factory=list)
    source_facts: list[MemoryRef] = Field(default_factory=list)
    retrieved_for: str = ""  # which bank/query produced it
    influence: str = ""  # why it changed the decision


class ComparabilityCheck(BaseModel):
    """Verdict on whether a recalled incident may inform the current one."""

    comparable: bool = False
    confidence: float = 0.0
    reason: str = ""
    prior_incident_id: str | None = None
    prior_outcome: str | None = None
    prior_resolution: str | None = None
    prior_failed_fixes: list[str] = Field(default_factory=list)
    matched_on: list[str] = Field(default_factory=list)
    rejected_because: list[str] = Field(default_factory=list)
    source: str = "llm"  # llm | heuristic | replay


class FileEdit(BaseModel):
    """A proposed replacement of one file's full contents.

    The LLM returns whole files, not diffs: hand-written diffs are the single
    biggest source of broken patches. We compute the diff ourselves for display.
    """

    path: str
    content: str
    rationale: str = ""


class PatchValidation(BaseModel):
    ok: bool = False
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0


class Patch(BaseModel):
    id: str = Field(default_factory=lambda: new_id("patch"))
    incident_id: str = ""
    attempt_number: int = 1
    source: AttemptSource = AttemptSource.GENERATED_FIX
    root_cause: str = ""
    why_this_happened: str = ""
    proposed_fix: str = ""
    files: list[FileEdit] = Field(default_factory=list)
    expected_outcome: str = ""
    risk: str = ""
    test_strategy: str = ""
    diff: str = ""
    summary: str = ""
    addresses_root_cause: bool = True
    model: str = ""
    derived_from_incident: str | None = None
    latency_ms: int = 0

    def touch_paths(self) -> list[str]:
        return [f.path for f in self.files]


class ReviewFinding(BaseModel):
    severity: Severity = Severity.INFO
    rule: str = ""
    message: str = ""
    file: str | None = None
    line: int | None = None
    reviewer: ReviewerKind = ReviewerKind.POLICY
    memory_ref: str | None = None
    memory_text: str | None = None


class ReviewVerdict(BaseModel):
    decision: ReviewDecision = ReviewDecision.APPROVE
    summary: str = ""
    findings: list[ReviewFinding] = Field(default_factory=list)
    reviewers_run: list[ReviewerKind] = Field(default_factory=list)
    cycles: int = 0
    evaluated_at: datetime = Field(default_factory=utcnow)

    @property
    def max_severity(self) -> Severity:
        if not self.findings:
            return Severity.INFO
        return max((f.severity for f in self.findings), key=lambda s: s.rank)

    @property
    def approved(self) -> bool:
        return self.decision is ReviewDecision.APPROVE

    def blocked_findings(self, threshold: Severity = Severity.HIGH) -> list[ReviewFinding]:
        return [f for f in self.findings if f.severity.rank >= threshold.rank]


class RegressionReport(BaseModel):
    original_error_resolved: bool = False
    baseline_failing: list[str] = Field(default_factory=list)
    after_failing: list[str] = Field(default_factory=list)
    new_failures: list[str] = Field(default_factory=list)
    resolved_failures: list[str] = Field(default_factory=list)
    flaky: list[str] = Field(default_factory=list)
    blast_radius: list[str] = Field(default_factory=list)
    acceptable: bool = False
    notes: str = ""


class SandboxResult(BaseModel):
    backend: str = "local"
    isolated: bool = False
    started: bool = False
    patch_applied: bool = False
    # Unpatched run of the failing tests: proves the failure is real, not flaky.
    reproduce_report: TestReport | None = None
    error_reproduced: bool = False
    # Patched run of the originally failing tests: proves the fix.
    test_report: TestReport | None = None
    # Full suite after the fix: input to regression comparison.
    full_report: TestReport | None = None
    output: str = ""
    error: str | None = None
    duration_s: float = 0.0
    workspace: str = ""
    simulated: bool = False


class Attempt(BaseModel):
    """One repair attempt. Traceable, replayable, and retained to Hindsight."""

    number: int = 1
    source: AttemptSource = AttemptSource.GENERATED_FIX
    strategy: str = ""
    status: AttemptStatus = AttemptStatus.PENDING
    patch: Patch | None = None
    validation: PatchValidation | None = None
    review: ReviewVerdict | None = None
    sandbox: SandboxResult | None = None
    regression: RegressionReport | None = None
    error: str | None = None
    explanation: str = ""
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    duration_s: float = 0.0


class IncidentMetrics(BaseModel):
    attempts_used: int = 0
    memories_recalled: int = 0
    memories_reused: int = 0
    memories_rejected: int = 0
    llm_calls: int = 0
    llm_tokens: int = 0
    first_attempt_success: bool = False
    regression_rate: int = 0
    duration_s: float = 0.0


class Incident(BaseModel):
    """The central object: one failure, its investigation, and its resolution."""

    id: str = Field(default_factory=lambda: new_id("INC"))
    repository: str = ""
    repo_path: str = ""
    branch: str = ""
    commit_sha: str = ""
    previous_good_commit: str = ""
    error: str = ""
    trigger: str = "manual"

    status: IncidentStatus = IncidentStatus.DETECTED
    outcome: Outcome | None = None

    evidence: Evidence = Field(default_factory=Evidence)
    classification: Classification | None = None
    comparability: ComparabilityCheck | None = None

    memory_refs: list[MemoryRef] = Field(default_factory=list)
    convention_refs: list[MemoryRef] = Field(default_factory=list)
    rejected_memories: list[MemoryRef] = Field(default_factory=list)

    attempts: list[Attempt] = Field(default_factory=list)
    events: list[ExecutionEvent] = Field(default_factory=list)

    root_cause: str = ""
    final_resolution: str = ""
    verification: str = ""
    escalation_reason: str = ""
    rollback_commit: str = ""

    metrics: IncidentMetrics = Field(default_factory=IncidentMetrics)

    run_mode: RunMode = RunMode.LIVE
    simulated: bool = False
    # True when a dependency (Hindsight, LLM, sandbox) degraded mid-run. The UI must be
    # able to tell a clean run from a degraded one — a degraded run is never presented
    # as a normal one.
    degraded: bool = False
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None

    # ── convenience ─────────────────────────────────────────
    @property
    def error_class(self) -> ErrorClass:
        return self.classification.error_class if self.classification else ErrorClass.UNKNOWN

    @property
    def terminal(self) -> bool:
        return self.outcome is not None

    @property
    def current_attempt(self) -> Attempt | None:
        return self.attempts[-1] if self.attempts else None

    def add_event(
        self,
        stage: Stage,
        message: str,
        status: EventStatus = EventStatus.OK,
        **metadata: Any,
    ) -> ExecutionEvent:
        event = ExecutionEvent(
            incident_id=self.id,
            stage=stage,
            status=status,
            message=message,
            metadata=metadata,
        )
        self.events.append(event)
        return event

    def warn(self, message: str) -> None:
        """Record a degradation without losing the incident."""
        self.degraded = True
        if message not in self.warnings:
            self.warnings.append(message)

    def touch(self) -> None:
        if self.resolved_at:
            self.metrics.duration_s = (self.resolved_at - self.created_at).total_seconds()

    def summary_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "error": self.error[:160],
            "error_class": self.error_class.value,
            "status": self.status.value,
            "outcome": self.outcome.value if self.outcome else None,
            "attempts": len(self.attempts),
            "memories_recalled": self.metrics.memories_recalled,
            "run_mode": self.run_mode.value,
            "degraded": self.degraded,
            "created_at": self.created_at.isoformat(),
            "duration_s": round(self.metrics.duration_s, 2),
        }


class LearningStats(BaseModel):
    """Aggregate view proving the agent improves over time."""

    total_incidents: int = 0
    resolved: int = 0
    rolled_back: int = 0
    escalated: int = 0
    repair_success_rate: float = 0.0
    avg_attempts: float = 0.0
    first_attempt_success_rate: float = 0.0
    memories_recalled: int = 0
    historical_fixes_reused: int = 0
    failed_approaches_avoided: int = 0
    regression_rate: float = 0.0
    per_incident: list[dict[str, Any]] = Field(default_factory=list)


class AgentStatus(BaseModel):
    healthy: bool = True
    llm_ready: bool = False
    hindsight_ready: bool = False
    hindsight_detail: str = ""
    sandbox_backend: str = "local"
    docker_available: bool = False
    run_mode: RunMode = RunMode.LIVE
    repo_present: bool = False
    repo_path: str = ""
    repo_commit: str = ""
    active_incident_id: str | None = None
    banks: dict[str, str] = Field(default_factory=dict)
    missing_credentials: list[str] = Field(default_factory=list)
    # `notes` reports healthy facts ("Hindsight ready, banks created") and `warnings`
    # reports problems. They are separate because a readiness summary is not a warning, and
    # mixing them made the UI announce a degraded state while quoting a success message.
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    version: str = ""
    hindsight_version: str = ""
