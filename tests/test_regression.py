"""Regression detection: a fix only counts when nothing else broke."""

from __future__ import annotations

from sre_agent.models import TestCaseResult, TestReport
from sre_agent.tools.regression import RegressionChecker, blast_radius


def report(failing: list[str], passed: int = 10, exit_code: int = 1) -> TestReport:
    cases = [TestCaseResult(nodeid=node, outcome="failed") for node in failing]
    cases += [TestCaseResult(nodeid=f"t::pass{i}", outcome="passed") for i in range(passed)]
    return TestReport(
        exit_code=exit_code,
        failed=len(failing),
        passed=passed,
        cases=cases,
        exit_reason="failed" if failing else "passed",
    )


def test_original_failure_resolved_with_no_regressions() -> None:
    checker = RegressionChecker(max_new_failures=0, flake_reruns=0)

    result = checker.compare(
        baseline=report([], passed=17, exit_code=0),
        after=report([], passed=17, exit_code=0),
        original_failing=["t::failing"],
        repo_path="",
    )

    assert result.acceptable is True
    assert result.original_error_resolved is True
    assert result.new_failures == []


def test_unresolved_original_failure_is_rejected() -> None:
    checker = RegressionChecker(max_new_failures=0, flake_reruns=0)

    result = checker.compare(
        baseline=report([], passed=17, exit_code=0),
        after=report(["t::failing"], passed=16),
        original_failing=["t::failing"],
        repo_path="",
    )

    assert result.acceptable is False
    assert result.original_error_resolved is False
    assert "still present" in result.notes


def test_new_failure_blocks_the_fix() -> None:
    checker = RegressionChecker(max_new_failures=0, flake_reruns=0)

    result = checker.compare(
        baseline=report([], passed=17, exit_code=0),
        after=report(["t::newly_broken"], passed=16),
        original_failing=["t::failing"],
        repo_path="",
    )

    assert result.acceptable is False
    assert result.new_failures == ["t::newly_broken"]


def test_empty_after_report_can_never_verify_a_fix() -> None:
    """The guard against a silent false positive: nothing ran, so nothing is proven."""
    checker = RegressionChecker(max_new_failures=0, flake_reruns=0)
    empty = TestReport(exit_code=0, total=0, exit_reason="no-tests-ran")

    result = checker.compare(
        baseline=report([], passed=17, exit_code=0),
        after=empty,
        original_failing=["t::failing"],
        repo_path="",
    )

    assert result.acceptable is False
    assert result.original_error_resolved is False
    assert "not trustworthy" in result.notes


def test_flaky_failures_are_separated_from_regressions() -> None:
    checker = RegressionChecker(max_new_failures=0, flake_reruns=1)

    def rerun(_nodeids: list[str]) -> TestReport:
        return report([], passed=17, exit_code=0)

    result = checker.compare(
        baseline=report([], passed=17, exit_code=0),
        after=report(["t::flaky"], passed=16),
        original_failing=["t::failing"],
        repo_path="",
        rerun=rerun,
    )

    assert result.flaky == ["t::flaky"]
    assert result.new_failures == []
    assert result.acceptable is True


def test_missing_after_report_is_rejected() -> None:
    checker = RegressionChecker()

    result = checker.compare(
        baseline=report([], passed=17, exit_code=0),
        after=None,
        original_failing=["t::failing"],
        repo_path="",
    )

    assert result.acceptable is False


def test_blast_radius_finds_dependents(tmp_path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "app" / "worker.py").write_text(
        "from .config import VALUE\n\nprint(VALUE)\n", encoding="utf-8"
    )
    (tmp_path / "app" / "unrelated.py").write_text("x = 1\n", encoding="utf-8")

    dependents = blast_radius(tmp_path, ["app/config.py"])

    assert "app/worker.py" in dependents
    assert "app/unrelated.py" not in dependents
