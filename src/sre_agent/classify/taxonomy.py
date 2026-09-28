"""Error taxonomy.

The taxonomy is data, not control flow: adding an error class must not require a new
`if` branch in the agent loop. A class optionally names a specialist, which contributes
extra evidence requirements and prompt guidance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import ErrorClass, Fixability

# Classes that code cannot safely repair. Classification still happens; the agent
# investigates, explains, and escalates instead of guessing at a patch.
ESCALATE_CLASSES: set[ErrorClass] = {
    ErrorClass.AUTH_CREDENTIAL,
    ErrorClass.INFRASTRUCTURE,
    ErrorClass.UNKNOWN,
}


@dataclass(frozen=True)
class ErrorClassSpec:
    error_class: ErrorClass
    label: str
    specialist: str | None = None
    fixability: Fixability = Fixability.CODE_FIXABLE
    evidence_required: tuple[str, ...] = ()
    guidance: str = ""
    signals: tuple[str, ...] = field(default_factory=tuple)


SPECS: tuple[ErrorClassSpec, ...] = (
    ErrorClassSpec(
        error_class=ErrorClass.CONNECTION_EXHAUSTION,
        label="Resource / connection pool exhaustion",
        specialist="connection_exhaustion",
        evidence_required=(
            "configured pool/limit size",
            "concurrency or load that consumes it",
            "whether connections are released on every path",
        ),
        guidance=(
            "Compare the pool/limit size with the concurrency that consumes it, and check "
            "every acquire path releases its resource on error too. Prefer deriving the "
            "limit from the concurrency rather than hardcoding a larger number."
        ),
        signals=(
            "connection pool",
            "pool exhausted",
            "connectionpool",
            "too many connections",
            "max_connections",
            "redisconnectionerror",
            "operationalerror",
            "queuepool limit",
            "resource exhausted",
            "too many open files",
            "emfile",
        ),
    ),
    ErrorClassSpec(
        error_class=ErrorClass.CONFIG_REGRESSION,
        label="Configuration regression",
        specialist="config_regression",
        evidence_required=(
            "the configuration value that changed",
            "the value expected by the failing code path",
        ),
        guidance=(
            "Find the config value whose change caused the failure and restore a coherent "
            "relationship between dependent settings. Do not simply revert the commit."
        ),
        signals=(
            "keyerror",
            "missing required",
            "environment variable",
            "env var",
            "not configured",
            "invalid config",
            "settings",
            "config",
            "default value",
        ),
    ),
    ErrorClassSpec(
        error_class=ErrorClass.DEPENDENCY_DRIFT,
        label="Dependency or version drift",
        evidence_required=("dependency change", "incompatible API surface"),
        guidance="Pin or adapt to the changed dependency surface.",
        signals=("importerror", "modulenotfound", "no module named", "version conflict", "cannot import"),
    ),
    ErrorClassSpec(
        error_class=ErrorClass.NULL_OR_TYPE,
        label="Null / type error",
        evidence_required=("the value that was unexpected", "the type expected"),
        guidance="Fix the data flow so the value cannot be null/ill-typed at that point.",
        signals=("nonetype", "attributeerror", "typeerror", "has no attribute", "unsupported operand"),
    ),
    ErrorClassSpec(
        error_class=ErrorClass.SERIALIZATION_SCHEMA,
        label="Serialization or schema mismatch",
        evidence_required=("expected schema", "actual payload shape"),
        guidance="Align the payload with the expected schema rather than loosening validation.",
        signals=("jsondecodeerror", "validationerror", "pydantic", "schema", "decode", "unmarshal"),
    ),
    ErrorClassSpec(
        error_class=ErrorClass.TIMEOUT_RETRY,
        label="Timeout / retry behaviour",
        evidence_required=("timeout value", "observed latency", "retry policy"),
        guidance="Fix the retry/backoff/timeout policy; do not just raise the timeout.",
        signals=("timeout", "timed out", "retry", "backoff", "deadline exceeded", "readtimeout"),
    ),
    ErrorClassSpec(
        error_class=ErrorClass.CONCURRENCY_RACE,
        label="Concurrency or race condition",
        evidence_required=("shared state", "interleaving that breaks it"),
        guidance="Protect the shared state; ordering fixes are usually safer than locks.",
        signals=("deadlock", "race", "lock", "lost update", "double", "ordering", "gather"),
    ),
    ErrorClassSpec(
        error_class=ErrorClass.BUILD_TOOLCHAIN,
        label="Build / toolchain failure",
        evidence_required=("toolchain versions", "build command"),
        guidance="Align toolchain or packaging metadata.",
        signals=("setuptools", "pip", "build", "toolchain", "wheel", "compiler", "syntaxerror"),
    ),
    ErrorClassSpec(
        error_class=ErrorClass.TEST_DEFECT,
        label="Test defect / flakiness",
        evidence_required=("why the test is wrong", "correct expectation"),
        guidance="Fix the test's expectation or setup, never by deleting or skipping it.",
        signals=("flaky", "fixture", "assertion", "wrong expected", "test itself"),
    ),
    ErrorClassSpec(
        error_class=ErrorClass.AUTH_CREDENTIAL,
        label="Authentication / credential failure",
        fixability=Fixability.ESCALATE,
        evidence_required=("which credential or scope failed",),
        guidance=(
            "Do not patch code to work around a credential problem. Escalate to a human: "
            "credentials must be rotated by the credential owner."
        ),
        signals=("401", "403", "unauthorized", "forbidden", "token expired", "invalid api key",
                 "credential", "permission denied", "expired"),
    ),
    ErrorClassSpec(
        error_class=ErrorClass.INFRASTRUCTURE,
        label="Infrastructure failure",
        fixability=Fixability.ESCALATE,
        evidence_required=("which infrastructure dependency failed",),
        guidance=(
            "This is an environment problem, not a code problem. Escalate; do not attempt a "
            "code patch that would mask it."
        ),
        signals=("no space left", "oom", "killed", "dns", "name resolution",
                 "connection refused", "network is unreachable", "service unavailable"),
    ),
)

SPEC_BY_CLASS: dict[ErrorClass, ErrorClassSpec] = {spec.error_class: spec for spec in SPECS}


def spec_for(error_class: ErrorClass) -> ErrorClassSpec:
    return SPEC_BY_CLASS.get(
        error_class,
        ErrorClassSpec(error_class=ErrorClass.UNKNOWN, label="Unknown failure",
                       fixability=Fixability.ESCALATE),
    )


def specialist_for(error_class: ErrorClass) -> str | None:
    return spec_for(error_class).specialist


def default_fixability(error_class: ErrorClass) -> Fixability:
    if error_class in ESCALATE_CLASSES:
        return Fixability.ESCALATE
    return spec_for(error_class).fixability


def class_names() -> list[str]:
    return [spec.error_class.value for spec in SPECS]


def heuristic_signals(text: str) -> list[tuple[ErrorClass, str]]:
    """Deterministic keyword hits, most specific class first.

    Used as a prior for the LLM and as the whole classifier when the LLM is unavailable.
    """
    haystack = (text or "").lower()
    hits: list[tuple[ErrorClass, str]] = []
    for spec in SPECS:
        for signal in spec.signals:
            if signal in haystack:
                hits.append((spec.error_class, signal))
                break
    return hits


def score_text(text: str) -> list[tuple[ErrorClass, int]]:
    """Count signal hits per class for tie-breaking."""
    haystack = (text or "").lower()
    scored: list[tuple[ErrorClass, int]] = []
    for spec in SPECS:
        count = sum(1 for signal in spec.signals if signal in haystack)
        if count:
            scored.append((spec.error_class, count))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


_TEST_PATH_RE = re.compile(r"(^|/)tests?/|(^|/)test_[^/]*\.py$|_test\.py$")


def looks_like_test_path(path: str) -> bool:
    return bool(_TEST_PATH_RE.search(path or ""))
