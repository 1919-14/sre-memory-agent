"""Enumerations for the SRE agent domain.

Error classes are the contract between the classifier, the specialist registry and
the Hindsight tag schema (`error-class:<value>`), so these strings must stay stable.
"""

from __future__ import annotations

from enum import Enum


class ErrorClass(str, Enum):
    """Failure taxonomy. Adding a class is a config change, never a new code path."""

    CONNECTION_EXHAUSTION = "connection-exhaustion"
    CONFIG_REGRESSION = "config-regression"
    DEPENDENCY_DRIFT = "dependency-drift"
    NULL_OR_TYPE = "null-or-type"
    SERIALIZATION_SCHEMA = "serialization-schema"
    TIMEOUT_RETRY = "timeout-retry"
    CONCURRENCY_RACE = "concurrency-race"
    BUILD_TOOLCHAIN = "build-toolchain"
    TEST_DEFECT = "test-defect"
    AUTH_CREDENTIAL = "auth-credential"
    INFRASTRUCTURE = "infrastructure"
    UNKNOWN = "unknown"


class Fixability(str, Enum):
    """Whether code can fix this at all — drives repair vs escalate."""

    CODE_FIXABLE = "code-fixable"
    ESCALATE = "escalate"
    UNKNOWN = "unknown"


class IncidentStatus(str, Enum):
    """Coarse incident state, mirrored in the dashboard."""

    DETECTED = "DETECTED"
    ANALYZING = "ANALYZING"
    CLASSIFIED = "CLASSIFIED"
    RECALLING_MEMORY = "RECALLING_MEMORY"
    GENERATING_FIX = "GENERATING_FIX"
    REVIEWING = "REVIEWING"
    SANDBOX_TESTING = "SANDBOX_TESTING"
    VERIFYING = "VERIFYING"
    RECOVERED = "RECOVERED"
    ROLLBACK_REQUIRED = "ROLLBACK_REQUIRED"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"
    NO_FAILURE = "NO_FAILURE"


class Outcome(str, Enum):
    """Terminal result. Every one of these writes memory."""

    RECOVERED = "recovered"
    ROLLED_BACK = "rolled-back"
    ESCALATED = "escalated"
    NO_FAILURE_DETECTED = "no-failure-detected"
    ABORTED = "aborted"


class Stage(str, Enum):
    """Timeline stages rendered by the incident detail view."""

    DETECTED = "incident_detected"
    CLASSIFIED = "classified"
    RECALLING = "recalling_memory"
    COMPARABILITY = "comparability_checked"
    GENERATING = "fix_generated"
    REVIEW = "review_gate"
    SANDBOX = "sandbox_execution"
    VERIFY = "verification"
    REGRESSION = "regression_check"
    RESOLVED = "resolved"
    ROLLBACK = "rollback"
    ESCALATED = "escalated"
    MEMORY = "memory_updated"


class EventStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    WARN = "warn"
    FAILED = "failed"
    SKIPPED = "skipped"


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


class AttemptSource(str, Enum):
    """Where a candidate fix came from — the memory story lives in this field."""

    HISTORICAL_FIX = "historical-fix"
    ADAPTED_HISTORICAL_FIX = "adapted-historical-fix"
    GENERATED_FIX = "generated-fix"
    SPECIALIST_FIX = "specialist-fix"


class AttemptStatus(str, Enum):
    PENDING = "pending"
    REJECTED_BY_VALIDATION = "rejected-by-validation"
    BLOCKED_BY_REVIEW = "blocked-by-review"
    VERIFICATION_FAILED = "verification-failed"
    REGRESSION_FAILED = "regression-failed"
    SANDBOX_ERROR = "sandbox-error"
    SUCCEEDED = "succeeded"


class ReviewerKind(str, Enum):
    POLICY = "policy"
    CONVENTIONS = "conventions"


class RunMode(str, Enum):
    LIVE = "live"
    REPLAY = "replay"


class SandboxBackend(str, Enum):
    DOCKER = "docker"
    LOCAL = "local"
