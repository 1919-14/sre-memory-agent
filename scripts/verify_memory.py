#!/usr/bin/env python
"""Verify the Hindsight integration end to end.

Starts the embedded Hindsight server, exercises every memory operation the agent uses
(bank creation, memory policy, retain, recall, reflect, runbook mental model), prints the
real results, then shuts everything down.

    venv/Scripts/python.exe scripts/verify_memory.py

This is the check that matters most: if retain/recall do not work here, the agent has no
memory and the project has no thesis.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from sre_agent.config import settings  # noqa: E402
from sre_agent.logging_setup import configure_stdout, get_logger, setup_logging  # noqa: E402
from sre_agent.memory import MemoryStore, MemoryStoreError  # noqa: E402
from sre_agent.memory.embedded import configure_embedded_env  # noqa: E402

log = get_logger("verify-memory")

TEST_BANK = "sre:verify-probe"


def wait_for_server(store: MemoryStore, timeout: float = 240.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        reachable, _detail = store.health()
        if reachable:
            return True
        time.sleep(2.0)
    return False


def main() -> int:
    configure_stdout()
    setup_logging(force=True)

    if not settings.groq_api_key:
        print("GROQ_API_KEY is missing from .env — Hindsight needs it for extraction.")
        return 2

    store = MemoryStore(settings)
    server = None
    reachable, detail = store.health()
    started = time.perf_counter()

    if reachable:
        # Docker or Cloud is already serving this URL; verify against it and leave it up.
        print(f"Using the Hindsight server already running at {settings.hindsight_base_url}")
    else:
        try:
            from hindsight import HindsightServer
        except ImportError:
            print("No Hindsight server is reachable and the embedded server is not installed.")
            print(f"  reachability: {detail}")
            print("Start one:  docker run -p 8888:8888 -p 9999:9999 \\")
            print("              -e HINDSIGHT_API_LLM_PROVIDER=groq -e HINDSIGHT_API_LLM_API_KEY=<key> \\")
            print("              ghcr.io/vectorize-io/hindsight:latest")
            print("Or install the embedded one: pip install hindsight-all")
            return 2

        applied = configure_embedded_env(settings)
        if applied:
            print("Configured Hindsight LLM overrides:")
            for key, value in applied.items():
                print(f"  {key} = {value}")
            print()

        print("Starting embedded Hindsight (first run initialises a local database)...")
        server = HindsightServer(
            db_url="pg0",
            llm_provider=settings.hindsight_api_llm_provider,
            llm_api_key=settings.groq_api_key,
            llm_model=settings.hindsight_api_llm_model,
            host="127.0.0.1",
            port=8888,
            log_level="warning",
        )

    try:
        if server is not None:
            server.start(timeout=settings.hindsight_start_timeout)
            if not wait_for_server(store):
                print("Hindsight did not become reachable in time.")
                print(store.health()[1])
                return 1
            print(f"Server up after {time.perf_counter() - started:.1f}s at {settings.hindsight_base_url}")
        reachable, detail = store.health()
        print(f"health        : {detail}\n")

        failures: list[str] = []

        # ── 1. banks + policy ───────────────────────────────
        print("1. bank creation + memory policy")
        try:
            store.ensure_banks()
            print(f"   incident bank    : {store.incident_bank}")
            print(f"   convention bank  : {store.convention_bank}")
            print(f"   memory defense   : {store.memory_defense_note}")
        except MemoryStoreError as exc:
            failures.append(f"ensure_banks: {exc}")
            print(f"   FAILED: {exc}")

        # ── 2. retain ───────────────────────────────────────
        print("\n2. retain (decoupled so no application code depends on this)")
        retained = False
        try:
            # Through the store, not the raw client: the client must only ever be touched
            # from the SDK thread (`MemoryStore.invoke` guarantees that).
            result = store.invoke(
                "retain",
                bank_id=store.incident_bank,
                content=(
                    "INCIDENT REPORT INC-PROBE-1\n"
                    "Symptom: RedisConnectionError: connection pool exhausted in the delivery worker.\n"
                    "Root cause: worker concurrency was raised to 40 while the Redis pool stayed at 10.\n"
                    "Fix: derive the pool size from the worker concurrency.\n"
                    "Outcome: recovered, all tests passed."
                ),
                context="incident postmortem: production failure and recovery",
                document_id="INC-PROBE-1",
                tags=[
                    "kind:incident",
                    "error-class:connection-exhaustion",
                    "component:redis",
                    f"service:{settings.repo_dir.name}",
                    "outcome:recovered",
                ],
                metadata={"incident_id": "INC-PROBE-1", "commit": "a82f91cd"},
            )
            print(f"   retained         : success={getattr(result, 'success', '?')} "
                  f"items={getattr(result, 'items_count', '?')}")
            retained = True
        except Exception as exc:  # noqa: BLE001
            failures.append(f"retain: {exc}")
            print(f"   FAILED: {type(exc).__name__}: {exc}")

        # ── 3. recall ───────────────────────────────────────
        print("\n3. recall (tag-scoped, four retrieval strategies)")
        if retained:
            try:
                response = store.invoke(
                    "recall",
                    bank_id=store.incident_bank,
                    query="connection pool exhausted redis worker concurrency",
                    types=["world", "experience", "observation"],
                    tags=[f"service:{settings.repo_dir.name}", "error-class:connection-exhaustion"],
                    tags_match="any",
                    budget="mid",
                    include_source_facts=True,
                )
                results = getattr(response, "results", []) or []
                print(f"   memories found   : {len(results)}")
                for item in results[:5]:
                    score = getattr(getattr(item, "scores", None), "final", None)
                    print(
                        f"     - [{getattr(item, 'type', '?')}] "
                        f"{(getattr(item, 'text', '') or '')[:110]}"
                        f"{f'  (score {score:.3f})' if isinstance(score, float) else ''}"
                    )
                if not results:
                    failures.append("recall returned no memories for a just-retained incident")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"recall: {exc}")
                print(f"   FAILED: {type(exc).__name__}: {exc}")
        else:
            print("   skipped (retain failed)")

        # ── 4. conventions + rejected patterns ──────────────
        print("\n4. convention memory (second bank)")
        try:
            store.retain_conventions(
                [
                    "The Redis connection pool size must be derived from the worker concurrency.",
                    "Every connection checkout must be released on every path, including retries.",
                ]
            )
            convention_response = store.invoke(
                "recall",
                bank_id=store.convention_bank,
                query="how should the redis connection pool be sized?",
                tags=["kind:convention"],
                tags_match="any",
            )
            convention_results = getattr(convention_response, "results", []) or []
            print(f"   conventions found: {len(convention_results)}")
            for item in convention_results[:3]:
                print(f"     - {(getattr(item, 'text', '') or '')[:110]}")
            if not convention_results:
                failures.append("convention recall returned nothing")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"conventions: {exc}")
            print(f"   FAILED: {type(exc).__name__}: {exc}")

        # ── 5. reflect ──────────────────────────────────────
        print("\n5. reflect (reasoning across memories)")
        try:
            text, structured = store.reflect(
                "What are the recurring failure modes in this service and which fixes worked?"
            )
            print(f"   reflection       : {(text or '')[:300]}")
            print(f"   structured output: {'yes' if structured else 'no'}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"reflect: {exc}")
            print(f"   FAILED: {type(exc).__name__}: {exc}")

        # ── 6. runbook mental model ─────────────────────────
        print("\n6. runbook mental model")
        try:
            model_id = store.ensure_runbook("verify-runbook")
            content = store.read_runbook("verify-runbook") if model_id else ""
            print(f"   mental model     : {model_id or 'unavailable'}")
            print(f"   content          : {(content or '(empty)')[:200]}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"runbook: {exc}")
            print(f"   FAILED: {type(exc).__name__}: {exc}")

        # ── summary ─────────────────────────────────────────
        print("\n" + "=" * 74)
        if failures:
            print("RESULT: FAILURES")
            for item in failures:
                print(f"  - {item}")
            return 1
        print("RESULT: Hindsight integration working — retain, recall, conventions, reflect, runbook")
        print("=" * 74)
        return 0
    finally:
        store.close()
        if server is not None:
            try:
                server.stop(timeout=30.0)
            except Exception as exc:  # noqa: BLE001
                print(f"Shutdown warning: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
