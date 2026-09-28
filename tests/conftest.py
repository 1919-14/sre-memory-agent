"""Shared test fixtures.

The suite must run without network access and without Hindsight, so tests inject a
scripted LLM and either a fake memory store or no memory at all.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from sre_agent.config import settings  # noqa: E402
from sre_agent.llm import ScriptedLLM  # noqa: E402
from sre_agent.tools.fsutil import clean_pycache  # noqa: E402
from sre_agent.tools.git_tools import GitRepo  # noqa: E402


@pytest.fixture(scope="session")
def project_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def demo_repo() -> Path:
    """The generated demo repository, built on demand."""
    repo_dir = settings.live_repo_dir
    if not (repo_dir / ".git").exists():
        setup = REPO_ROOT / "scripts" / "setup_demo_repo.py"
        subprocess.run(
            [sys.executable, str(setup), "--no-verify"],
            check=True,
            capture_output=True,
            cwd=str(REPO_ROOT),
        )
    assert (repo_dir / ".git").exists(), "demo repository could not be created"
    return repo_dir


@pytest.fixture
def scenario(demo_repo: Path):
    """Check a scenario out and restore the default afterwards."""

    def _switch(name: str) -> Path:
        repo = GitRepo(demo_repo)
        repo._run("checkout", "-q", f"scenario/{name}")
        clean_pycache(demo_repo)
        return demo_repo

    yield _switch
    GitRepo(demo_repo)._run("checkout", "-q", "scenario/concurrency")
    clean_pycache(demo_repo)


@pytest.fixture
def scripted_llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def no_memory():
    """No memory layer: exercises the degraded path deterministically."""
    return None


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """A throwaway copy of the demo template, with no git history."""
    source = settings.template_dir
    target = tmp_path / "repo"
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
    )
    return target
