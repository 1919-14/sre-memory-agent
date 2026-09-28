"""Parsing pytest output correctly is what stops a broken fix being called a success."""

from __future__ import annotations

from sre_agent.tools.test_runner import parse_pytest_output

QUIET_FAILING = """
....FF.......FF..                                                        [100%]
================================== FAILURES ===================================
_____________________ test_pool_size_supports_concurrency _____________________
E   AssertionError: redis_pool_size (10) is smaller than worker_concurrency (40)
=========================== short test summary info ===========================
FAILED tests/test_config.py::test_pool_size_supports_concurrency - AssertionErr...
FAILED tests/test_worker.py::test_all_jobs_complete - ValueError: redis_pool...
4 failed, 13 passed in 0.08s
"""

QUIET_PASSING = """
.................                                                        [100%]
17 passed in 0.05s
"""

VERBOSE_MIXED = """
tests/test_config.py::test_pool_size_supports_concurrency FAILED   [  5%]
tests/test_config.py::test_validate_rejects_undersized_pool PASSED [ 11%]
tests/test_worker.py::test_all_jobs_complete PASSED                [ 17%]
2 failed, 15 passed in 0.09s
"""

NO_TESTS = """
no tests ran in 0.01s
"""


def test_quiet_failing_run() -> None:
    report = parse_pytest_output(QUIET_FAILING, exit_code=1)

    assert report.exit_reason == "failed"
    assert report.failed == 4
    assert report.passed == 13
    assert report.total == 17
    assert report.duration == 0.08
    assert report.green is False
    assert "tests/test_config.py::test_pool_size_supports_concurrency" in report.failing_ids()


def test_quiet_passing_run() -> None:
    report = parse_pytest_output(QUIET_PASSING, exit_code=0)

    assert report.exit_reason == "passed"
    assert report.passed == 17
    assert report.green is True
    assert report.failing_ids() == []


def test_verbose_output_is_parsed() -> None:
    """Verbose runs put the status after the nodeid; parsing must handle both orders."""
    report = parse_pytest_output(VERBOSE_MIXED, exit_code=1)

    assert report.failed == 2
    assert report.passed == 15
    assert report.failing_ids() == ["tests/test_config.py::test_pool_size_supports_concurrency"]


def test_empty_report_is_not_treated_as_green() -> None:
    """A run that executed nothing must never look like a pass."""
    report = parse_pytest_output(NO_TESTS, exit_code=5)

    assert report.total == 0
    assert report.exit_reason == "no-tests-collected"
    assert report.green is False


def test_unparseable_output_is_flagged() -> None:
    """If pytest prints nothing useful, the report is untrustworthy rather than passing."""
    report = parse_pytest_output("something went sideways", exit_code=0)

    assert report.total == 0
    assert report.exit_reason == "no-tests-ran"
    assert report.green is False


def test_timeout_report() -> None:
    report = parse_pytest_output("", exit_code=124)

    assert report.green is False
    assert report.exit_reason == "no-tests-ran"
