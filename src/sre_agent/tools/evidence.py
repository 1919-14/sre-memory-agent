"""Evidence collection.

Everything the agent knows about a failure before it reasons. Deliberately gathered
from real repository and test state — never invented.
"""

from __future__ import annotations

import platform
import re
import sys
from pathlib import Path

from ..logging_setup import get_logger
from ..models import Evidence, TestReport
from .git_tools import GitRepo
from .test_runner import run_pytest

log = get_logger("evidence")

_EXCEPTION_RE = re.compile(
    r"^([A-Za-z_][\w.]*(?:Error|Exception|Failure|Timeout|Exhausted|Refused|Denied|"
    r"Unavailable|Interrupt)\w*)(?::\s*(.*))?$"
)


class EvidenceCollector:
    def __init__(self, repo: GitRepo, *, python: str | None = None) -> None:
        self.repo = repo
        self.python = python or sys.executable

    def collect(
        self,
        *,
        source: str = "test-run",
        since_ref: str = "",
        previous_good: str = "",
        test_report: TestReport | None = None,
        error_override: str = "",
        logs: str = "",
        run_tests: bool = True,
    ) -> Evidence:
        report = test_report
        if report is None and run_tests:
            report = run_pytest(self.repo.path, python=self.python, suite_label="current")

        error_message, stack_trace = extract_error_from_output(report.raw_output if report else "")
        if error_override:
            error_message = error_override
        if not error_message and report is not None and report.failing_ids():
            error_message = f"Test failure in {report.failing_ids()[0]}"

        previous = previous_good or self.repo.last_known_good()
        # Diff against the last known-good commit, not the working tree: the incident is
        # caused by committed work, so `git diff <good>..HEAD` is the real evidence. An
        # empty diff here would hide the very change that caused the failure.
        since = since_ref or previous
        evidence = Evidence(
            error_message=error_message or "Unspecified failure",
            stack_trace=stack_trace,
            logs=logs,
            source=source,
            repo_path=str(self.repo.path),
            branch=self.repo.current_branch(),
            commit_sha=self.repo.current_commit() if self.repo.is_repo() else "",
            commit_message=self.repo.commit_message() if self.repo.is_repo() else "",
            previous_good_commit=previous,
            changed_files=self.repo.changed_files(since) if self.repo.is_repo() else [],
            diff=self.repo.diff(since) if self.repo.is_repo() else "",
            diff_summary=self.repo.diff_summary(since) if self.repo.is_repo() else "",
            dependency_changes=self.repo.dependency_changes(since)
            if self.repo.is_repo()
            else [],
            env_info=environment_info(),
            failing_tests=report.failing_ids() if report else [],
            test_report=report,
        )
        log.info(
            "collected evidence: %s failing test(s), %s changed file(s), error=%r",
            len(evidence.failing_tests),
            len(evidence.changed_files),
            evidence.error_message[:80],
        )
        return evidence


def environment_info() -> dict[str, str]:
    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": platform.system().lower(),
        "machine": platform.machine(),
        "env": "ci" if _looks_like_ci() else "local",
    }


def _looks_like_ci() -> bool:
    import os

    return any(os.environ.get(var) for var in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILD_ID"))


def extract_error_from_output(output: str) -> tuple[str, str]:
    """Pull the primary exception and the traceback out of pytest output.

    Prefers a recognised exception type; falls back to the last assertion-like line.
    """
    if not output:
        return "", ""

    e_lines = [line[1:].strip() for line in output.splitlines() if line.lstrip().startswith("E ")]

    primary = ""
    for line in e_lines:
        match = _EXCEPTION_RE.match(line)
        if match:
            exception, detail = match.group(1), (match.group(2) or "").strip()
            primary = f"{exception}: {detail}" if detail else exception
            break
    if not primary:
        for line in reversed(e_lines):
            if line:
                primary = line[:300]
                break

    trace = "\n".join(e_lines[:60])
    if not trace:
        # Fall back to the FAILED summary lines so we still have something concrete.
        trace = "\n".join(
            line.strip()
            for line in output.splitlines()
            if line.strip().startswith(("FAILED", "ERROR"))
        )[:2000]
    return primary, trace


def read_source_files(repo_path: str | Path, relative_paths: list[str], *, max_chars: int = 6000) -> str:
    """Concatenate the current contents of files, for LLM context."""
    root = Path(repo_path)
    chunks: list[str] = []
    for relative in relative_paths[:12]:
        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            continue  # refuse to read outside the repository
        if not target.is_file():
            continue
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) > max_chars:
            text = text[:max_chars] + "\n# … truncated …"
        chunks.append(f"### FILE: {relative}\n{text}")
    return "\n\n".join(chunks)


def find_test_files(repo_path: str | Path, failing_tests: list[str]) -> list[str]:
    """Map pytest nodeids to repository-relative test file paths."""
    files: list[str] = []
    for nodeid in failing_tests:
        path = nodeid.split("::")[0]
        if path and path not in files:
            files.append(path)
    if not files:
        tests_dir = Path(repo_path) / "tests"
        if tests_dir.is_dir():
            for candidate in sorted(tests_dir.rglob("test_*.py")):
                files.append(str(candidate.relative_to(repo_path)).replace("\\", "/"))
    return files[:10]
