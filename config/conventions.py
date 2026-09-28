"""Standing engineering conventions for the demo service.

These are seeded into the Hindsight *convention* bank and applied literally by the code
review gate. Editing this file and re-running `scripts/seed_memory.py` is how a team would
teach the agent its own house rules.

Keep each entry concrete and checkable — a convention the reviewer cannot verify
mechanically becomes noise.
"""

from __future__ import annotations

CONVENTIONS: list[str] = [
    # Connection / resource management
    "The Redis connection pool size must be DERIVED from the worker concurrency "
    "(pool = max(8, concurrency * 2)). Hardcoding REDIS_POOL_SIZE is rejected: it silently "
    "decouples the pool from the load that consumes it.",
    "Every connection checkout must be matched by exactly one release on EVERY path, "
    "including exceptions and retries. Prefer try/finally. A retry must never abandon a "
    "checked-out connection.",
    "Resource limits (pool size, timeouts, retry counts) belong in app/config.py, never "
    "inline in the module that uses them.",
    # Error handling
    "Bare `except:` is rejected. Catch the specific exception type.",
    "`except Exception: pass` is rejected: swallowed errors hide production failures.",
    # Testing
    "Never weaken or delete a test to make a suite pass. `assert True`, `pytest.skip` and "
    "`@pytest.mark.xfail` on a failing test are all rejected.",
    "Every bug fix must be provable by a test that fails before the fix and passes after it.",
    # Configuration / credentials
    "Never hardcode credentials, tokens or environment-specific URLs in application code.",
    "An expired credential is NOT a code defect. Rotate the token; do not extend an expiry "
    "constant to make a test pass.",
    # Change hygiene
    "Configuration changes alone are not acceptable fixes unless the configuration value "
    "itself was wrong and the correct value is derivable from another setting.",
    "Fixes must be minimal: do not reformat, rename, reorder imports, or refactor "
    "unrelated code in the same change.",
    "No new dependencies without an explicit justification in the change description.",
]

DEFAULT_COMPONENT = "config"
