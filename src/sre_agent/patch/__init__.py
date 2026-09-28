"""Patch generation support: build, validate, apply."""

from .applier import ApplyResult, PatchApplyError, apply_edits, revert
from .builder import PatchBuildError, patch_from_payload
from .diff import build_patch_diff, changed_paths_from_diff, file_unified_diff, line_counts
from .validator import PatchValidator

__all__ = [
    "ApplyResult",
    "PatchApplyError",
    "PatchBuildError",
    "PatchValidator",
    "apply_edits",
    "build_patch_diff",
    "changed_paths_from_diff",
    "file_unified_diff",
    "line_counts",
    "patch_from_payload",
    "revert",
]
