#!/usr/bin/env python
"""Build the demo repository the agent operates on.

Creates `data/demo-repo` from the tracked template at `demo/redis-worker-app`, with a
git history that contains three real, independently fixable failures:

    good                          baseline — full suite passes
    scenario/concurrency          pool size decoupled from worker concurrency  (fixable)
    scenario/leak                 connections not released on the retry path   (fixable)
    scenario/auth                 billing credential expired                   (escalate)

The leak scenario is the important one: it fails with the *same error class* as the
concurrency scenario but has a completely different root cause. A memory agent that
blindly replays its previous fix gets it wrong there — which is exactly the behaviour the
demo is built to show.

Usage:
    venv/Scripts/python.exe scripts/setup_demo_repo.py          # build + verify
    venv/Scripts/python.exe scripts/setup_demo_repo.py --list
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from sre_agent.config import settings  # noqa: E402
from sre_agent.tools.fsutil import clean_pycache, force_rmtree  # noqa: E402

LIVE = settings.live_repo_dir
TEMPLATE = settings.template_dir

GOOD_COMMIT_MESSAGE = "baseline: delivery worker with Redis pool derived from concurrency"


# ── scenario transforms ─────────────────────────────────────


def apply_concurrency_regression(root: Path) -> str:
    """Raise worker concurrency without resizing the pool, and hardcode the pool size."""
    config = root / "app" / "config.py"
    text = config.read_text(encoding="utf-8")

    old_block = (
        "# Number of concurrent delivery workers.\n"
        "WORKER_CONCURRENCY = 4\n"
        "\n"
        "# Every in-flight job needs a connection, and retries can double that briefly, so the\n"
        "# pool is derived rather than chosen by hand.\n"
        "REDIS_POOL_SIZE = max(8, WORKER_CONCURRENCY * 2)"
    )
    new_block = (
        "# Number of concurrent delivery workers.\n"
        "WORKER_CONCURRENCY = 40\n"
        "\n"
        "# Pool size tuned for our previous traffic level.\n"
        "REDIS_POOL_SIZE = 10"
    )
    if old_block not in text:
        raise SystemExit(
            "Cannot build the concurrency scenario: app/config.py does not match the "
            "expected baseline. Was the template modified?"
        )
    config.write_text(text.replace(old_block, new_block), encoding="utf-8")
    return "chore: raise worker concurrency to 40 for the launch batch"


def apply_connection_leak(root: Path) -> str:
    """Stop releasing connections on the retry path."""
    client = root / "app" / "redis_client.py"
    text = client.read_text(encoding="utf-8")

    old_doc = (
        '        """Run a job, retrying transient errors on a fresh connection.\n'
        "\n"
        "        The connection is released on EVERY path — success and failure alike — so a\n"
        "        retry can never leak one. That invariant is what keeps the pool from draining.\n"
        '        """'
    )
    new_doc = '        """Run a job, retrying transient errors on a fresh connection."""'

    old_body = (
        "        last_error: Exception | None = None\n"
        "        for _attempt in range(max_attempts):\n"
        "            connection = self._acquire()\n"
        "            try:\n"
        "                return connection.run(job)\n"
        "            except TransientRedisError as exc:\n"
        "                last_error = exc\n"
        "            finally:\n"
        "                self._release(connection)\n"
        "        raise RuntimeError(f\"job {job.id} failed after {max_attempts} attempts\") from last_error"
    )
    new_body = (
        "        for _attempt in range(max_attempts):\n"
        "            connection = self._acquire()\n"
        "            try:\n"
        "                return connection.run(job)\n"
        "            except TransientRedisError:\n"
        "                # Take a fresh connection for the retry.\n"
        "                connection = self._acquire()\n"
        "        raise RuntimeError(f\"job {job.id} failed after {max_attempts} attempts\")"
    )

    if old_body not in text or old_doc not in text:
        raise SystemExit(
            "Cannot build the leak scenario: app/redis_client.py does not match the "
            "expected baseline. Was the template modified?"
        )
    text = text.replace(old_doc, new_doc).replace(old_body, new_body)
    client.write_text(text, encoding="utf-8")
    return "refactor: simplify the retry path in RedisClient.execute"


def apply_expired_credential(root: Path) -> str:
    """Point the billing token at an expiry that has already passed."""
    billing = root / "app" / "billing.py"
    text = billing.read_text(encoding="utf-8")

    old = 'BILLING_TOKEN_EXPIRES_AT = os.environ.get("BILLING_TOKEN_EXPIRES_AT", "2027-06-30T00:00:00Z")'
    new = 'BILLING_TOKEN_EXPIRES_AT = os.environ.get("BILLING_TOKEN_EXPIRES_AT", "2026-08-01T00:00:00Z")'
    if old not in text:
        raise SystemExit(
            "Cannot build the auth scenario: app/billing.py does not match the expected "
            "baseline. Was the template modified?"
        )
    billing.write_text(text.replace(old, new), encoding="utf-8")
    return "chore: update the billing token expiry constant"


