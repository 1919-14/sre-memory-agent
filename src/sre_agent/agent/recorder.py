"""Trajectory recording and replay.

Every incident run is written to `data/runs/<incident_id>.json`. Replay re-renders a
recorded trajectory without calling the LLM or Hindsight, which is what keeps a live demo
alive when the network, a rate limit, or an API key fails in front of judges.

Replayed incidents are always marked `run_mode=replay` and `simulated=True`. A replay is
never presented as a live run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..config import Settings, settings as default_settings
from ..logging_setup import get_logger
from ..models import Incident, RunMode

log = get_logger("recorder")


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
        try:
            incident = Incident.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("recorded trajectory %s does not match the model: %s", path.name, exc)
            return None
        # Mark clearly as replay.
        incident.run_mode = RunMode.REPLAY
        incident.simulated = True
        return incident

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
