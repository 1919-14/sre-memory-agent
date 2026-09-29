"""Sandbox backends.

A backend answers one question: *how do I run this repository's test suite in
isolation?* The execution flow (reproduce, apply, verify, regress) lives in
`executor.py` so both backends behave identically.

* `LocalBackend`  — temp workspace + `pytest` via a controlled interpreter. Gives
  filesystem isolation and hard timeouts. Does NOT give resource isolation.
* `DockerBackend` — container isolation: no network, memory/CPU caps, non-root.
  Requires Docker to be running and the sandbox image to be built.

The backend actually used is always reported on `SandboxResult.backend`, so a run can
never imply stronger isolation than it had.
"""

from __future__ import annotations

import shutil
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from ..config import Settings, settings as default_settings
from ..logging_setup import get_logger
from ..models import TestReport

log = get_logger("sandbox")

_IGNORED_COPY = (
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".sandbox",
    "data",
    "web/node_modules",
    "web/dist",
)


class SandboxError(RuntimeError):
    pass


class TestBackend(ABC):
    name: str = "base"
    isolated: bool = False
    # Set by `select_backend`: why this backend was selected. Empty means "not explained yet",
    # never "nothing to explain" — the API reports it as `sandbox_detail`, so the dashboard can
    # say which guarantee is missing instead of only that one is.
    reason: str = ""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings

    @abstractmethod
    def run_tests(
        self,
        workspace: str | Path,
        *,
        nodeids: list[str] | None = None,
        label: str = "full",
        timeout: int | None = None,
    ) -> TestReport:
        """Run pytest in the workspace and return a structured report."""

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """Return (usable, reason)."""

    def description(self) -> str:
        mode = "container isolation" if self.isolated else "filesystem isolation only"
        return f"{self.name} ({mode})"

    # ── shared workspace handling ───────────────────────────
    def prepare_workspace(self, workspace_root: str | Path | None = None) -> Path:
        source = self.settings.repo_dir
        if not source.is_dir():
            raise SandboxError(f"Target repository not found: {source}")

        root = Path(workspace_root) if workspace_root else (self.settings.data_dir / "sandbox")
        root.mkdir(parents=True, exist_ok=True)
        workspace = root / f"ws-{uuid.uuid4().hex[:8]}"
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)
        shutil.copytree(
            source,
            workspace,
            ignore=shutil.ignore_patterns(*_IGNORED_COPY),
            dirs_exist_ok=True,
        )
        log.info("workspace prepared: %s", workspace)
        return workspace

    @staticmethod
    def cleanup(workspace: str | Path) -> None:
        shutil.rmtree(workspace, ignore_errors=True)
