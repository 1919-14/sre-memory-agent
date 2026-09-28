#!/usr/bin/env python
"""Run the SRE Memory Agent against one demo scenario.

    # scenario 1 (fixable, no prior memory)
    venv/Scripts/python.exe scripts/run_incident.py --scenario concurrency

    # scenario 2 (same error class, different root cause -> memory must be refused)
    venv/Scripts/python.exe scripts/run_incident.py --scenario leak

    # scenario 3 (credential expired -> escalate, no patch)
    venv/Scripts/python.exe scripts/run_incident.py --scenario auth

Flags:
    --offline     use the deterministic scripted LLM (no network calls)
    --no-memory   run without Hindsight, to show the cold-start behaviour
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from sre_agent.agent import SREAgent, TrajectoryRecorder  # noqa: E402
from sre_agent.agent.replay import ReplaySource  # noqa: E402
from sre_agent.config import settings  # noqa: E402
from sre_agent.llm import build_llm  # noqa: E402
from sre_agent.logging_setup import setup_logging  # noqa: E402
from sre_agent.memory import MemoryStore  # noqa: E402
from sre_agent.models import Incident, Outcome, RunMode  # noqa: E402
from sre_agent.storage import Storage  # noqa: E402
from sre_agent.tools.git_tools import GitRepo, clean_pycache  # noqa: E402

SCENARIOS = ("concurrency", "leak", "auth")


def switch_scenario(name: str) -> str:
    repo = GitRepo(settings.repo_dir)
    if not repo.is_repo():
        raise SystemExit(
            f"{settings.repo_dir} is not a git repository.\n"
            "Run: venv/Scripts/python.exe scripts/setup_demo_repo.py"
        )
    branch = f"scenario/{name}"
    # `-f` matters: a previous incident that rolled back restores the known-good working
    # tree without committing, and a plain checkout would *preserve* those local changes.
    # The scenario's fault would then never be reinstated and the run would report
    # "17 passed" against fixed code — silently breaking the demo.
    repo._run("checkout", "-f", "-q", branch)
    # Switching scenarios can leave stale bytecode behind; two versions of the same
    # file often differ by one character, so Python may happily reuse the old module.
    clean_pycache(settings.repo_dir)
    return repo.current_commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one incident end to end.")
    parser.add_argument("--scenario", choices=SCENARIOS, default="concurrency")
    parser.add_argument("--offline", action="store_true", help="use the scripted LLM")
    parser.add_argument("--no-memory", action="store_true", help="skip Hindsight entirely")
    parser.add_argument("--quiet", action="store_true", help="suppress debug logging")
    args = parser.parse_args()

    if args.quiet:
        settings.log_level = "WARNING"
    setup_logging(force=True)

    print("=" * 78)
    print(f"SRE Memory Agent — incident run ({args.scenario})")
    print("=" * 78)

    commit = switch_scenario(args.scenario)
    good_commit = GitRepo(settings.repo_dir).rev_parse("good")
    print(f"repository : {settings.repo_dir}")
    print(f"branch     : scenario/{args.scenario} @ {commit[:8]}")
    print(f"known good : {good_commit[:8]}")

    memory = None
    if not args.no_memory:
        memory = MemoryStore(settings)
        reachable, detail = memory.health()
        print(f"hindsight  : {'reachable' if reachable else 'UNAVAILABLE'} — {detail}")
        if reachable:
            print(f"banks      : {memory.incident_bank} | {memory.convention_bank}")
        else:
            print("             running degraded: no historical memory will be used")
    else:
        print("hindsight  : disabled (--no-memory)")

    # Offline mode replays the real LLM outputs from a recorded run, so it can still
    # complete a repair without a network call. Without a recorded patch it cannot.
    replay = ReplaySource.load(settings, branch=f"scenario/{args.scenario}") if args.offline else None
    llm = build_llm(
        force_scripted=args.offline,
        scripted_handlers=replay.handlers() if replay else None,
    )
    print(f"llm        : {type(llm).__name__} (simulated={llm.simulated})")
    if replay:
        print(f"replay     : {replay.describe()}")
        print(f"             handlers: {', '.join(sorted(replay.handlers()))}")
    elif args.offline:
        print("replay     : no recorded trajectory with a patch — this offline run cannot")
        print("             generate a repair and will end in a rollback by design.")
    print("-" * 78)

    def on_event(event) -> None:
        marker = {
            "ok": "   ",
            "warn": " ! ",
            "failed": " x ",
            "running": " > ",
            "skipped": " - ",
            "pending": " . ",
        }.get(getattr(event.status, "value", "ok"), "   ")
        # Events are stored in UTC; show them in the operator's local time.
        stamp = event.timestamp.astimezone().strftime("%H:%M:%S")
        print(f"{stamp}{marker}{event.stage.value:<24} {event.message}")

    agent = SREAgent(
        settings=settings,
        llm=llm,
        memory=memory,
        event_sink=on_event,
    )
    for warning in agent.prepare():
        print(f"  warning: {warning}")

    incident = Incident(
        repository=settings.repo_dir.name,
        error="CI failure on the current commit",
        trigger="test-run",
        previous_good_commit=good_commit,
        branch=f"scenario/{args.scenario}",
        run_mode=RunMode.REPLAY if llm.simulated else RunMode.LIVE,
        simulated=llm.simulated,
    )

    started = time.perf_counter()
    incident = agent.run_incident(incident)
    elapsed = time.perf_counter() - started

    TrajectoryRecorder(settings).save(incident, label=args.scenario)
    # Persist to the same operational store the dashboard reads. Without this a CLI run
    # existed only as a trajectory file, so the UI's incident history and its metrics
    # would disagree about what had happened.
    try:
        Storage(settings).save_incident(incident)
    except Exception as exc:  # noqa: BLE001 - a failed write must not lose the run summary
        print(f"  warning: could not persist incident to the operational store: {exc}")

    # ── summary ─────────────────────────────────────────────
    print("-" * 78)
    print(f"incident   : {incident.id}")
    print(f"status     : {incident.status.value}")
    print(f"outcome    : {incident.outcome.value if incident.outcome else 'n/a'}")
    if incident.classification:
        c = incident.classification
        print(
            f"class      : {c.error_class.value} (confidence {c.confidence:.2f}, "
            f"source {c.source}, fixability {c.likely_fixability.value})"
        )
    print(f"memories   : {incident.metrics.memories_recalled} recalled, "
          f"{incident.metrics.memories_reused} reused, "
          f"{incident.metrics.memories_rejected} rejected")
    print(f"attempts   : {len(incident.attempts)} proposed, "
          f"{incident.metrics.attempts_used} executed")
    print(f"llm calls  : {llm.calls} ({llm.tokens} tokens)")
    print(f"duration   : {elapsed:.1f}s")
    if incident.root_cause:
        print(f"root cause : {incident.root_cause[:300]}")
    if incident.final_resolution:
        print(f"resolution : {incident.final_resolution[:300]}")
    if incident.verification:
        print(f"verified   : {incident.verification[:300]}")
    if incident.escalation_reason:
        print(f"escalation : {incident.escalation_reason[:300]}")
    if incident.degraded:
        for warning in incident.warnings:
            print(f"degraded   : {warning}")

    if incident.outcome is Outcome.RECOVERED:
        print("\nResult: RECOVERED — the fix was verified in the sandbox.")
    elif incident.outcome is Outcome.ESCALATED:
        print("\nResult: ESCALATED — correctly handed to a human, no patch attempted.")
    elif incident.outcome is Outcome.ROLLED_BACK:
        print("\nResult: ROLLED BACK — budget exhausted, repository restored to known-good.")
    else:
        print(f"\nResult: {incident.outcome.value if incident.outcome else 'incomplete'}")

    print("=" * 78)
    if memory is not None:
        memory.close()
    if hasattr(llm, "close"):
        llm.close()
    import gc

    gc.collect()
    return 0 if incident.outcome in (Outcome.RECOVERED, Outcome.ESCALATED, Outcome.ROLLED_BACK) else 1


if __name__ == "__main__":
    raise SystemExit(main())
