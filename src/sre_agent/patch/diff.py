"""Unified diff generation.

The LLM returns complete file contents, not diffs — hand-written diffs are the single
biggest source of broken patches. We compute the diff here, so the review gate and the UI
see exactly what will change and the applier can never be confused by a malformed hunk.
"""

from __future__ import annotations

import difflib
from pathlib import Path

from ..models import FileEdit


def file_unified_diff(path: str, old: str, new: str, *, context: int = 3) -> str:
    if old == new:
        return ""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=context,
        )
    )


def read_existing(repo_path: str | Path, relative: str) -> str:
    target = Path(repo_path) / relative
    if not target.is_file():
        return ""
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def build_patch_diff(repo_path: str | Path, files: list[FileEdit]) -> str:
    """Concatenate per-file diffs into one patch body for display and policy checks."""
    chunks: list[str] = []
    for edit in files:
        diff = file_unified_diff(edit.path, read_existing(repo_path, edit.path), edit.content)
        if diff:
            chunks.append(diff)
    return "".join(chunks)


def line_counts(diff: str) -> tuple[int, int]:
    """Return (added, removed) line counts, ignoring file headers."""
    added = removed = 0
    for line in (diff or "").splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def changed_paths_from_diff(diff: str) -> list[str]:
    paths: list[str] = []
    for line in (diff or "").splitlines():
        if line.startswith("+++ "):
            candidate = line[4:].strip()
            if candidate == "/dev/null":
                continue
            candidate = candidate[2:] if candidate.startswith("b/") else candidate
            if candidate not in paths:
                paths.append(candidate)
    return paths
