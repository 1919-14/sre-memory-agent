#!/usr/bin/env python
"""Run the SRE Memory Agent API (and the built frontend, if present).

    venv/Scripts/python.exe scripts/serve.py
    venv/Scripts/python.exe scripts/serve.py --port 8000 --reload
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from sre_agent.api import create_app  # noqa: E402
from sre_agent.config import settings  # noqa: E402
from sre_agent.logging_setup import configure_stdout, setup_logging  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the SRE Memory Agent API.")
    parser.add_argument("--host", default=settings.api_host)
    parser.add_argument("--port", type=int, default=settings.api_port)
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    args = parser.parse_args()

    configure_stdout()
    setup_logging(force=True)

    if args.reload:
        import uvicorn

        uvicorn.run(
            "sre_agent.api.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=True,
            reload_dirs=[str(REPO_ROOT / "src")],
        )
        return 0

    import uvicorn

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
