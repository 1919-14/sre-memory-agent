"""The Docker sandbox, including the case where the daemon is not on this machine.

`docker run -v <workspace>:/workspace` is only meaningful while the daemon shares this
filesystem. Point it at a remote daemon — which is the only way to run generated code in a
container where a daemon cannot run at all, such as a Hugging Face Space — and the mount
resolves to nothing: the container sees an empty directory, and every suite fails for a reason
that has nothing to do with the code. These tests pin the behaviour that prevents that:
a remote daemon gets the workspace streamed in, and never a mount.
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from sre_agent.config import Settings
from sre_agent.sandbox import backends
from sre_agent.sandbox.backends import DockerBackend, _workspace_archive
from sre_agent.sandbox.executor import SandboxExecutor


def _backend(monkeypatch: pytest.MonkeyPatch, **env: str) -> DockerBackend:
    for name in ("DOCKER_HOST",):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        if value:
            monkeypatch.setenv(name, value)
    return DockerBackend(Settings(sandbox_image="sandbox:pytest", sandbox_copy_repo=True))


# ── which daemon, and therefore which transfer ───────────────


@pytest.mark.parametrize(
    ("host", "remote"),
    [
        ("", False),  # no DOCKER_HOST: the default daemon, reachable over a local socket
        ("unix:///var/run/docker.sock", False),
        ("npipe:////./pipe/docker_engine", False),
        ("tcp://localhost:2375", False),
        ("tcp://127.0.0.1:2376", False),
        ("tcp://10.0.0.5:2376", True),
        ("ssh://user@example.com", True),
        ("ssh://user@example.com:22", True),
        ("ssh://user@localhost", False),
    ],
)
def test_daemon_is_remote_only_for_another_machine(
    monkeypatch: pytest.MonkeyPatch, host: str, remote: bool
) -> None:
    backend = _backend(monkeypatch, DOCKER_HOST=host)

    assert backend.daemon_is_remote() is remote


def test_remote_daemon_forces_the_workspace_to_be_streamed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mounting here would test an empty directory, so the setting cannot switch it off."""
    backend = _backend(monkeypatch, DOCKER_HOST="ssh://user@builder.example.com")
    backend.settings.sandbox_copy_repo = False

    assert backend.transfer_mode() == "copy"


def test_local_daemon_may_mount_the_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _backend(monkeypatch)
    backend.settings.sandbox_copy_repo = False

    assert backend.transfer_mode() == "mount"
    assert backend.daemon_endpoint() == "the local daemon"


def test_daemon_endpoint_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _backend(monkeypatch, DOCKER_HOST="tcp://10.0.0.5:2376")

    assert backend.daemon_endpoint() == "tcp://10.0.0.5:2376"


# ── the container command ────────────────────────────────────


def _argv(
    monkeypatch: pytest.MonkeyPatch, backend: DockerBackend, copy: bool, workspace: Path
) -> list[str]:
    monkeypatch.setattr(backend, "transfer_mode", lambda: "copy" if copy else "mount")
    return backend._build_command(workspace, ["python", "-m", "pytest", "-q"], copy=copy)


def test_copy_mode_streams_the_workspace_into_an_ephemeral_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _backend(monkeypatch, DOCKER_HOST="ssh://user@builder.example.com")

    argv = _argv(monkeypatch, backend, copy=True, workspace=tmp_path / "ws")

    assert "-i" in argv, "the archive has to arrive on stdin"
    assert "--tmpfs" in argv, "the extraction target must be writable and disposable"
    assert argv[argv.index("--tmpfs") + 1] == backends._COPY_TMPFS
    assert "-v" not in argv, "a bind mount would be empty on the daemon"
    assert "-w" in argv and argv[argv.index("-w") + 1] == "/workspace"
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
    # pytest still runs as pytest: the extractor execs the arguments after it.
    extractor = argv.index(backends._EXTRACT_AND_EXEC)
    assert argv[extractor - 2 : extractor + 1] == ["python", "-c", backends._EXTRACT_AND_EXEC]
    assert argv[extractor + 1 : extractor + 4] == ["python", "-m", "pytest"]
    assert backends._EXTRACT_AND_EXEC.splitlines()[0].startswith("import os, sys, tarfile")
    assert "extractall('/workspace')" in backends._EXTRACT_AND_EXEC
    assert "execvp" in backends._EXTRACT_AND_EXEC


def test_extractor_script_is_valid_python() -> None:
    """`python -c` rejects indentation, which a reformat of this string could easily add."""
    compile(backends._EXTRACT_AND_EXEC, "<sandbox-extract>", "exec")


def test_mount_mode_bind_mounts_the_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _backend(monkeypatch)
    workspace = tmp_path / "ws"

    argv = _argv(monkeypatch, backend, copy=False, workspace=workspace)

    assert argv[argv.index("-v") + 1] == f"{workspace}:/workspace"
    assert "--tmpfs" not in argv
    assert "-i" not in argv, "nothing is streamed in mount mode"
    image = argv.index("sandbox:pytest")
    assert argv[image + 1 : image + 4] == ["python", "-m", "pytest"]


