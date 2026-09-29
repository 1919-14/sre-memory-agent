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

The order of the three steps in `main` is not cosmetic — Hindsight reads its configuration
and its database URL at import time, so both have to exist before `hindsight` is imported.
`src/sre_agent/memory/embedded.py` explains what goes wrong otherwise.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from sre_agent.config import settings  # noqa: E402
from sre_agent.logging_setup import configure_stdout  # noqa: E402
from sre_agent.memory.embedded import (  # noqa: E402
    configure_embedded_env,
    ensure_embedded_database,
    stop_embedded_database,
    verify_embedded_env,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the embedded Hindsight server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8888, help="must match HINDSIGHT_BASE_URL")
    parser.add_argument("--model", default=settings.hindsight_api_llm_model)
    parser.add_argument("--provider", default=settings.hindsight_api_llm_provider)
    parser.add_argument("--log-level", default="info")
    parser.add_argument(
        "--db-url",
        default="",
        help="use an existing PostgreSQL (postgresql://...) instead of starting embedded pg0",
    )
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

    # Step 1 — the environment. This has to happen before `hindsight` is imported anywhere:
    # the library snapshots the environment when it first parses it, so a variable set after
    # the import is ignored (and Groq then rejects the default `service_tier: auto`).
    configure_embedded_env(settings)

    # Step 2 — the database. Started explicitly so that a pg0 failure is reported as a pg0
    # failure, and Hindsight receives a real DSN instead of the magic "pg0" string.
    if args.db_url:
        db_url = args.db_url
    else:
        try:
            db_url = ensure_embedded_database()
        except RuntimeError as exc:
            print(f"Embedded PostgreSQL is unavailable: {exc}", file=sys.stderr)
            print(
                "Hindsight needs a database. Pass --db-url to use an existing PostgreSQL, "
                "or use Hindsight Cloud by pointing HINDSIGHT_BASE_URL at it.",
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

    # Step 3 — confirm the library saw the configuration, rather than assuming it did.
    verify_embedded_env(settings.hindsight_api_llm_groq_service_tier)

    print("Starting embedded Hindsight (embedded PostgreSQL, Groq extraction)...")
    print(f"  provider : {args.provider}")
    print(f"  model    : {args.model}")
    print(f"  database : {'external, ' + db_url if args.db_url else 'embedded PostgreSQL'}")
    print(f"  url      : http://{args.host}:{args.port}")
    print("First start initialises a local database and can take a minute.\n")

    server = HindsightServer(
        db_url=db_url,
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
        if not args.db_url:
            stop_embedded_database()
        print("Hindsight stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
