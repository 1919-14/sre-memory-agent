"""Apply proposed file contents to a workspace.

Always operates on a throwaway workspace (a sandbox copy), never on the live working
tree, and keeps a snapshot so an attempt can be reverted cleanly between retries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..logging_setup import get_logger
from ..models import FileEdit

log = get_logger("patch-applier")


class PatchApplyError(RuntimeError):
    pass


@dataclass
class ApplyResult:
    applied: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    snapshot: dict[str, str | None] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def apply_edits(root: str | Path, edits: list[FileEdit]) -> ApplyResult:
    """Write file contents under `root`, snapshotting originals for revert."""
    root_path = Path(root).resolve()
    result = ApplyResult()

    for edit in edits:
        relative = (edit.path or "").strip().replace("\\", "/")
        target = (root_path / relative).resolve()

        # Containment check: refuse anything that escapes the workspace.
        try:
            target.relative_to(root_path)
        except ValueError:
            result.errors.append(f"Refusing to write outside the workspace: {relative}")
            continue

        try:
            existed = target.is_file()
            result.snapshot[relative] = (
                target.read_text(encoding="utf-8", errors="replace") if existed else None
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(edit.content, encoding="utf-8")
            (result.applied if existed else result.created).append(relative)
        except OSError as exc:
            result.errors.append(f"Failed to write {relative}: {exc}")

    if result.errors:
        log.error("patch application had errors: %s", result.errors)
    else:
        log.info(
            "applied patch: %s updated, %s created",
            len(result.applied),
            len(result.created),
        )
    return result


def revert(root: str | Path, snapshot: dict[str, str | None]) -> list[str]:
    """Restore a snapshot produced by `apply_edits`."""
    root_path = Path(root).resolve()
    reverted: list[str] = []
    for relative, original in snapshot.items():
        target = (root_path / relative).resolve()
        try:
            target.relative_to(root_path)
        except ValueError:
            continue
        try:
            if original is None:
                if target.is_file():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(original, encoding="utf-8")
            reverted.append(relative)
        except OSError as exc:  # pragma: no cover
            log.warning("failed to revert %s: %s", relative, exc)
    return reverted
