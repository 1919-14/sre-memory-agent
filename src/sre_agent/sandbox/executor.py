"""Sandbox execution flow.

Order matters here, and the first step is the one most implementations skip:

    reproduce  -> prove the failure is real and deterministic BEFORE touching anything
    apply      -> write the proposed files into the throwaway workspace
    verify     -> run the originally failing tests
    regress    -> run the whole suite for the regression comparison

If the failure does not reproduce unpatched, the agent must not claim a fix — a test that
is already green when the fix is applied proves nothing. That case is reported, not hidden.
"""

from __future__ import annotations

import time
from pathlib import Path

from ..config import Settings, settings as default_settings
from ..logging_setup import get_logger
from ..models import Incident, Patch, SandboxResult
from ..patch.applier import apply_edits
from .backends import select_backend
from .base import SandboxError, TestBackend

log = get_logger("sandbox")


class SandboxExecutor:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        backend: TestBackend | None = None,
    ) -> None:
        self.settings = settings or default_settings
        if backend is None:
            backend, warnings = select_backend(self.settings)
            for warning in warnings:
                log.warning(warning)
            self.warnings = warnings
        else:
            self.warnings = []
        self.backend = backend

    def execute(
        self,
        incident: Incident,
        patch: Patch,
        *,
        reproduce_tests: list[str] | None = None,
        full_suite: bool | None = None,
        keep_workspace: bool = False,
    ) -> SandboxResult:
        if full_suite is None:
            full_suite = self.settings.regression_suite != "failing-only"

        started = time.perf_counter()
        result = SandboxResult(
            backend=self.backend.name,
            isolated=self.backend.isolated,
            workspace="",
        )

        tests = reproduce_tests if reproduce_tests is not None else list(incident.evidence.failing_tests)

        try:
            workspace = self.backend.prepare_workspace()
        except (SandboxError, OSError) as exc:
            result.error = f"Could not prepare the sandbox workspace: {exc}"
            result.duration_s = time.perf_counter() - started
            log.error(result.error)
            return result

        # Recorded for traceability; the directory itself is removed below unless kept.
        result.workspace = str(workspace)
        result.started = True

        try:
            # 1. Reproduce the failure BEFORE applying anything.
            if tests:
                result.reproduce_report = self.backend.run_tests(
                    workspace, nodeids=tests, label="reproduce"
                )
                result.error_reproduced = not result.reproduce_report.green
                if not result.error_reproduced:
                    log.warning(
                        "failure did NOT reproduce in the sandbox (%s); "
                        "a passing fix would not be evidence",
                        result.reproduce_report.summary_line(),
                    )

            # 2. Apply the proposed patch inside the workspace only.
            applied = apply_edits(workspace, patch.files)
            if not applied.ok:
                result.error = "Patch application failed: " + "; ".join(applied.errors)
                result.output = result.error
                result.duration_s = time.perf_counter() - started
                log.error(result.error)
                return result
            result.patch_applied = True

            # 3. Verify the originally failing tests now pass.
            if tests:
                result.test_report = self.backend.run_tests(
                    workspace, nodeids=tests, label="verify"
                )

            # 4. Full suite for the regression comparison.
            if full_suite:
                result.full_report = self.backend.run_tests(workspace, label="full")

            result.output = _combine_output(result)

            # A test run that executed nothing must never be read as a success.
            for label, report in (
                ("verify", result.test_report),
                ("full suite", result.full_report),
            ):
                if report is not None and report.total == 0:
                    result.error = (
                        f"The {label} test run executed no tests "
                        f"({report.exit_reason}); the fix cannot be verified."
                    )
                    log.error(result.error)
                    break
        except SandboxError as exc:
            result.error = str(exc)
            log.error("sandbox execution failed: %s", exc)
        except Exception as exc:  # noqa: BLE001 - a sandbox crash must not kill the run
            result.error = f"Unexpected sandbox error: {type(exc).__name__}: {exc}"
            log.exception("unexpected sandbox failure")
        finally:
            if not keep_workspace:
                self.backend.cleanup(workspace)

        result.duration_s = time.perf_counter() - started
        log.info(
            "sandbox[%s] done in %.2fs: applied=%s reproduced=%s verify=%s",
            self.backend.name,
            result.duration_s,
            result.patch_applied,
            result.error_reproduced,
            result.test_report.summary_line() if result.test_report else "n/a",
        )
        return result

    def description(self) -> str:
        return self.backend.description()


def _combine_output(result: SandboxResult) -> str:
    chunks: list[str] = []
    if result.reproduce_report is not None:
        chunks.append(
            "--- reproduce (unpatched) ---\n"
            f"{result.reproduce_report.summary_line()}\n"
            f"{result.reproduce_report.raw_output[-2000:]}"
        )
    if result.test_report is not None:
        chunks.append(
            "--- verify (patched, originally failing tests) ---\n"
            f"{result.test_report.summary_line()}\n"
            f"{result.test_report.raw_output[-2000:]}"
        )
    if result.full_report is not None:
        chunks.append(
            "--- full suite (patched) ---\n"
            f"{result.full_report.summary_line()}\n"
            f"{result.full_report.raw_output[-2000:]}"
        )
    return "\n\n".join(chunks)


def workspace_of(result: SandboxResult) -> Path | None:
    return Path(result.workspace) if result.workspace else None
