"""Trajectory recording and replay.

Every incident run is written to `data/runs/<incident_id>.json`. Replay re-renders a
recorded trajectory without calling the LLM or Hindsight, which is what keeps a live demo
alive when the network, a rate limit, or an API key fails in front of judges.

Replayed incidents are always marked `run_mode=replay` and `simulated=True`. A replay is
never presented as a live run.

Recordings are portable across hosts. Every absolute path in a run belongs to the machine
that produced it — the repository checkout, the sandbox workspace — and those paths appear in
the evidence the interface displays. A recording therefore stores the project root it was
written on, and is read back re-anchored to the current root: a trajectory recorded on a
laptop replays correctly inside the deployment container, which has no such directory. The
replay stays a faithful re-render of what the agent did; only the machine-specific prefix
changes, so a public deployment never shows a path from someone's laptop.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Settings, settings as default_settings
from ..logging_setup import get_logger
from ..models import Incident, RunMode

log = get_logger("recorder")


def _json_escaped(path: str) -> str:
    """A path as it appears inside a JSON string (backslashes doubled)."""
    return json.dumps(path)[1:-1]


def _recorded_root(payload: dict) -> str:
    """The project root a recording was written on.

    Recordings made before `_root` was stored are recovered from the repository path: the
    agent's repository always lives under `data/`, so everything before that separator is
    the root. Returns "" when it cannot be determined, and the payload is then left alone.
    """
    stored = payload.get("_root")
    if isinstance(stored, str) and stored:
        return stored
    evidence = payload.get("evidence")
    candidates = [payload.get("repo_path"), evidence.get("repo_path") if isinstance(evidence, dict) else None]
    for value in candidates:
        if not isinstance(value, str) or not value:
            continue
        for separator in ("\\", "/"):
            index = value.rfind(f"{separator}data{separator}")
            if index > 0:
                return value[:index]
    return ""


def _rebase_paths(node: Any, source: str, target: str) -> Any:
    """Rewrite every string that starts with `source` to start with `target`.

    Only values that *begin* with the recorded root are rewritten, and separators after it
    are normalised to the target's convention. A path embedded mid-sentence is therefore left
    as-is rather than risk rewriting prose, and a stack-trace line is untouched because the
    test runner already reports repository-relative paths.
    """
    if isinstance(node, dict):
        return {key: _rebase_paths(value, source, target) for key, value in node.items()}
    if isinstance(node, list):
        return [_rebase_paths(value, source, target) for value in node]
    if not isinstance(node, str) or not node:
        return node
    separator = "\\" if "\\" in target else "/"
    for prefix in (source, source.replace("\\", "/")):
        if node.startswith(prefix):
            tail = node[len(prefix) :].replace("\\", separator).replace("/", separator)
            return target + tail
    return node


class TrajectoryRecorder:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings
        self.settings.runs_dir_path.mkdir(parents=True, exist_ok=True)

    # ── write ───────────────────────────────────────────────
    def save(self, incident: Incident, *, label: str = "") -> Path | None:
        if not self.settings.demo_record_trajectories:
            return None
        path = self.path_for(incident.id)
        try:
            payload = incident.model_dump(mode="json")
            payload["_recorded_at"] = datetime.now(timezone.utc).isoformat()
            payload["_label"] = label
            # The host this ran on, so a replay elsewhere can re-anchor its paths.
            payload["_root"] = str(self.settings.base_dir)
            path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            log.info("trajectory recorded: %s", path.name)
            return path
        except OSError as exc:
            log.warning("could not record trajectory %s: %s", incident.id, exc)
            return None

    # ── read ────────────────────────────────────────────────
    def load(self, incident_id: str) -> Incident | None:
        path = self.path_for(incident_id)
        return self._load_path(path)

    def load_latest(self, *, error_class: str | None = None) -> Incident | None:
        for entry in self.list_runs():
            if error_class and entry.get("error_class") != error_class:
                continue
            incident = self.load(entry["id"])
            if incident is not None:
                return incident
        return None

    def load_by_label(self, label: str) -> Incident | None:
        for entry in self.list_runs():
            if entry.get("label") == label:
                incident = self.load(entry["id"])
                if incident is not None:
                    return incident
        return None

    def _load_path(self, path: Path) -> Incident | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("could not read trajectory %s: %s", path.name, exc)
            return None
        payload.pop("_recorded_at", None)
        payload.pop("_label", None)
        source_root = _recorded_root(payload)
        payload.pop("_root", None)
        payload = self._reanchor(payload, source_root, path)
        try:
            incident = Incident.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("recorded trajectory %s does not match the model: %s", path.name, exc)
            return None
        # Mark clearly as replay.
        incident.run_mode = RunMode.REPLAY
        incident.simulated = True
        return incident

    # ── portability ─────────────────────────────────────────
    def _reanchor(self, payload: dict, source_root: str, path: Path) -> dict:
        """Rebase a recording's host paths onto this machine.

        Walks the whole payload rather than a fixed list of fields, because the paths live in
        evidence and sandbox reports nested several levels deep. On the machine that recorded
        the run this is a no-op; anywhere else it is what makes the trajectory readable.
        """
        target_root = str(self.settings.base_dir)
        if not source_root or source_root == target_root:
            return payload
        try:
            rebased = _rebase_paths(payload, source_root, target_root)
        except Exception as exc:  # noqa: BLE001 - a replay must never fail on this
            log.warning("could not re-anchor %s: %s", path.name, exc)
            return payload
        # A path that survived the rewrite would be shown to whoever is watching the replay,
        # so say so instead of publishing it quietly.
        residual = _json_escaped(source_root)
        if residual in json.dumps(rebased):
            log.warning(
                "%s still contains the recorded path %r after re-anchoring; "
                "it appears inside a longer string and was left as recorded.",
                path.name,
                source_root,
            )
        log.info("re-anchored %s from %s to %s", path.name, source_root, target_root)
        return rebased

    # ── inventory ───────────────────────────────────────────
    def list_runs(self, limit: int = 50) -> list[dict]:
        entries: list[dict] = []
        paths = sorted(
            self.settings.runs_dir_path.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for path in paths[:limit]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            classification = payload.get("classification") or {}
            entries.append(
                {
                    "id": payload.get("id", path.stem),
                    "error": (payload.get("error") or "")[:160],
                    "error_class": classification.get("error_class", "unknown"),
                    "status": payload.get("status", ""),
                    "outcome": payload.get("outcome"),
                    "run_mode": payload.get("run_mode", "live"),
                    "attempts": len(payload.get("attempts") or []),
                    "created_at": payload.get("created_at", ""),
                    "label": payload.get("_label", ""),
                    "file": path.name,
                }
            )
        return entries

    def path_for(self, incident_id: str) -> Path:
        return self.settings.runs_dir_path / f"{incident_id}.json"
