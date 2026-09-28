"""Concrete sandbox backends."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from ..logging_setup import get_logger
from ..models import TestReport
from ..tools.test_runner import run_pytest
from .base import TestBackend

log = get_logger("sandbox")

SANDBOX_IMAGE_DEFAULT = "sre-memory-agent/sandbox:pytest"


class LocalBackend(TestBackend):
    """Runs pytest in a copied workspace with the current interpreter."""

    name = "local"
    isolated = False

    def __init__(self, settings=None, python: str | None = None) -> None:
        super().__init__(settings)
        self.python = python or sys.executable

    def available(self) -> tuple[bool, str]:
        if not Path(self.python).exists() and shutil.which(self.python) is None:
            return False, f"Python interpreter not found: {self.python}"
        try:
            probe = subprocess.run(
                [self.python, "-c", "import pytest"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"Could not probe {self.python}: {exc}"
        if probe.returncode != 0:
            return False, f"pytest is not importable with {self.python}"
        return True, f"pytest available via {self.python}"

    def run_tests(
        self,
        workspace: str | Path,
        *,
        nodeids: list[str] | None = None,
        label: str = "full",
        timeout: int | None = None,
    ) -> TestReport:
        return run_pytest(
            workspace,
            python=self.python,
            nodeids=nodeids,
            suite_label=label,
            timeout=timeout or self.settings.sandbox_timeout_seconds,
        )


class DockerBackend(TestBackend):
    """Runs pytest inside a container with no network and hard resource caps."""

    name = "docker"
    isolated = True

    def __init__(self, settings=None, image: str = "") -> None:
        super().__init__(settings)
        self.image = image or SANDBOX_IMAGE_DEFAULT

    # ── capability checks ───────────────────────────────────
    def _docker_binary(self) -> bool:
        return shutil.which("docker") is not None

    def daemon_running(self) -> tuple[bool, str]:
        if not self._docker_binary():
            return False, "docker executable not found on PATH"
        try:
            proc = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"docker info failed: {exc}"
        if proc.returncode != 0:
            return False, "Docker daemon is not running"
        return True, f"Docker {proc.stdout.strip()}"

    def image_exists(self) -> bool:
        try:
            proc = subprocess.run(
                ["docker", "image", "inspect", self.image],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    def available(self) -> tuple[bool, str]:
        ok, detail = self.daemon_running()
        if not ok:
            return False, detail
        if not self.image_exists():
            return False, (
                f"Sandbox image {self.image!r} is not built. "
                "Build it with: docker build -f docker/sandbox.Dockerfile -t "
                f"{self.image} docker/"
            )
        return True, f"{detail}; image {self.image}"

    # ── execution ───────────────────────────────────────────
    def run_tests(
        self,
        workspace: str | Path,
        *,
        nodeids: list[str] | None = None,
        label: str = "full",
        timeout: int | None = None,
    ) -> TestReport:
        workspace = Path(workspace).resolve()
        timeout = timeout or self.settings.sandbox_timeout_seconds

        pytest_args = [
            "python",
            "-m",
            "pytest",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            "-rf",
            "--tb=short",
            *(nodeids or []),
        ]
        cmd = [
            "docker",
            "run",
            "--rm",
            "--network",
            self.settings.sandbox_network,
            "--memory",
            self.settings.sandbox_memory_limit,
            "--cpus",
            str(self.settings.sandbox_cpus),
            "--pids-limit",
            "256",
            "-v",
            f"{workspace}:/workspace",
            "-w",
            "/workspace",
            self.image,
            *pytest_args,
        ]

        import time

        started = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout + 30,
            )
        except subprocess.TimeoutExpired:
            return TestReport(
                suite_label=label,
                exit_code=124,
                exit_reason="timeout",
                raw_output=f"docker sandbox timed out after {timeout}s",
                duration=time.perf_counter() - started,
            )
        except OSError as exc:
            return TestReport(
                suite_label=label,
                exit_code=125,
                exit_reason="docker-error",
                raw_output=f"docker could not be executed: {exc}",
                duration=time.perf_counter() - started,
            )

        from ..tools.test_runner import parse_pytest_output

        output = f"{proc.stdout}\n{proc.stderr}".strip()
        report = parse_pytest_output(output, suite_label=label, exit_code=proc.returncode)
        report.duration = time.perf_counter() - started
        log.info("docker pytest[%s] exit=%s %s", label, proc.returncode, report.summary_line())
        return report


def select_backend(settings, *, python: str | None = None) -> tuple[TestBackend, list[str]]:
    """Choose a backend according to `SANDBOX_BACKEND`, reporting any downgrade.

    Returns (backend, warnings). A downgrade from docker to local is never silent.
    """
    warnings: list[str] = []
    preference = (settings.sandbox_backend or "auto").lower()

    docker = DockerBackend(settings)
    local = LocalBackend(settings, python=python)

    if preference == "docker":
        ok, detail = docker.available()
        if ok:
            return docker, warnings
        warnings.append(f"SANDBOX_BACKEND=docker is not usable ({detail}); using the local backend.")
        return local, warnings

    if preference == "local":
        return local, warnings

    # auto
    ok, detail = docker.available()
    if ok:
        return docker, warnings
    local_ok, local_detail = local.available()
    if not local_ok:
        warnings.append(f"Local sandbox unavailable: {local_detail}")
    warnings.append(f"Docker sandbox unavailable ({detail}); running with local isolation.")
    return local, warnings
