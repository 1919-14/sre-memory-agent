"""Deterministic replay of a previously recorded incident run.

The scripted LLM used by offline mode has no `generate_patch` handler, so before this
module existed an offline run could never repair anything: every proposal failed and the
incident always ended in a rollback. Replaying the real LLM outputs captured in a recorded
trajectory fixes that without fabricating anything — the patch being replayed came from an
actual run whose fix was verified in the sandbox.

Recorded runs are written to `data/runs/<incident_id>.json` by `TrajectoryRecorder`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import Settings, settings as default_settings
from ..logging_setup import get_logger

log = get_logger("replay")

# Keys the fix generator consumes from a `generate_patch` payload. Everything else in the
# recorded patch (ids, timings, the applied diff) is derived fresh on replay.
_PATCH_KEYS = (
    "root_cause",
    "why_this_happened",
    "proposed_fix",
    "files",
    "expected_outcome",
    "risk",
    "test_strategy",
)


class ReplaySource:
    """Real recorded LLM outputs, served as scripted handlers."""

    def __init__(self, run: dict[str, Any], path: Path) -> None:
        self.run = run
        self.path = path

    # ── loading ─────────────────────────────────────────────
    @classmethod
    def load(
        cls,
        settings: Settings | None = None,
        *,
        branch: str | None = None,
        prefer_outcome: str = "recovered",
    ) -> "ReplaySource | None":
        """Pick the recorded run to replay, preferring one matching `branch`.

        Returns None when no recorded run contains a usable patch, which is the honest
        answer: offline mode then genuinely cannot repair anything, and the caller says so
        instead of pretending.
        """
        settings = settings or default_settings
        candidates: list[tuple[int, dict[str, Any], Path]] = []
        for path in sorted(settings.runs_dir_path.glob("*.json")):
            try:
                run = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("skipping unreadable trajectory %s: %s", path.name, exc)
                continue
            if not cls._patch_payload(run):
                continue
            # Same branch + recovered is the ideal replay; score so the best one wins.
            score = 0
            if branch and run.get("branch") == branch:
                score += 2
            if run.get("outcome") == prefer_outcome:
                score += 1
            candidates.append((score, run, path))

        if not candidates:
            return None
        _score, run, path = max(candidates, key=lambda item: item[0])
        log.info("replaying recorded trajectory %s", path.name)
        return cls(run, path)

    # ── payload extraction ──────────────────────────────────
    @staticmethod
    def _patch_payload(run: dict[str, Any]) -> dict[str, Any]:
        """The first recorded patch that actually carried file contents."""
        for attempt in run.get("attempts") or []:
            patch = (attempt or {}).get("patch") or {}
            if isinstance(patch, dict) and patch.get("files"):
                return {key: patch[key] for key in _PATCH_KEYS if patch.get(key) is not None}
        return {}

    def _first_patched_attempt(self) -> dict[str, Any]:
        for attempt in self.run.get("attempts") or []:
            if isinstance(attempt, dict) and (attempt.get("patch") or {}).get("files"):
                return attempt
        return {}

    # ── handlers ────────────────────────────────────────────
    def handlers(self) -> dict[str, Any]:
        """Handlers for the purposes offline mode cannot otherwise answer.

        `classify` is deliberately absent: classification has a real deterministic
        fallback, so it does not need replaying.
        """
        handlers: dict[str, Any] = {}

        patch = self._patch_payload(self.run)
        if patch:
            handlers["generate_patch"] = patch

        review = self._first_patched_attempt().get("review")
        if isinstance(review, dict) and review.get("decision"):
            handlers["review_patch"] = review

        comparability = self.run.get("comparability")
        if isinstance(comparability, dict) and comparability:
            handlers["comparability"] = comparability

        return handlers

    def describe(self) -> str:
        return (
            f"{self.path.name} (branch={self.run.get('branch')}, "
            f"outcome={self.run.get('outcome')}, "
            f"recorded={str(self.run.get('_recorded_at'))[:19]})"
        )
