"""Patch validation.

Validation happens before anything executes, and it is deterministic: no model can talk
its way past it. Findings here are hard errors that stop the attempt.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..classify.taxonomy import looks_like_test_path
from ..config import Settings, settings as default_settings
from ..logging_setup import get_logger
from ..models import Patch, PatchValidation
from .diff import build_patch_diff, line_counts

log = get_logger("patch-validator")

_SECRET_PATTERNS = (
    re.compile(r"\bgsk_[A-Za-z0-9]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}"),
    re.compile(r"(?i)\bpassword\s*=\s*['\"][^'\"]{3,}['\"]"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token)\s*=\s*['\"][A-Za-z0-9_\-]{12,}['\"]"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

_SUSPICIOUS_PATTERNS = (
    (re.compile(r"^\s*except\s*:\s*$", re.MULTILINE), "bare `except:` swallows every error"),
    (re.compile(r"^\s*except\s+Exception\s*:\s*(pass|\.\.\.)\s*$", re.MULTILINE),
     "`except Exception: pass` hides the failure"),
    (re.compile(r"\bos\.system\(|\bshell\s*=\s*True\b"), "executes a shell command"),
    (re.compile(r"\bsubprocess\.(run|Popen|call|check_output)\("), "spawns a subprocess"),
    (re.compile(r"\bbreakpoint\(\)|\bpdb\.set_trace\(\)"), "leaves a debugger breakpoint"),
    (re.compile(r"^\s*print\(", re.MULTILINE), "leaves debug output in place"),
    (re.compile(r"@pytest\.mark\.(skip|xfail)"), "skips or xfails a test"),
    (re.compile(r"\brm\s+-rf\b"), "contains a destructive shell command"),
    (re.compile(r"\bDROP\s+TABLE\b|\bTRUNCATE\b", re.IGNORECASE), "contains a destructive SQL statement"),
    (re.compile(r"https?://(?!localhost|127\.0\.0\.1)"), "hardcodes an external URL"),
)

_TEST_WEAKENING = (
    re.compile(r"^\s*assert\s+True\b", re.MULTILINE),
    re.compile(r"^\s*assert\s+1\s*==\s*1\b", re.MULTILINE),
)


class PatchValidator:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings

    def validate(self, patch: Patch, repo_path: str | Path) -> PatchValidation:
        result = PatchValidation()
        errors = result.errors
        warnings = result.warnings

        if not patch.files:
            errors.append("Patch contains no file changes.")
            return self._finish(result, patch, repo_path)

        if len(patch.files) > self.settings.patch_max_files:
            errors.append(
                f"Patch touches {len(patch.files)} files, exceeding the limit of "
                f"{self.settings.patch_max_files}."
            )

        seen: set[str] = set()
        for edit in patch.files:
            path = (edit.path or "").strip().replace("\\", "/")
            if not path:
                errors.append("Patch contains a file entry with an empty path.")
                continue
            if path in seen:
                errors.append(f"Patch changes the same file twice: {path}")
                continue
            seen.add(path)

            if Path(path).is_absolute():
                errors.append(f"Absolute paths are not allowed: {path}")
                continue
            if ".." in Path(path).parts:
                errors.append(f"Path traversal is not allowed: {path}")
                continue

            if not any(path.startswith(prefix) for prefix in self.settings.allowed_patch_paths):
                errors.append(
                    f"{path} is outside the allowed patch paths "
                    f"({', '.join(self.settings.allowed_patch_paths)})."
                )
            if any(path.startswith(prefix) for prefix in self.settings.forbidden_patch_paths):
                errors.append(f"{path} is in a forbidden path.")

            if not isinstance(edit.content, str) or not edit.content.strip():
                errors.append(f"{path} has empty content.")
                continue
            if "\x00" in edit.content:
                errors.append(f"{path} contains a null byte.")

            for pattern in _SECRET_PATTERNS:
                if pattern.search(edit.content):
                    errors.append(f"{path} appears to contain a hardcoded secret or credential.")
                    break

            for pattern, description in _SUSPICIOUS_PATTERNS:
                if pattern.search(edit.content):
                    warnings.append(f"{path}: {description}.")

            if looks_like_test_path(path):
                for pattern in _TEST_WEAKENING:
                    if pattern.search(edit.content):
                        warnings.append(f"{path}: change may weaken a test assertion.")
                        break

        diff = build_patch_diff(repo_path, patch.files)
        added, removed = line_counts(diff)
        result.files_changed = len(patch.files)
        result.lines_added = added
        result.lines_removed = removed
        patch.diff = diff

        if not diff.strip():
            errors.append("Patch produces no actual change (proposed content is identical).")

        if added + removed > self.settings.patch_max_lines:
            errors.append(
                f"Patch changes {added + removed} lines, exceeding the limit of "
                f"{self.settings.patch_max_lines}."
            )

        return self._finish(result, patch, repo_path)

    @staticmethod
    def _finish(result: PatchValidation, patch: Patch, repo_path: str | Path) -> PatchValidation:
        result.ok = not result.errors
        if result.ok:
            log.info(
                "patch %s validated: %s file(s), +%s/-%s lines",
                patch.id[:8],
                result.files_changed,
                result.lines_added,
                result.lines_removed,
            )
        else:
            log.warning("patch %s rejected by validation: %s", patch.id[:8], result.errors)
        return result
