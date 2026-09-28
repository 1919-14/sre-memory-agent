"""Git operations.

Every git call goes through `_run` with an argument list (never `shell=True`), so no
repository content can ever be interpreted as a command.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..logging_setup import get_logger

log = get_logger("git")


class GitError(RuntimeError):
    pass


DEPENDENCY_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "poetry.lock",
    "Pipfile",
    "package.json",
    "package-lock.json",
    "uv.lock",
)


@dataclass
class RollbackPlan:
    """A rollback is a reviewed plan, not an autonomous reset."""

    target_ref: str
    target_commit: str
    current_commit: str
    files_affected: list[str]
    description: str
    reversible: bool = True

    def to_dict(self) -> dict:
        return {
            "target_ref": self.target_ref,
            "target_commit": self.target_commit,
            "current_commit": self.current_commit,
            "files_affected": self.files_affected,
            "description": self.description,
            "reversible": self.reversible,
        }


class GitRepo:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    # ── primitives ──────────────────────────────────────────
    def _run(self, *args: str, check: bool = True) -> str:
        import subprocess

        cmd = ["git", "-C", str(self.path), *args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        except FileNotFoundError as exc:  # pragma: no cover
            raise GitError("git executable not found on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git timed out: {' '.join(args)}") from exc

        if check and proc.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
            )
        return proc.stdout

    def is_repo(self) -> bool:
        try:
            self._run("rev-parse", "--is-inside-work-tree")
            return True
        except GitError:
            return False

    # ── reads ───────────────────────────────────────────────
    def current_commit(self) -> str:
        return self._run("rev-parse", "HEAD").strip()

    def current_branch(self) -> str:
        branch = self._run("rev-parse", "--abbrev-ref", "HEAD").strip()
        return branch if branch != "HEAD" else ""

    def is_dirty(self) -> bool:
        return bool(self._run("status", "--porcelain").strip())

    def commit_message(self, ref: str = "HEAD") -> str:
        return self._run("log", "-1", "--pretty=%s", ref).strip()

    def describe_commit(self, ref: str = "HEAD") -> str:
        return self._run("log", "-1", "--pretty=%h %s (%an, %ar)", ref).strip()

    def log(self, count: int = 10, ref: str = "HEAD") -> list[dict[str, str]]:
        raw = self._run(
            "log", f"-{count}", "--pretty=%H%x1f%h%x1f%s%x1f%an%x1f%aI", ref
        )
        entries: list[dict[str, str]] = []
        for line in raw.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 5:
                entries.append(
                    {
                        "sha": parts[0],
                        "short": parts[1],
                        "subject": parts[2],
                        "author": parts[3],
                        "date": parts[4],
                    }
                )
        return entries

    def rev_parse(self, ref: str) -> str:
        """Resolve a ref to a commit SHA, or "" when it does not exist."""
        try:
            return self._run("rev-parse", "--verify", f"{ref}^{{commit}}").strip()
        except GitError:
            return ""

    def last_known_good(self, preferred_ref: str = "") -> str:
        """Resolve the last known-good commit.

        Preference order: configured ref, `HEAD~1`, then HEAD. The agent never
        *assumes* which commit is good — the incident evidence supplies it.
        """
        for candidate in (preferred_ref, "HEAD~1"):
            if not candidate:
                continue
            sha = self.rev_parse(candidate)
            if sha:
                return sha
        return self.current_commit()

    # ── diffs ───────────────────────────────────────────────
    def changed_files(self, since: str = "") -> list[str]:
        args = ["diff", "--name-only"]
        if since:
            args.append(f"{since}..HEAD")
        else:
            args.append("HEAD")
        out = self._run(*args).strip()
        files = [line.strip() for line in out.splitlines() if line.strip()]
        if not files and not since:
            # Uncommitted changes in the working tree
            out = self._run("status", "--porcelain").strip()
            files = [line[3:].strip() for line in out.splitlines() if line.strip()]
        return files

    def diff(self, since: str = "", *, stat_only: bool = False) -> str:
        args = ["diff"]
        if stat_only:
            args.append("--stat")
        if since:
            args.append(f"{since}..HEAD")
        else:
            args.append("HEAD")
        return self._run(*args)

    def diff_summary(self, since: str = "", max_files: int = 25) -> str:
        """Per-file changed-line counts, compact enough for a prompt."""
        out = self.diff(since, stat_only=True).strip()
        if not out:
            return ""
        lines = out.splitlines()[-max_files:]
        return "\n".join(lines)

    def dependency_changes(self, since: str = "") -> list[str]:
        changed = set(self.changed_files(since))
        return sorted(f for f in changed if Path(f).name in DEPENDENCY_FILES)

    def show_file_at(self, ref: str, path: str) -> str:
        """Contents of a file at a ref. Returns "" when absent."""
        try:
            return self._run("show", f"{ref}:{path}")
        except GitError:
            return ""

    # ── controlled rollback ─────────────────────────────────
    def plan_rollback(self, target_ref: str) -> RollbackPlan:
        target_commit = self.rev_parse(target_ref)
        if not target_commit:
            raise GitError(f"Rollback target {target_ref!r} does not resolve to a commit")
        current = self.current_commit()
        raw = self._run("diff", "--name-only", f"{current}..{target_commit}").strip()
        files = [line.strip() for line in raw.splitlines() if line.strip()]
        return RollbackPlan(
            target_ref=target_ref,
            target_commit=target_commit,
            current_commit=current,
            files_affected=files,
            description=(
                f"Restore the working tree to {target_ref} ({target_commit[:8]}); "
                f"{len(files)} file(s) differ from the current commit."
            ),
        )

    def execute_rollback(self, plan: RollbackPlan, *, confirm: bool = False) -> dict[str, str]:
        """Restore tracked files to the plan's target commit.

        Requires explicit confirmation: production-affecting actions are gated.
        """
        if not confirm:
            raise GitError("Rollback requires explicit confirmation (confirm=True)")
        self._run("checkout", plan.target_commit, "--", ".")
        verified = self.current_commit()
        log.warning(
            "ROLLBACK executed: working tree restored to %s (HEAD still %s)",
            plan.target_commit[:8],
            verified[:8],
        )
        return {
            "restored_to": plan.target_commit,
            "head": verified,
            "files_affected": str(len(plan.files_affected)),
        }


# `clean_pycache` / `force_rmtree` live in fsutil; re-exported here because callers that
# check out a revision almost always need to purge caches right after.
from .fsutil import clean_pycache, force_rmtree  # noqa: E402  (intentional re-export)


def parse_patch_paths(patch_text: str) -> list[str]:
    """Extract target paths from a unified diff (used for policy checks)."""
    paths: list[str] = []
    for line in (patch_text or "").splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            candidate = line[4:].strip()
            if candidate in ("/dev/null", ""):
                continue
            candidate = re.sub(r"^[ab]/", "", candidate)
            if candidate not in paths:
                paths.append(candidate)
    return paths
