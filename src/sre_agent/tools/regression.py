"""Regression protection.

A repair succeeds only when BOTH hold:

    the original failure is resolved  AND  no unacceptable regression was introduced

The baseline is captured from the last known-good state, so "new failure" has a real
definition instead of being guessed from the current run.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..logging_setup import get_logger
from ..models import RegressionReport, TestReport

log = get_logger("regression")

Rerun = Callable[[list[str]], TestReport]


class RegressionChecker:
    def __init__(
        self,
        *,
        max_new_failures: int = 0,
        flake_reruns: int = 2,
        check_blast_radius: bool = True,
    ) -> None:
        self.max_new_failures = max_new_failures
        self.flake_reruns = flake_reruns
        self.check_blast_radius = check_blast_radius

    def compare(
        self,
        *,
        baseline: TestReport | None,
        after: TestReport | None,
        original_failing: list[str],
        repo_path: str | Path = "",
        changed_files: list[str] | None = None,
        rerun: Rerun | None = None,
    ) -> RegressionReport:
        report = RegressionReport()
        report.baseline_failing = sorted(set(baseline.failing_ids() if baseline else []))
        report.after_failing = sorted(set(after.failing_ids() if after else []))
        original = set(original_failing)

        if after is None:
            report.notes = "No post-fix test report was produced; cannot verify."
            report.acceptable = False
            return report

        # A run that collected nothing proves nothing. This check exists because an
        # unparseable or empty report otherwise looks exactly like a clean pass, which
        # would let the agent declare success without any test ever executing.
        if after.exit_reason in ("no-tests-ran", "no-tests-collected", "usage-error", "interrupted", "internal-error"):
            report.notes = (
                f"The post-fix test run is not trustworthy ({after.exit_reason}); "
                "no fix can be verified from it."
            )
            report.acceptable = False
            report.original_error_resolved = False
            return report

        # 1. Did the original failure actually go away?
        still_failing = original & set(report.after_failing)
        report.original_error_resolved = not still_failing

        # 2. New failures relative to the known-good baseline.
        new_failures = sorted(set(report.after_failing) - set(report.baseline_failing))
        report.resolved_failures = sorted(set(report.baseline_failing) - set(report.after_failing))

        # 3. Separate flakes from real regressions by re-running the suspects.
        if new_failures and rerun and self.flake_reruns > 0:
            for _ in range(self.flake_reruns):
                try:
                    retry = rerun(new_failures)
                except Exception as exc:  # noqa: BLE001 - never fail the run on a rerun
                    log.warning("flake rerun failed: %s", exc)
                    break
                genuinely_failing = set(retry.failing_ids()) & set(new_failures)
                for nodeid in list(new_failures):
                    if nodeid not in genuinely_failing:
                        report.flaky.append(nodeid)
                        new_failures.remove(nodeid)
                        log.info("classified as flaky (passed on rerun): %s", nodeid)
                if not new_failures:
                    break

        report.new_failures = new_failures

        if self.check_blast_radius and repo_path and changed_files:
            report.blast_radius = blast_radius(repo_path, changed_files)

        # 4. Verdict.
        acceptable = report.original_error_resolved and len(report.new_failures) <= self.max_new_failures
        if after.exit_reason == "no-tests-collected":
            acceptable = False
            report.notes = "No tests were collected — cannot verify the fix."
        elif still_failing:
            report.notes = f"Original failure still present: {', '.join(sorted(still_failing))}"
        elif report.new_failures:
            report.notes = f"Introduced {len(report.new_failures)} new failure(s): {', '.join(report.new_failures[:5])}"
        elif report.flaky:
            report.notes = f"Resolved, with {len(report.flaky)} flaky test(s) excluded"
        else:
            report.notes = "Original failure resolved with no new failures."
        report.acceptable = acceptable

        log.info(
            "regression check: acceptable=%s resolved=%s new_failures=%s",
            acceptable,
            report.original_error_resolved,
            len(report.new_failures),
        )
        return report


def blast_radius(repo_path: str | Path, changed_files: list[str], *, limit: int = 10) -> list[str]:
    """Find modules that import a changed module.

    A cheap textual dependency check — enough to warn a reviewer that a change is not
    local, without pretending to be a full static analyser.
    """
    root = Path(repo_path)
    if not root.is_dir():
        return []

    changed_stems = {
        Path(path).stem
        for path in changed_files
        if path.endswith(".py") and Path(path).stem != "__init__"
    }
    if not changed_stems:
        return []

    dependents: list[str] = []
    try:
        for candidate in root.rglob("*.py"):
            if ".venv" in candidate.parts or "venv" in candidate.parts or "__pycache__" in candidate.parts:
                continue
            relative = str(candidate.relative_to(root)).replace("\\", "/")
            if relative in changed_files:
                continue
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for stem in changed_stems:
                if f"import {stem}" in text or f"from {stem}" in text or f"from .{stem}" in text:
                    dependents.append(relative)
                    break
            if len(dependents) >= limit:
                break
    except OSError as exc:  # pragma: no cover
        log.warning("blast radius scan failed: %s", exc)
    return dependents[:limit]