# ── the archive ──────────────────────────────────────────────


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    (workspace / "src").mkdir(parents=True)
    (workspace / "tests").mkdir()
    (workspace / "__pycache__").mkdir()
    (workspace / ".git").mkdir()
    (workspace / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    test_file = workspace / "tests" / "test_app.py"
    test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (workspace / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"\x00cached")
    (workspace / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    return workspace


def test_archive_carries_the_sources_and_leaves_the_caches(tmp_path: Path) -> None:
    archive = _workspace_archive(_workspace(tmp_path))
    try:
        with tarfile.open(archive) as handle:
            names = set(handle.getnames())
    finally:
        archive.unlink(missing_ok=True)

    assert {"src", "src/app.py", "tests", "tests/test_app.py"} <= names
    assert not any(".git" in name for name in names)
    assert not any(".pyc" in name for name in names)
    assert not any("__pycache__" in name for name in names)


# ── capability checks and failure reporting ──────────────────


class _Completed:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_image_that_cannot_import_pytest_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sandbox's own base image is the easy mistake, and it has no pytest."""
    backend = _backend(monkeypatch)

    def fake_run(argv, **_kwargs):  # noqa: ANN001, ANN202
        if argv[1] == "info":
            return _Completed(0, stdout="27.3.1\n")
        if argv[1] == "image":
            return _Completed(0, stdout="[]")
        if argv[1] == "run":
            return _Completed(1, stderr="ModuleNotFoundError: No module named 'pytest'\n")
        raise AssertionError(f"unexpected docker invocation: {argv}")

    monkeypatch.setattr(backends.subprocess, "run", fake_run)

    usable, detail = backend.available()

    assert usable is False
    assert "cannot import pytest" in detail
    assert "No module named 'pytest'" in detail


def test_oversized_workspace_is_reported_rather_than_mounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Too big to stream is a sandbox error, not a silent downgrade to a bind mount."""
    backend = _backend(monkeypatch)
    monkeypatch.setattr(backends, "_COPY_SIZE_CAP", 8)
    workspace = _workspace(tmp_path)

    report = backend.run_tests(workspace, label="reproduce")

    assert report.exit_reason == "docker-error"
    assert "MiB transfer cap" in report.raw_output
    assert report.passed == 0


def test_copy_mode_streams_the_archive_on_stdin_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End of the chain: the archive is what docker is given, and it does not linger."""
    backend = _backend(monkeypatch)
    workspace = _workspace(tmp_path)
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN202
        captured["argv"] = argv
        stdin = kwargs.get("stdin")
        assert stdin is not None, "copy mode must hand docker the archive"
        with tarfile.open(fileobj=stdin, mode="r|") as handle:
            captured["names"] = set(handle.getnames())
        captured["archive"] = Path(stdin.name)
        return _Completed(0, stdout="1 passed in 0.02s\n")

    monkeypatch.setattr(backends.subprocess, "run", fake_run)

    report = backend.run_tests(workspace, label="verify")

    assert report.passed == 1
    assert "src/app.py" in captured["names"]
    assert not captured["archive"].exists(), "the temporary archive must be removed"
    argv = captured["argv"]
    assert argv[argv.index(backends._EXTRACT_AND_EXEC) + 1 :][:3] == ["python", "-m", "pytest"]


def test_local_backend_is_still_available_without_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fallback exists and stays reachable; it is just never passed off as isolation."""
    monkeypatch.setattr(backends.shutil, "which", lambda _name: None)
    monkeypatch.delenv("DOCKER_HOST", raising=False)

    backend, warnings = backends.select_backend(Settings(sandbox_backend="auto"))

    assert backend.name == "local"
    assert any("Docker sandbox unavailable" in warning for warning in warnings)
    assert "docker executable not found" in warnings[0]


def test_a_local_fallback_explains_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """`sandbox_detail` is what turns a DEGRADED badge into an explained one."""
    monkeypatch.setattr(backends.shutil, "which", lambda _name: None)
    monkeypatch.delenv("DOCKER_HOST", raising=False)

    backend, _ = backends.select_backend(Settings(sandbox_backend="auto"))

    assert backend.name == "local"
    assert "no Docker daemon answered" in backend.reason
    assert "temporary workspace" in backend.reason


def test_configured_local_backend_is_reported_as_a_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switched off deliberately is still a missing guarantee, so it is never silent."""
    backend, warnings = backends.select_backend(Settings(sandbox_backend="local"))

    assert "switched off in configuration" in backend.reason
    assert any("SANDBOX_BACKEND=local" in warning for warning in warnings)


def test_docker_backend_reason_describes_the_daemon_it_will_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = "Docker 27.3.1 at ssh://user@builder; image sandbox:pytest; workspace copy"
    monkeypatch.setattr(DockerBackend, "available", lambda _self: (True, detail))

    backend, warnings = backends.select_backend(Settings(sandbox_backend="auto"))

    assert backend.name == "docker"
    assert backend.reason == detail
    assert warnings == []


def test_executor_carries_the_reason_the_api_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    """The chain the dashboard depends on: select_backend -> executor -> /api/status."""
    monkeypatch.setattr(backends.shutil, "which", lambda _name: None)
    monkeypatch.delenv("DOCKER_HOST", raising=False)

    executor = SandboxExecutor(Settings(sandbox_backend="auto"))

    assert executor.backend.name == "local"
    assert executor.backend.reason, "an unexplained degradation is what made the badge read as broken"


def test_binary_probe_does_not_depend_on_the_host_os() -> None:
    """Sanity: the module under test imports cleanly, on Windows and Linux alike."""
    assert DockerBackend.name == "docker"
    assert DockerBackend.isolated is True
    assert subprocess is backends.subprocess
    assert sys.platform  # the module is importable here at all
