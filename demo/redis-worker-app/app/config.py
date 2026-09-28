"""Service configuration.

The connection pool is sized FROM the worker concurrency on purpose: a change to worker
concurrency must never be able to outrun the pool that feeds it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# ── Redis / queue worker settings ───────────────────────────
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

# Number of concurrent delivery workers.
WORKER_CONCURRENCY = 4

# Every in-flight job needs a connection, and retries can double that briefly, so the
# pool is derived rather than chosen by hand.
REDIS_POOL_SIZE = max(8, WORKER_CONCURRENCY * 2)

# How many times a job is retried when Redis returns a transient error.
JOB_MAX_ATTEMPTS = 3
JOB_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class Settings:
    redis_host: str = REDIS_HOST
    redis_port: int = REDIS_PORT
    worker_concurrency: int = WORKER_CONCURRENCY
    redis_pool_size: int = REDIS_POOL_SIZE
    job_max_attempts: int = JOB_MAX_ATTEMPTS
    job_timeout_seconds: int = JOB_TIMEOUT_SECONDS

    def validate(self) -> None:
        if self.redis_pool_size < self.worker_concurrency:
            raise ValueError(
                f"redis_pool_size ({self.redis_pool_size}) must be at least "
                f"worker_concurrency ({self.worker_concurrency})"
            )


settings = Settings()
