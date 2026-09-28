#!/usr/bin/env python
"""Run Hindsight locally without Docker.

Uses the embedded server (`hindsight-all`), which bundles PostgreSQL (`pg0`) and talks to
Groq for memory extraction, so there is no container to manage and no cloud account
needed for the demo.

    venv/Scripts/python.exe scripts/start_hindsight.py

Then, in another terminal:
    venv/Scripts/python.exe scripts/run_incident.py --scenario concurrency

Leave this process running. Ctrl+C stops the server; data persists in the local `pg0`
store, so the agent keeps whatever it has learned.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from sre_agent.config import settings  # noqa: E402
from sre_agent.logging_setup import configure_stdout  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the embedded Hindsight server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8888, help="must match HINDSIGHT_BASE_URL")
    parser.add_argument("--model", default=settings.hindsight_api_llm_model)
    parser.add_argument("--provider", default=settings.hindsight_api_llm_provider)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    configure_stdout()

    api_key = settings.groq_api_key
    if not api_key:
        print(
            "GROQ_API_KEY is not set in .env. Hindsight needs an LLM to extract memories.\n"
            "Get a key at https://console.groq.com/keys and add it to .env.",
            file=sys.stderr,
        )
        return 2

    try:
        from hindsight import HindsightServer
    except ImportError:
        print(
            "The embedded Hindsight server is not installed.\n"
            "Install it with:  venv/Scripts/python.exe -m pip install hindsight-all",
            file=sys.stderr,
        )
        return 2

    # Hindsight defaults this to "auto", which Groq rejects with HTTP 400 on plans that
    # do not include that tier. It must be set before the server reads its config.
    os.environ.setdefault(
        "HINDSIGHT_API_LLM_GROQ_SERVICE_TIER", settings.hindsight_api_llm_groq_service_tier
    )

    print("Starting embedded Hindsight (embedded PostgreSQL, Groq extraction)...")
    print(f"  provider : {args.provider}")
    print(f"  model    : {args.model}")
    print(f"  url      : http://{args.host}:{args.port}")
    print("First start initialises a local database and can take a minute.\n")

    server = HindsightServer(
        db_url="pg0",
        llm_provider=args.provider,
        llm_api_key=api_key,
        llm_model=args.model,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )

    stopping = {"now": False}

    def _handle(signum, _frame):  # type: ignore[no-untyped-def]
        stopping["now"] = True
        print(f"\nReceived signal {signum}; shutting Hindsight down...")

    signal.signal(signal.SIGINT, _handle)
    try:
        signal.signal(signal.SIGTERM, _handle)
    except (AttributeError, ValueError):  # pragma: no cover - platform dependent
        pass

    started = time.perf_counter()
    server.start(timeout=settings.hindsight_start_timeout)
    print(f"Hindsight is up at {server.url} (started in {time.perf_counter() - started:.1f}s)")

    try:
        while not stopping["now"]:
            time.sleep(0.5)
    finally:
        try:
            server.stop(timeout=30.0)
        except Exception as exc:  # noqa: BLE001
            print(f"Shutdown warning: {exc}", file=sys.stderr)
        print("Hindsight stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
