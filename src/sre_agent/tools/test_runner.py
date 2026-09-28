"""Run pytest and turn its output into a structured report.

Regression detection depends on this parsing being trustworthy: if a failure is missed
here, the agent will declare a broken fix successful. So parsing is deliberately
defensive and the raw output is always preserved alongside the parsed result.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from ..logging_setup import get_logger
from ..models import TestCaseResult, TestReport

log = get_logger("test-runner")


class TestRunnerError(RuntimeError):
    pass


# "3 failed, 24 passed, 1 skipped in 1.23s"
_COUNT_PATTERNS = {
    "passed": re.compile(r"(\d+) passed"),
    "failed": re.compile(r"(\d+) failed"),
    "errors": re.compile(r"(\d+) errors?"),
    "skipped": re.compile(r"(\d+) skipped"),
}
_DURATION_RE = re.compile(r"in (\d+\.\d+)s")

# Quiet mode lists "FAILED path::test - msg"; verbose mode lists
# "path::test FAILED [ 5%]". Support both so parsing survives a verbose run.
_SUMMARY_STATUS_RE = re.compile(r"^(FAILED|ERROR|PASSED|XPASS|XFAIL)\s+(\S+)", re.MULTILINE)
_VERBOSE_STATUS_RE = re.compile(
    r"^(\S+::\S+)\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)", re.MULTILINE
)
_NO_TESTS_RE = re.compile(r"no tests ran", re.IGNORECASE)
_STATUS_TO_OUTCOME = {
    "FAILED": "failed",
    "ERROR": "error",
    "PASSED": "passed",
    "XPASS": "passed",
    "XFAIL": "skipped",
    "SKIPPED": "skipped",
}


def parse_pytest_output(output: str, *, suite_label: str = "full", exit_code: int = 0) -> TestReport:
    """Parse pytest output into a TestReport.

    Handles both quiet ("FAILED path::test - msg") and verbose
    ("path::test FAILED") result listings.
    """
    report = TestReport(suite_label=suite_label, exit_code=exit_code, raw_output=output)

    tail = output[-4000:]
    for field, pattern in _COUNT_PATTERNS.items():
        matches = pattern.findall(tail)
        if matches:
            setattr(report, field, int(matches[-1]))

    duration = _DURATION_RE.findall(tail)
    if duration:
        try:
            report.duration = float(duration[-1])
        except ValueError:
            report.duration = 0.0

    cases: list[TestCaseResult] = []
    seen: set[str] = set()

    for status, nodeid in _SUMMARY_STATUS_RE.findall(output):
        if nodeid in seen:
            continue
        seen.add(nodeid)
        message = ""
        line_match = re.search(
            rf"^{status}\s+{re.escape(nodeid)}\s*-\s*(.+)$", output, re.MULTILINE
        )
        if line_match:
            message = line_match.group(1).strip()[:500]
        cases.append(
            TestCaseResult(
                nodeid=nodeid, outcome=_STATUS_TO_OUTCOME[status], message=message
            )
        )

    for nodeid, status in _VERBOSE_STATUS_RE.findall(output):
        if nodeid in seen:
            continue
        seen.add(nodeid)
        cases.append(
            TestCaseResult(nodeid=nodeid, outcome=_STATUS_TO_OUTCOME[status], message="")
        )
    report.cases = cases

    # Counts from the summary line are authoritative when present. Counting parsed lines
    # is only a fallback, and a report with neither is treated as untrustworthy rather
    # than as a pass.
    counted_failures = sum(1 for c in cases if c.outcome in ("failed", "error"))
    counted_passes = sum(1 for c in cases if c.outcome == "passed")
    if report.failed == 0 and report.errors == 0 and counted_failures:
        report.failed = counted_failures
    if report.passed == 0 and counted_passes:
        report.passed = counted_passes

    report.total = report.passed + report.failed + report.errors + report.skipped

    if exit_code == 5 or _NO_TESTS_RE.search(output):
        report.exit_reason = "no-tests-collected"
    elif exit_code == 2:
        report.exit_reason = "interrupted"
    elif exit_code == 3:
        report.exit_reason = "internal-error"
    elif exit_code == 4:
        report.exit_reason = "usage-error"
    elif report.total == 0:
        # Nothing ran. Treating this as a pass would let a fix be "verified" by a test
        # run that never executed a single test.
        report.exit_reason = "no-tests-ran"
    elif report.green:
        report.exit_reason = "passed"
    else:
        report.exit_reason = "failed"

    return report


def run_pytest(
    cwd: str | Path,
    *,
    python: str = "python",
    nodeids: list[str] | None = None,
    suite_label: str = "full",
    timeout: int = 300,
    extra_args: list[str] | None = None,
) -> TestReport:
    """Run pytest inside `cwd` and return a structured report.

    Never raises for failing tests — a failing suite is a valid, expected result.
    Raises TestRunnerError only when pytest could not be executed at all.
    """
    cwd = Path(cwd)
    if not cwd.exists():
        raise TestRunnerError(f"Test directory does not exist: {cwd}")

    args = [
        str(python),
        "-m",
        "pytest",
        # `-o addopts=` stops an inherited pytest configuration (e.g. this project's own
        # pyproject.toml) from leaking into the target repository's run. Without it, an
        # inherited `-q` combines with ours, suppresses the summary line, and the run
        # becomes unparseable — which previously looked like a pass.
        "-o",
        "addopts=",
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
        "-rf",
        "--tb=short",
        f"--rootdir={cwd}",
    ]
    if nodeids:
        args.extend(nodeids)
    else:
        # Collect explicitly instead of relying on discovered `testpaths`.
        args.append("tests" if (cwd / "tests").is_dir() else ".")
    if extra_args:
        args.extend(extra_args)

    # Bytecode caching is disabled on purpose. A stale __pycache__ can survive a branch
    # switch or a file rewrite when the new source has the same size and mtime second,
    # which would make the agent verify a fix against code that is not on disk. That is a
    # silent false positive, so we never let pytest write bytecode here.
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    started = time.perf_counter()
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - started
        output = f"pytest timed out after {timeout}s"
        log.error("pytest timeout in %s", cwd)
        return TestReport(
            suite_label=suite_label,
            exit_code=124,
            exit_reason="timeout",
            raw_output=output,
            duration=elapsed,
        )
    except FileNotFoundError as exc:
        raise TestRunnerError(
            f"Could not execute pytest with {python!r}: {exc}. "
            "Check SANDBOX python / venv configuration."
        ) from exc

    output = f"{proc.stdout}\n{proc.stderr}".strip()
    report = parse_pytest_output(output, suite_label=suite_label, exit_code=proc.returncode)
    log.info(
        "pytest[%s] exit=%s %s (%.2fs)",
        suite_label,
        proc.returncode,
        report.summary_line(),
        report.duration,
    )
    return report
