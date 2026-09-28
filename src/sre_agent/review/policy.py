"""Deterministic policy reviewer.

Pure code, zero cost, zero hallucination. It runs on every patch and its high-severity
findings always block. A persuasive diff cannot argue with a regex.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..classify.taxonomy import looks_like_test_path
from ..config import Settings, settings as default_settings
from ..logging_setup import get_logger
from ..models import Incident, Patch, ReviewFinding, ReviewerKind, Severity
from ..patch.diff import line_counts
from ..patch.validator import _SECRET_PATTERNS  # shared secret patterns

log = get_logger("review-policy")

_CRITICAL_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\bos\.system\("), "no-shell-execution", "Calls os.system to run a shell command"),
    (re.compile(r"\bshell\s*=\s*True\b"), "no-shell-execution", "Runs a subprocess with shell=True"),
    (re.compile(r"\b(rm\s+-rf|shutil\.rmtree)\b"), "no-destructive-fs", "Performs a destructive filesystem operation"),
    (re.compile(r"\bDROP\s+TABLE\b|\bTRUNCATE\s+TABLE\b|\bDELETE\s+FROM\b", re.IGNORECASE),
     "no-destructive-sql", "Contains a destructive SQL statement"),
    (re.compile(r"@pytest\.mark\.(skip|xfail)"), "no-test-suppression", "Skips or xfails a test instead of fixing it"),
    (re.compile(r"\bpytest\.skip\("), "no-test-suppression", "Skips a test at runtime instead of fixing it"),
    (re.compile(r"\bgit\s+(reset\s+--hard|push\s+--force)\b"), "no-destructive-git", "Contains a destructive git command"),
    (re.compile(r"\beval\s*\(|\bexec\s*\("), "no-dynamic-execution", "Executes dynamic code"),
)

_HIGH_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"^\s*except\s*:\s*$", re.MULTILINE), "no-bare-except", "Uses a bare `except:` that hides every error"),
    (re.compile(r"^\s*except\s+Exception\s*:\s*(pass|\.\.\.)\s*$", re.MULTILINE),
     "no-swallowed-exceptions", "Swallows all exceptions with `except Exception: pass`"),
    (re.compile(r"^\s*assert\s+(True|1\s*==\s*1)\s*$", re.MULTILINE), "no-weakened-tests",
     "Weakens a test assertion to a tautology"),
    (re.compile(r"\btry:\s*\n\s*pass\b", re.MULTILINE), "no-empty-try", "Contains an empty try block"),
)

_MEDIUM_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"^\s*print\(", re.MULTILINE), "no-debug-output", "Leaves debug print output behind"),
    (re.compile(r"\bbreakpoint\(\)|\bpdb\.set_trace\(\)"), "no-debugger", "Leaves a debugger breakpoint"),
    (re.compile(r"#\s*(TODO|FIXME|XXX)", re.IGNORECASE), "no-new-todos", "Introduces a TODO/FIXME"),
    (re.compile(r"https?://(?!localhost|127\.0\.0\.1)"), "no-hardcoded-endpoints", "Hardcodes an external URL"),
)

# Bare `except Exception:` (not pass) is worth a note, not a block.
_LOW_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"^\s*except\s+Exception\b", re.MULTILINE), "narrow-exceptions",
     "Catches broad `Exception`; consider the specific error type"),
)


class PolicyReviewer:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings

    def review(
        self,
        incident: Incident,
        patch: Patch,
        *,
        blast_radius: list[str] | None = None,
    ) -> tuple[list[ReviewFinding], str]:
        findings: list[ReviewFinding] = []

        if not patch.files:
            findings.append(
                ReviewFinding(
                    severity=Severity.CRITICAL,
                    rule="patch-must-change-something",
                    message="Patch contains no file changes.",
                    reviewer=ReviewerKind.POLICY,
                )
            )

        for edit in patch.files:
            path = edit.path
            content = edit.content

            for pattern, rule, message in _CRITICAL_PATTERNS:
                if pattern.search(content):
                    findings.append(
                        ReviewFinding(severity=Severity.CRITICAL, rule=rule,
                                      message=message, file=path, reviewer=ReviewerKind.POLICY)
                    )
            for pattern in _SECRET_PATTERNS:
                if pattern.search(content):
                    findings.append(
                        ReviewFinding(
                            severity=Severity.CRITICAL,
                            rule="no-hardcoded-secrets",
                            message="Appears to contain a hardcoded secret or credential.",
                            file=path,
                            reviewer=ReviewerKind.POLICY,
                        )
                    )
                    break
            for pattern, rule, message in _HIGH_PATTERNS:
                if pattern.search(content):
                    findings.append(
                        ReviewFinding(severity=Severity.HIGH, rule=rule,
                                      message=message, file=path, reviewer=ReviewerKind.POLICY)
                    )
            for pattern, rule, message in _MEDIUM_PATTERNS:
                if pattern.search(content):
                    findings.append(
                        ReviewFinding(severity=Severity.MEDIUM, rule=rule,
                                      message=message, file=path, reviewer=ReviewerKind.POLICY)
                    )
            for pattern, rule, message in _LOW_PATTERNS:
                if pattern.search(content):
                    findings.append(
                        ReviewFinding(severity=Severity.LOW, rule=rule,
                                      message=message, file=path, reviewer=ReviewerKind.POLICY)
                    )

            if Path(path).name in ("requirements.txt", "pyproject.toml", "package.json"):
                findings.append(
                    ReviewFinding(
                        severity=Severity.MEDIUM,
                        rule="dependency-change-needs-justification",
                        message="Changes dependency metadata; confirm this is intended.",
                        file=path,
                        reviewer=ReviewerKind.POLICY,
                    )
                )

        # ── scope analysis ──────────────────────────────────
        suspected = {f.replace("\\", "/") for f in incident.evidence.changed_files}
        touched = {f.replace("\\", "/") for f in patch.touch_paths()}
        unrelated = sorted(touched - suspected) if suspected else []
        if unrelated and len(unrelated) == len(touched):
            findings.append(
                ReviewFinding(
                    severity=Severity.MEDIUM,
                    rule="fix-unrelated-files",
                    message=(
                        "The patch changes only files outside the suspected change set "
                        f"({', '.join(unrelated[:3])}). Confirm the causal link."
                    ),
                    reviewer=ReviewerKind.POLICY,
                )
            )
        elif unrelated:
            findings.append(
                ReviewFinding(
                    severity=Severity.LOW,
                    rule="fix-touches-extra-files",
                    message=f"Also modifies files outside the suspected change set: {', '.join(unrelated[:3])}",
                    reviewer=ReviewerKind.POLICY,
                )
            )

        if any(not looks_like_test_path(p) for p in touched) is False and incident.evidence.failing_tests:
            findings.append(
                ReviewFinding(
                    severity=Severity.HIGH,
                    rule="fix-must-change-source",
                    message="Patch changes only test files while the failure is in application code.",
                    reviewer=ReviewerKind.POLICY,
                )
            )

        added, removed = line_counts(patch.diff)
        if added + removed > self.settings.patch_max_lines:
            findings.append(
                ReviewFinding(
                    severity=Severity.HIGH,
                    rule="patch-too-large",
                    message=f"Patch changes {added + removed} lines, over the limit of {self.settings.patch_max_lines}.",
                    reviewer=ReviewerKind.POLICY,
                )
            )
        elif added + removed > self.settings.patch_max_lines // 2:
            findings.append(
                ReviewFinding(
                    severity=Severity.LOW,
                    rule="patch-size",
                    message=f"Patch changes {added + removed} lines; prefer the smallest possible fix.",
                    reviewer=ReviewerKind.POLICY,
                )
            )

        if blast_radius:
            findings.append(
                ReviewFinding(
                    severity=Severity.LOW,
                    rule="blast-radius",
                    message=(
                        f"{len(blast_radius)} other module(s) import the changed code: "
                        f"{', '.join(blast_radius[:4])}"
                    ),
                    reviewer=ReviewerKind.POLICY,
                )
            )

        if not patch.test_strategy.strip():
            findings.append(
                ReviewFinding(
                    severity=Severity.LOW,
                    rule="state-test-strategy",
                    message="No test strategy was stated for this fix.",
                    reviewer=ReviewerKind.POLICY,
                )
            )

        summary = _summarise(findings)
        log.info("policy review: %s finding(s) — %s", len(findings), summary)
        return findings, summary


def _summarise(findings: list[ReviewFinding]) -> str:
    if not findings:
        return "Deterministic policy checks passed with no findings."
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.severity.value] = counts.get(finding.severity.value, 0) + 1
    breakdown = ", ".join(f"{count} {severity}" for severity, count in sorted(counts.items()))
    return f"Deterministic policy checks produced {len(findings)} finding(s): {breakdown}."
