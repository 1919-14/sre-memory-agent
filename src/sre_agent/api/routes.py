"""HTTP API routes.

Every response carries provenance (live vs replayed, degraded vs clean) so the client can
never present a simulated or degraded result as a normal one.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..config import settings
from ..logging_setup import get_logger
from .service import SCENARIOS, AgentService

log = get_logger("api")

router = APIRouter(prefix="/api")


def service(request: Request) -> AgentService:
    return request.app.state.service


# ── system ──────────────────────────────────────────────────


@router.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "version": _version(), "env": settings.app_env}


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    svc = service(request)
    payload = svc.status().model_dump(mode="json")
    payload["metrics"] = svc.storage.dashboard_metrics()
    payload["learning"] = svc.storage.learning_stats().model_dump(mode="json")
    payload["memory"] = svc.memory.counters()
    payload["memory_defense"] = svc.memory.memory_defense_note
    payload["running"] = svc.is_running()
    return payload


@router.get("/metrics")
def metrics(request: Request) -> dict[str, Any]:
    svc = service(request)
    return {
        "dashboard": svc.storage.dashboard_metrics(),
        "learning": svc.storage.learning_stats().model_dump(mode="json"),
        "memory": svc.memory.counters(),
        "hindsight": svc.memory.status(),
    }


# ── incidents ───────────────────────────────────────────────


@router.get("/incidents")
def list_incidents(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    svc = service(request)
    return {"incidents": _merged_incidents(svc, limit=limit, offset=offset)}


def _merged_incidents(svc: AgentService, *, limit: int, offset: int) -> list[dict[str, Any]]:
    """The operational store and the recorded trajectories, as one history.

    Two writers feed this list: runs started through the API persist to the operational
    store, and every run (including CLI ones) is recorded as a trajectory. Merging them
    keeps the incident history, its metrics and its detail pages telling one story.
    """
    incidents = svc.storage.list_incidents(limit=limit + offset, offset=0)
    for row in incidents:
        row.setdefault("source", "live")
    seen = {row["id"] for row in incidents}
    for run in svc.recorded_runs():
        if run["id"] in seen:
            continue
        incidents.append(
            {
                "id": run["id"],
                "repository": run.get("repository"),
                "error": run.get("error"),
                "error_class": run.get("error_class"),
                "status": run.get("status"),
                "outcome": run.get("outcome"),
                "run_mode": run.get("run_mode"),
                "attempts": run.get("attempts"),
                "created_at": run.get("created_at"),
                "resolved_at": None,
                "source": "recorded",
                "label": run.get("label"),
            }
        )
        seen.add(run["id"])
    incidents.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return incidents[offset : offset + limit]


@router.get("/incidents/{incident_id}")
def get_incident(request: Request, incident_id: str) -> dict[str, Any]:
    svc = service(request)
    incident = svc.storage.get_incident(incident_id)
    if incident is None:
        recorded = svc.recorder.load(incident_id)
        if recorded is None:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
        incident = recorded
    return incident.model_dump(mode="json")


@router.get("/incidents/{incident_id}/events")
def incident_events(request: Request, incident_id: str) -> dict[str, Any]:
    svc = service(request)
    events = svc.storage.get_events(incident_id)
    if not events:
        events = svc.broker.recent(incident_id)
    return {"events": events}


@router.post("/incidents")
async def start_incident(request: Request) -> dict[str, Any]:
    svc = service(request)
    body = await _json_body(request)
    scenario = body.get("scenario") or None
    if scenario and scenario not in SCENARIOS:
        raise HTTPException(status_code=400, detail=f"Unknown scenario {scenario!r}")
    try:
        incident = svc.start_incident(
            scenario=scenario,
            trigger=str(body.get("trigger") or "manual"),
            error=str(body.get("error") or ""),
            background=bool(body.get("background", True)),
            replay=bool(body.get("replay", False)),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"incident": incident.model_dump(mode="json"), "scenario": scenario}


@router.post("/incidents/{incident_id}/rollback/approve")
def approve_rollback(request: Request, incident_id: str) -> dict[str, Any]:
    svc = service(request)
    try:
        return svc.approve_rollback(incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found") from exc


# ── live stream ─────────────────────────────────────────────


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    svc = service(request)
    queue = svc.broker.subscribe()

    async def generator():
        try:
            # Replay recent events so a client that connects mid-run is not blind.
            for payload in svc.broker.recent(limit=50):
                yield svc.broker.sse(payload)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield svc.broker.sse(payload)
        finally:
            svc.broker.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── memory ──────────────────────────────────────────────────


@router.get("/memory")
def memory_overview(request: Request) -> dict[str, Any]:
    return service(request).memory_overview()


@router.get("/memory/search")
def memory_search(
    request: Request,
    q: str = Query(..., min_length=2),
    bank: str = Query("incident"),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    return service(request).memory_search(q, bank=bank, limit=limit)


@router.get("/memory/runbook")
def runbook(request: Request, refresh: bool = False) -> dict[str, Any]:
    return service(request).runbook(refresh=refresh)


@router.get("/conventions")
def conventions(request: Request) -> dict[str, Any]:
    svc = service(request)
    return {"conventions": svc.conventions(), "bank": svc.memory.convention_bank}


@router.post("/memory/seed")
def seed_memory(request: Request) -> dict[str, Any]:
    return service(request).seed_memory()


# ── demo ────────────────────────────────────────────────────


@router.get("/demo/scenarios")
def demo_scenarios(request: Request) -> dict[str, Any]:
    svc = service(request)
    return {"scenarios": svc.scenarios(), "runs": svc.recorded_runs()[:20]}


@router.post("/demo/reset")
def demo_reset(request: Request) -> dict[str, Any]:
    """Clear the local operational record (Hindsight memory is deliberately untouched)."""
    svc = service(request)
    svc.storage.clear()
    return {"cleared": True, "note": "Hindsight memory was not modified"}


# ── helpers ─────────────────────────────────────────────────


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        raw = await request.body()
    except Exception:  # noqa: BLE001
        return {}
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _version() -> str:
    from .. import __version__

    return __version__