SCENARIOS: list[tuple[str, str, object, str]] = [
    (
        "concurrency",
        "bad-concurrency",
        apply_concurrency_regression,
        "Pool decoupled from concurrency. Same class as the leak scenario, "
        "different root cause.",
    ),
    (
        "leak",
        "bad-leak",
        apply_connection_leak,
        "Connection leak on the retry path. Fixable only by releasing the connection.",
    ),
    (
        "auth",
        "bad-auth",
        apply_expired_credential,
        "Expired billing credential. Not code-fixable — must escalate.",
    ),
]


# ── git plumbing ────────────────────────────────────────────


def git(*args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(LIVE), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{proc.stderr.strip()}")
    return proc.stdout


def build(quiet: bool = False) -> None:
    if LIVE.exists():
        if not force_rmtree(LIVE):
            raise SystemExit(
                f"Could not remove the existing demo repository at {LIVE}. "
                "Close any editor or terminal sitting in it and retry."
            )
    LIVE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        TEMPLATE,
        LIVE,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".git", "*.pyc"),
    )

    git("init", "-q", "-b", "main")
    git("config", "user.email", "sre-demo@example.com")
    git("config", "user.name", "Delivery Platform")
    git("add", "-A")
    git("commit", "-q", "-m", GOOD_COMMIT_MESSAGE)
    git("tag", "good")

    for name, tag, transform, _description in SCENARIOS:
        git("checkout", "-q", "-b", f"scenario/{name}", "good")
        message = transform(LIVE)  # type: ignore[operator]
        git("add", "-A")
        git("commit", "-q", "-m", message)
        git("tag", tag)

    # Default starting point for a fresh run.
    git("checkout", "-q", "scenario/concurrency")

    if not quiet:
        print(f"Built demo repository at {LIVE}")
        print(f"  baseline commit: {git('rev-parse', 'good').strip()[:8]} (tag: good)")
        for name, tag, _transform, description in SCENARIOS:
            sha = git("rev-parse", tag).strip()[:8]
            print(f"  {tag:<16} {sha}  {description}")
        print("\nSwitch scenario:  git -C data/demo-repo checkout scenario/<name>")


# ── verification ────────────────────────────────────────────


def run_suite(label: str) -> tuple[int, list[str]]:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            "-rf",
            "--tb=no",
        ],
        cwd=str(LIVE),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    failing = sorted(
        {
            line.split()[1]
            for line in proc.stdout.splitlines()
            if line.startswith(("FAILED", "ERROR")) and len(line.split()) > 1
        }
    )
    return proc.returncode, failing


def verify() -> bool:
    print("Verifying each scenario produces the intended failure...\n")
    print(f"{'scenario':<18}{'exit':<6}{'failing tests'}")
    print("-" * 78)
    all_ok = True
    expectations = {
        "good": 0,
        "scenario/concurrency": None,
        "scenario/leak": None,
        "scenario/auth": None,
    }
    for ref, expected_exit in expectations.items():
        git("checkout", "-q", ref)
        # Two scenario files can differ by a single character; stale bytecode would make
        # this verification (and any real run) silently test the wrong revision.
        clean_pycache(LIVE)
        code, failing = run_suite(ref)
        label = ref.replace("scenario/", "")
        if expected_exit is not None and code != expected_exit:
            all_ok = False
            print(f"{label:<18}{code:<6}UNEXPECTED (expected exit {expected_exit})")
            continue
        if expected_exit is None and code == 0:
            all_ok = False
            print(f"{label:<18}{code:<6}UNEXPECTED: scenario passes, so it cannot be a demo")
            continue
        detail = ", ".join(f.split("::")[-1] for f in failing) or "—"
        print(f"{label:<18}{code:<6}{detail}")

    git("checkout", "-q", "scenario/concurrency")
    print()
    if all_ok:
        print("All scenarios behave as intended.")
    else:
        print("SCENARIO MISMATCH — the demo would not show what it claims to.")
    return all_ok


def list_scenarios() -> None:
    print(f"Live demo repo: {LIVE}  (exists: {LIVE.exists()})")
    print(f"Template:       {TEMPLATE}")
    for name, tag, _transform, description in SCENARIOS:
        print(f"  {name:<14} tag={tag:<16} {description}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the demo SRE repository.")
    parser.add_argument("--list", action="store_true", help="list scenarios and exit")
    parser.add_argument("--no-verify", action="store_true", help="skip suite verification")
    args = parser.parse_args()

    if args.list:
        list_scenarios()
        return 0

    build()
    if not args.no_verify:
        print()
        if not verify():
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
