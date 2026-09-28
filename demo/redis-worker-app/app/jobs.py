"""Delivery jobs and the fixtures used by tests and the local runner."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

CHANNELS = ("email", "sms", "push")
QUEUES = ("notifications", "marketing", "transactional")
RECIPIENTS = (
    "a.kapoor@example.com",
    "m.iyer@example.com",
    "s.venkatesan@example.com",
    "ops-team@example.com",
    "r.nair@example.com",
    "+91-90000-11223",
    "+91-90000-44556",
)


@dataclass
class Job:
    id: str
    channel: str = "email"
    queue: str = "notifications"
    recipient: str = ""
    # Number of transient Redis errors to simulate before this job succeeds. Decremented
    # on each failure, so the retry path is exercised by real tests, not just by traffic.
    transient_failures: int = 0
    payload: dict = field(default_factory=dict)


def build_jobs(count: int, *, transient_every: int = 0, seed: int = 7) -> list[Job]:
    """Generate a deterministic batch of jobs.

    `transient_every` makes every Nth job hit one transient Redis error first.
    """
    rng = random.Random(seed)
    jobs: list[Job] = []
    for index in range(count):
        transient = 1 if (transient_every > 0 and index % transient_every == 0) else 0
        jobs.append(
            Job(
                id=f"msg-{index:06d}",
                channel=rng.choice(CHANNELS),
                queue=rng.choice(QUEUES),
                recipient=rng.choice(RECIPIENTS),
                transient_failures=transient,
                payload={"template": f"txn-{index % 17}", "batch": index // 50},
            )
        )
    return jobs
