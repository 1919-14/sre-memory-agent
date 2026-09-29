"""Concrete sandbox backends."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import IO

from ..logging_setup import get_logger
from ..models import TestReport
from ..tools.test_runner import run_pytest
from .base import SandboxError, TestBackend

log = get_logger("sandbox")

SANDBOX_IMAGE_DEFAULT = "sre-memory-agent/sandbox:pytest"

# ── How the workspace reaches the container ──────────────────
# A bind mount (`-v <workspace>:/workspace`) means what it says only while the daemon shares
# this filesystem. Point the backend at a *remote* daemon — `DOCKER_HOST=ssh://…` or
# `tcp://…`, the only way to get container isolation from an environment that cannot run a
# daemon itself, such as a Hugging Face Space — and the same command silently mounts a path
# that does not exist over there: the container gets an empty directory, and pytest reports
# failures that say nothing about the code under test. So a daemon that is not local gets the
# workspace streamed into it instead, and the resulting verdict is the one the run claims.
_DOCKER_HOST_ENV = "DOCKER_HOST"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}
# Ephemeral, writable and bounded: the streamed archive is extracted here and lives only for
# the container's lifetime, never on the daemon's disk. Sized below the container's memory
# limit because tmpfs pages are charged to the same cgroup.
_COPY_TMPFS = "/workspace:rw,size=512m,mode=1777"
_COPY_SIZE_CAP = 256 * 1024 * 1024
# Directories and files a test run never needs. `prepare_workspace` has already filtered the
# heavy ones out; this second pass covers what a previous stage wrote back (bytecode caches).
_ARCHIVE_SKIP = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"})

# Extraction is done by the sandbox image's own Python rather than `tar(1)`, because the image
# contract is "a Python interpreter with pytest" and nothing more. `execvp` replaces this
# process, so pytest's exit code is the container's. Written without indentation: this string
# is passed to `python -c`, where a leading space would be a syntax error.
_EXTRACT_AND_EXEC = (
    "import os, sys, tarfile\n"
    "try:\n"
    "    tarfile.open(fileobj=sys.stdin.buffer, mode='r|').extractall('/workspace')\n"
    "except Exception as exc:\n"
    "    print(f'sandbox workspace transfer failed: {exc}', file=sys.stderr)\n"
    "    raise SystemExit(126)\n"
    "os.execvp(sys.argv[1], sys.argv[1:])\n"
)


def _skip_in_archive(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if any(part in _ARCHIVE_SKIP for part in Path(info.name).parts):
        return None
    if info.name.endswith((".pyc", ".pyo")):
        return None
    return info


def _workspace_archive(workspace: Path) -> Path:
    """Tar the workspace for a daemon that cannot see this filesystem.

    Returned as a file rather than bytes so the transfer can stream it straight through
    without holding a copy in memory. The caller removes it.
    """
    handle = tempfile.NamedTemporaryFile(suffix=".tar", delete=False)
    path = Path(handle.name)
    try:
        with handle, tarfile.open(fileobj=handle, mode="w") as archive:
            for entry in sorted(workspace.iterdir()):
                archive.add(entry, arcname=entry.name, filter=_skip_in_archive)
        size = path.stat().st_size
        if size > _COPY_SIZE_CAP:
            raise SandboxError(
                f"workspace archive is {size / 1_048_576:.0f} MiB, over the "
                f"{_COPY_SIZE_CAP // 1_048_576} MiB transfer cap — raise it or run the sandbox "
                f"on a local Docker daemon so the workspace can be mounted"
            )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


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
    """Runs pytest inside a container with no network and hard resource caps.

    Works against any daemon the Docker CLI can reach, local or remote, because generated
    code has to be isolated even where a daemon cannot run — on a Hugging Face Space, for
    instance. Which daemon and which transfer mode are used is reported by `available()` and
    by `daemon_endpoint()`/`transfer_mode()`, so a run never claims more isolation than it had.
    """

    name = "docker"
    isolated = True

    def __init__(self, settings=None, image: str = "") -> None:
        super().__init__(settings)
        # `SANDBOX_IMAGE` is authoritative: it must match the image actually built on the
        # daemon, so an operator pointing at a different repository's image gets that one.
        self.image = image or self.settings.sandbox_image or SANDBOX_IMAGE_DEFAULT

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

    def image_runs_pytest(self) -> tuple[bool, str]:
        """Check the image can import pytest, not merely that its tag exists.

        A tag that cannot run the suites is easy to have — the sandbox's own base image
        (`python:3.12-slim`) looks like the answer and has no pytest — and the cost of not
        checking is the worst kind of evidence: every suite failing in a way that reads as
        broken code. One container start turns that into a named misconfiguration.
        """
        try:
            proc = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    self.settings.sandbox_network,
                    self.image,
                    "python",
                    "-c",
                    "import pytest",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"could not start {self.image!r}: {exc}"
        if proc.returncode != 0:
            lines = [line for line in (proc.stderr or "").strip().splitlines() if line.strip()]
            reason = lines[-1] if lines else "no output"
            return False, f"image {self.image!r} cannot import pytest ({reason})"
        return True, f"image {self.image}"

    def daemon_endpoint(self) -> str:
        """The daemon this backend talks to, named the way the Docker CLI names it."""
        return os.environ.get(_DOCKER_HOST_ENV, "").strip() or "the local daemon"

    def daemon_is_remote(self) -> bool:
        """True when `DOCKER_HOST` names a daemon this process shares no filesystem with.

        `DOCKER_HOST` is the CLI's own switch, so it is also how a Space is pointed at a
        daemon elsewhere (or at a Docker Desktop install over SSH); reading it here keeps one
        source of truth instead of a second setting that could disagree with the CLI.
        """
        host = os.environ.get(_DOCKER_HOST_ENV, "").strip()
        if not host or host.startswith(("unix://", "npipe://")):
            return False
        # ssh://user@host:port and tcp://host:port both reduce to a hostname.
        hostname = host.split("://", 1)[-1].split("@")[-1].split(":")[0].strip("/")
        return hostname not in _LOCAL_HOSTS

    def transfer_mode(self) -> str:
        """`copy` (stream the workspace in) or `mount` (bind-mount it)."""
        if self.settings.sandbox_copy_repo:
            return "copy"
        if self.daemon_is_remote():
            # Mounting here would run pytest against an empty directory and look like a pass
            # or a failure of the code. Never silent.
            log.warning(
                "SANDBOX_COPY_REPO is off but the sandbox daemon at %s cannot see this "
                "filesystem; streaming the workspace in instead of mounting it",
                self.daemon_endpoint(),
            )
            return "copy"
        return "mount"

    def available(self) -> tuple[bool, str]:
        ok, detail = self.daemon_running()
        if not ok:
            return False, detail
        if not self.image_exists():
            return False, (
                f"Sandbox image {self.image!r} is not built on {self.daemon_endpoint()}. "
                "Build it there with: docker build -f docker/sandbox.Dockerfile -t "
                f"{self.image} docker/"
            )
        usable, reason = self.image_runs_pytest()
        if not usable:
            return False, reason
        return (
            True,
            f"{detail} at {self.daemon_endpoint()}; {reason}; workspace {self.transfer_mode()}",
        )

    # ── execution ───────────────────────────────────────────
    def _build_command(self, workspace: Path, pytest_args: list[str], *, copy: bool) -> list[str]:
        """The `docker run` for one stage, in whichever transfer mode applies."""
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
        ]
        if copy:
            # `-i` because the workspace archive arrives on stdin; `--tmpfs` because the daemon
            # has no copy of it on disk, and nothing extracted should outlive the stage.
            cmd += ["-i", "--tmpfs", _COPY_TMPFS]
        else:
            cmd += ["-v", f"{workspace}:/workspace"]
        cmd += ["-w", "/workspace", self.image]
        if copy:
            cmd += ["python", "-c", _EXTRACT_AND_EXEC, *pytest_args]
        else:
            cmd += pytest_args
        return cmd

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
        copy = self.transfer_mode() == "copy"
        cmd = self._build_command(workspace, pytest_args, copy=copy)

        import time

        started = time.perf_counter()
        archive: Path | None = None
        stdin: IO[bytes] | None = None
        if copy:
            try:
                archive = _workspace_archive(workspace)
            except (OSError, SandboxError) as exc:
                return TestReport(
                    suite_label=label,
                    exit_code=125,
                    exit_reason="docker-error",
                    raw_output=f"could not prepare the workspace transfer: {exc}",
                    duration=time.perf_counter() - started,
                )
            stdin = archive.open("rb")
        try:
            proc = subprocess.run(
                cmd,
                stdin=stdin,
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
        finally:
            if stdin is not None:
                stdin.close()
            if archive is not None:
                archive.unlink(missing_ok=True)

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
            docker.reason = detail
            return docker, warnings
        warnings.append(f"SANDBOX_BACKEND=docker is not usable ({detail}); using the local backend.")
        local.reason = f"container isolation was requested but is not usable: {detail}"
        return local, warnings

    if preference == "local":
        # Chosen, not fallen back to — and still reported. An agent running generated code
        # outside a container is degraded whoever decided that, and the reason has to reach
        # the dashboard or the badge is an unexplained warning sign.
        local.reason = "SANDBOX_BACKEND=local: container isolation is switched off in configuration"
        warnings.append(
            "SANDBOX_BACKEND=local is set, so generated code runs in a temporary workspace "
            "instead of a container."
        )
        return local, warnings

    # auto
    ok, detail = docker.available()
    if ok:
        docker.reason = detail
        return docker, warnings
    local_ok, local_detail = local.available()
    if not local_ok:
        warnings.append(f"Local sandbox unavailable: {local_detail}")
    warnings.append(f"Docker sandbox unavailable ({detail}); running with local isolation.")
    local.reason = (
        f"no Docker daemon answered ({detail}), so generated code runs in a temporary "
        "workspace instead of a container"
    )
    return local, warnings
