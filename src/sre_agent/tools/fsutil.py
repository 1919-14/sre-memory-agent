"""Filesystem helpers.

Two Windows realities this module exists for:

1. Git objects are written read-only, so a plain `shutil.rmtree` fails with
   `PermissionError: [WinError 5]` and can leave a repository half-deleted.
2. Stale `__pycache__` is a correctness hazard, not just clutter: when two versions of a
   file differ only in size-preserving ways, Python can keep executing the cached module
   after the source changes. That would let the agent "verify" a fix that is not on disk.
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

_SKIP_PARTS = {".venv", "venv", "env", "node_modules"}


def _make_writable(path: str) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def force_rmtree(path: str | Path) -> bool:
    """Remove a directory tree, clearing read-only flags (Windows-safe).

    Returns True when the path no longer exists.
    """
    target = Path(path)
    if not target.exists():
        return True

    def on_error(func, failed_path, _exc_info):  # type: ignore[no-untyped-def]
        _make_writable(failed_path)
        try:
            func(failed_path)
        except OSError:
            pass

    shutil.rmtree(target, onerror=on_error)
    if target.exists():
        # Second pass: some handles (antivirus, editor, git) release a moment later.
        shutil.rmtree(target, ignore_errors=True)
    return not target.exists()


def clean_pycache(root: str | Path) -> int:
    """Delete every `__pycache__` directory under `root`. Returns the count removed."""
    base = Path(root)
    if not base.is_dir():
        return 0
    removed = 0
    for cache in list(base.rglob("__pycache__")):
        if any(part in _SKIP_PARTS for part in cache.parts):
            continue
        force_rmtree(cache)
        removed += 1
    return removed


def clean_test_caches(root: str | Path) -> int:
    """Remove pytest/mypy/ruff caches under `root`."""
    base = Path(root)
    if not base.is_dir():
        return 0
    removed = 0
    for name in (".pytest_cache", ".mypy_cache", ".ruff_cache"):
        for cache in list(base.rglob(name)):
            if any(part in _SKIP_PARTS for part in cache.parts):
                continue
            force_rmtree(cache)
            removed += 1
    return removed
