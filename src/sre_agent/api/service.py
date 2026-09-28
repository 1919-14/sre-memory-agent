"""Application service.

Owns the long-lived objects (LLM client, memory store, agent) and decides how an incident
run is executed: live in a worker thread, or replayed from a recorded trajectory.

Everything the UI shows comes from here, and every response carries enough provenance
(live vs replayed, degraded vs clean) that the UI cannot misrepresent what happened.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from ..agent import SREAgent, TrajectoryRecorder
from ..config import Settings, settings as default_settings
from ..llm import LLMClient, build_llm
from ..logging_setup import get_logger
from ..memory import MemoryStore, MemoryStoreError
from ..models import (
    AgentStatus,
    EventStatus,
    ExecutionEvent,
    Incident,
    IncidentStatus,
    Outcome,
    RunMode,
    Stage,
)
from ..sandbox import SandboxExecutor
from ..sandbox.backends import DockerBackend
from ..storage import Storage
from ..tools.fsutil import clean_pycache
from ..tools.git_tools import GitRepo
from .events import EventBroker

log = get_logger("service")

SCENARIOS: dict[str, dict[str, str]] = {
    "concurrency": {
        "label": "Pool decoupled from concurrency",
        "description": "Worker concurrency raised to 40 while the Redis pool stays at 10.",
        "expectation": "Fixable: derive the pool from the concurrency.",
        "error": "RedisConnectionError: connection pool exhausted",
    },
    "leak": {
        "label": "Connection leak on the retry path",
        "description": "The retry path takes a new connection without releasing the failed one.",
        "expectation": "Fixable, but NOT by reusing the pool-sizing fix from the other incident.",
        "error": "RedisConnectionError: connection pool exhausted",
    },
    "auth": {
        "label": "Expired billing credential",
        "description": "The billing API token expired; every request returns HTTP 401.",
        "expectation": "Not code-fixable: escalate to a human instead of patching.",
        "error": "AuthenticationError: billing API token expired (HTTP 401)",
    },
}


class AgentService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings
        self.settings.ensure_dirs()
        self.storage = Storage(self.settings)
        self.recorder = TrajectoryRecorder(self.settings)
        self.broker = EventBroker()
        self.memory = MemoryStore(self.settings)
        self.memory.on_retry = self._on_memory_retry
        self._llm: LLMClient | None = None
        self._agent: SREAgent | None = None
        self._run_thread: threading.Thread | None = None
        self._active_incident_id: str | None = None
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self.warnings: list[str] = []
        self.notes: list[str] = []

    # ── lifecycle ───────────────────────────────────────────
    def startup(self) -> None:
        self.warnings = []
        self.notes = []
        reachable, detail = self.memory.health()
        if reachable:
            try:
                self.memory.ensure_banks()
                # A healthy fact, deliberately not a warning.
                self.notes.append(
                    f"Hindsight ready at {self.settings.hindsight_base_url} "
                    f"(banks: {self.memory.incident_bank}, {self.memory.convention_bank})"
                )
            except MemoryStoreError as exc:
                self.warnings.append(f"Hindsight reachable but bank setup failed: {exc}")
        else:
            self.warnings.append(
                f"Hindsight unavailable ({detail}). The agent runs degraded: no historical "
                "memory is used and nothing is learned."
            )
        agent = self.agent()
        self.warnings.extend(agent.prepare())
        self.settings.ensure_dirs()
        warning_suffix = (
            f"; WARNINGS: {'; '.join(self.warnings)}" if self.warnings else ""
        )
        log.info(
            "service ready: %s%s",
            "; ".join(self.notes) or "all dependencies available",
            warning_suffix,
        )

    def agent(self) -> SREAgent:
        if self._agent is None:
            self._agent = SREAgent(
                settings=self.settings,
                llm=self.llm(),
                memory=self.memory,
                event_sink=self._on_event,
            )
        return self._agent

    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = build_llm()
        return self._llm

    # ── event plumbing ──────────────────────────────────────
    def _on_memory_retry(self, operation: str, wait: float, attempt: int) -> None:
        """Publish a real throttle/retry notice for the in-flight incident.

        The wait is the window the provider itself asked for, so the interface can show a
        countdown that is measured rather than invented. Called from the memory store's
        retry loop on whichever thread made the call.
        """
        incident_id = self._active_incident_id
        if not incident_id:
            return
        stage = Stage.MEMORY if "retain" in operation or "store" in operation else Stage.RECALLING
        event = ExecutionEvent(
            incident_id=incident_id,
            stage=stage,
            status=EventStatus.RUNNING,
            message=(
                f"{operation.capitalize()} is throttled by the memory provider "
                f"(attempt {attempt}). Retrying in {wait:.0f}s."
            ),
            metadata={
                "retry": True,
                "retry_attempt": attempt,
                "retry_in_s": round(wait, 1),
                "retry_operation": operation,
                "reason": "LLM provider rate limit reported by Hindsight",
            },
        )
        try:
            self._on_event(event)
        except Exception as exc:  # noqa: BLE001 - never break a run to report a wait
            log.warning("could not publish retry notice: %s", exc)

    def _on_event(self, event) -> None:
        self.broker.publish_event(event)
        try:
            self.storage.append_event(event)
        except Exception as exc:  # noqa: BLE001 - persistence must not break a run
            log.warning("could not persist event: %s", exc)
        if event.incident_id:
            incident = self.storage.get_incident(event.incident_id)
            if incident is not None:
                try:
                    self.storage.save_incident(incident)
                except Exception:  # noqa: BLE001
                    pass

    def _snapshot(self, incident: Incident) -> None:
        self.storage.save_incident(incident)
        self.recorder.save(incident)

    # ── status ──────────────────────────────────────────────
    def status(self) -> AgentStatus:
        reachable, detail = self.memory.health()
        repo_present = GitRepo(self.settings.repo_dir).is_repo()
        sandbox = SandboxExecutor(self.settings)
        llm_ready = bool(self.settings.groq_api_key) and not self.settings.offline
        # Container isolation is part of what this agent guarantees about generated code, so
        # falling back to the local backend is a degradation even when everything else is
        # healthy. Each component below is reported from its own signal — readiness is never
        # inferred from the overall state.
        sandbox_isolated = sandbox.backend.name == "docker"
        docker_ok, _docker_detail = DockerBackend(self.settings).daemon_running()
        status = AgentStatus(
            healthy=reachable and repo_present and llm_ready and sandbox_isolated,
            llm_ready=llm_ready,
            hindsight_ready=reachable,
            hindsight_detail=detail,
            sandbox_backend=sandbox.backend.name,
            docker_available=docker_ok,
            run_mode=RunMode.REPLAY if self.settings.demo_replay_mode else RunMode.LIVE,
            repo_present=repo_present,
            repo_path=str(self.settings.repo_dir),
            repo_commit=GitRepo(self.settings.repo_dir).current_commit() if repo_present else "",
            active_incident_id=self._active_incident_id,
            banks={
                "incident": self.memory.incident_bank,
                "conventions": self.memory.convention_bank,
            },
            missing_credentials=self.settings.missing_credentials(),
            notes=list(self.notes),
            warnings=list(self.warnings),
            version=_version(),
            hindsight_version=self.memory.version,
        )
        for warning in sandbox.warnings:
            if warning not in status.warnings:
                status.warnings.append(warning)
        if self._last_error:
            status.warnings.append(self._last_error)
        return status

    # ── incident runs ───────────────────────────────────────
    def scenarios(self) -> list[dict[str, Any]]:
        repo = GitRepo(self.settings.repo_dir)
        out: list[dict[str, Any]] = []
        for key, meta in SCENARIOS.items():
            out.append(
                {
                    "key": key,
                    "branch": f"scenario/{key}",
                    "commit": repo.rev_parse(f"bad-{key}")[:8],
                    **meta,
                }
            )
        return out

    def switch_scenario(self, scenario: str) -> str:
        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown scenario {scenario!r}")
        repo = GitRepo(self.settings.repo_dir)
        if not repo.is_repo():
            raise RuntimeError(
                "The demo repository is not built. Run: "
                "venv/Scripts/python.exe scripts/setup_demo_repo.py"
            )
        repo._run("checkout", "-q", f"scenario/{scenario}")
        # Stale bytecode can otherwise execute the previous scenario's module.
        clean_pycache(self.settings.repo_dir)
        return repo.current_commit()

    def is_running(self) -> bool:
        return self._run_thread is not None and self._run_thread.is_alive()

    def start_incident(
        self,
        *,
        scenario: str | None = None,
        trigger: str = "manual",
        error: str = "",
        background: bool = True,
        replay: bool = False,
    ) -> Incident:
        with self._lock:
            if self.is_running():
                raise RuntimeError("An incident is already running.")

            if replay or self.settings.demo_replay_mode:
                incident = self._load_replay(scenario)
                if incident is None:
                    raise RuntimeError(
                        "No recorded trajectory is available to replay. Run the scenario "
                        "live first."
                    )
                thread = threading.Thread(
                    target=self._replay, args=(incident,), name=f"replay-{incident.id}", daemon=True
                )
                self._run_thread = thread
                self._active_incident_id = incident.id
                thread.start()
                return incident

            if scenario:
                self.switch_scenario(scenario)
                error = error or SCENARIOS[scenario]["error"]

            repo = GitRepo(self.settings.repo_dir)
            incident = Incident(
                repository=self.settings.repo_dir.name,
                error=error or "CI failure on the current commit",
                trigger=trigger,
                previous_good_commit=repo.rev_parse("good") or repo.last_known_good(),
                branch=repo.current_branch(),
                commit_sha=repo.current_commit(),
                run_mode=RunMode.REPLAY if self.settings.offline else RunMode.LIVE,
                simulated=self.settings.offline,
            )
            self.storage.save_incident(incident)

            if background:
                thread = threading.Thread(
                    target=self._run_live, args=(incident,), name=f"incident-{incident.id}", daemon=True
                )
                self._run_thread = thread
                self._active_incident_id = incident.id
                thread.start()
                return incident

            return self._run_live(incident)

    def _run_live(self, incident: Incident) -> Incident:
        self._active_incident_id = incident.id
        try:
            agent = self.agent()
            incident = agent.run_incident(incident)
        except Exception as exc:  # noqa: BLE001 - surface, never lose the incident
            log.exception("incident run failed")
            self._last_error = f"Incident run failed: {type(exc).__name__}: {exc}"
            incident.warn(self._last_error)
            incident.outcome = Outcome.ABORTED
        finally:
            self._snapshot(incident)
            self._active_incident_id = None
            self.broker.publish(
                {
                    "_type": "incident_finished",
                    "incident_id": incident.id,
                    "status": incident.status.value,
                    "outcome": incident.outcome.value if incident.outcome else None,
                }
            )
        return incident

    # ── replay ──────────────────────────────────────────────
    def _load_replay(self, scenario: str | None) -> Incident | None:
        if scenario:
            incident = self.recorder.load_by_label(scenario)
            if incident is not None:
                return incident
        return self.recorder.load_latest()

    def _replay(self, incident: Incident) -> None:
        """Re-render a recorded trajectory. Clearly marked simulated; no LLM calls."""
        try:
            delay = 0.35
            for event in incident.events:
                self.broker.publish(
                    {
                        "_type": "event",
                        "simulated": True,
                        **event.model_dump(mode="json"),
                    }
                )
                time.sleep(delay)
            self.broker.publish(
                {
                    "_type": "incident_finished",
                    "incident_id": incident.id,
                    "status": incident.status.value,
                    "outcome": incident.outcome.value if incident.outcome else None,
                    "simulated": True,
                }
            )
        finally:
            self._active_incident_id = None

    # ── memory browsing ─────────────────────────────────────
    def memory_overview(self) -> dict[str, Any]:
        reachable, detail = self.memory.health()
        if not reachable:
            return {
                "available": False,
                "detail": detail,
                "banks": {
                    "incident": {"bank_id": self.memory.incident_bank, "memories": []},
                    "conventions": {"bank_id": self.memory.convention_bank, "memories": []},
                },
                "counters": self.memory.counters(),
            }
        out: dict[str, Any] = {
            "available": True,
            "detail": detail,
            "counters": self.memory.counters(),
            "memory_defense": self.memory.memory_defense_note,
            "banks": {},
        }
        for key, bank in (
            ("incident", self.memory.incident_bank),
            ("conventions", self.memory.convention_bank),
        ):
            try:
                refs = self.memory.list_memories(bank, limit=100)
                out["banks"][key] = {
                    "bank_id": bank,
                    "memories": [r.model_dump() for r in refs],
                }
            except MemoryStoreError as exc:
                out["banks"][key] = {"bank_id": bank, "memories": [], "error": str(exc)}
        return out

    def memory_search(self, query: str, bank: str = "incident", limit: int = 20) -> dict[str, Any]:
        target = self.memory.incident_bank if bank == "incident" else self.memory.convention_bank
        try:
            refs = self.memory.list_memories(target, search_query=query, limit=limit)
        except MemoryStoreError as exc:
            return {"available": False, "detail": str(exc), "results": []}
        return {"available": True, "results": [r.model_dump() for r in refs]}

    def runbook(self, refresh: bool = False) -> dict[str, Any]:
        try:
            if refresh:
                self.memory.refresh_runbook()
            content = self.memory.read_runbook()
            path = self.memory.write_runbook_to_disk(content) if content else ""
            return {"available": True, "content": content, "path": path}
        except MemoryStoreError as exc:
            return {"available": False, "detail": str(exc), "content": ""}

    def conventions(self) -> list[str]:
        from pathlib import Path

        path = Path(self.settings.convention_seed_path)
        if not path.is_absolute():
            path = self.settings.base_dir / path
        if not path.is_file():
            return []
        try:
            namespace: dict[str, Any] = {}
            exec(path.read_text(encoding="utf-8"), namespace)  # noqa: S102 - trusted local file
            return list(namespace.get("CONVENTIONS", []))
        except Exception as exc:  # noqa: BLE001
            log.warning("could not load conventions from %s: %s", path, exc)
            return []

    def seed_memory(self) -> dict[str, Any]:
        from ..seed.incidents import seed_conventions, seed_history

        result = {"conventions": 0, "incidents": [], "errors": []}
        try:
            result["conventions"] = seed_conventions(self.memory, self.conventions())
        except MemoryStoreError as exc:
            result["errors"].append(str(exc))
        try:
            result["incidents"] = seed_history(self.memory, self.settings)
        except MemoryStoreError as exc:
            result["errors"].append(str(exc))
        return result

    # ── rollback approval gate ──────────────────────────────
    def approve_rollback(self, incident_id: str) -> dict[str, Any]:
        incident = self.storage.get_incident(incident_id)
        if incident is None:
            raise KeyError(incident_id)
        agent = self.agent()
        outcome = agent.rollback.approve_and_execute(incident)
        if outcome.executed:
            incident.status = IncidentStatus.ROLLED_BACK
            incident.outcome = Outcome.ROLLED_BACK
            incident.rollback_commit = outcome.verified_commit
            incident.final_resolution = (
                f"Rolled back to {outcome.verified_commit[:8]} after administrator approval."
            )
            agent._event(
                incident,
                Stage.ROLLBACK,
                "Rollback approved by an administrator and executed.",
                plan=outcome.plan,
            )
            self._snapshot(incident)
        return outcome.to_dict()

    def recorded_runs(self) -> list[dict[str, Any]]:
        return self.recorder.list_runs()

    def shutdown(self) -> None:
        self.memory.close()
        if self._llm is not None and hasattr(self._llm, "close"):
            self._llm.close()


def _version() -> str:
    from .. import __version__

    return __version__


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
