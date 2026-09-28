"""Delivery worker pool.

Runs jobs concurrently using exactly `settings.worker_concurrency` workers, against a
Redis pool of `settings.redis_pool_size` connections.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .config import Settings, settings as default_settings
from .jobs import Job
from .redis_client import ConnectionPoolExhausted, RedisClient


@dataclass
class RunReport:
    delivered: int = 0
    failed: int = 0
    exhausted: int = 0
    errors: list[str] = field(default_factory=list)
    peak_connections: int = 0
    pool_size: int = 0
    concurrency: int = 0

    @property
    def total(self) -> int:
        return self.delivered + self.failed + self.exhausted

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.exhausted == 0


def build_client(settings: Settings | None = None) -> RedisClient:
    settings = settings or default_settings
    return RedisClient(pool_size=settings.redis_pool_size, host=settings.redis_host)


def deliver(job: Job, client: RedisClient, settings: Settings | None = None) -> dict:
    settings = settings or default_settings
    return client.execute(job, max_attempts=settings.job_max_attempts)


def run_jobs(
    jobs: list[Job],
    *,
    settings: Settings | None = None,
    client: RedisClient | None = None,
) -> RunReport:
    """Deliver every job using the configured worker concurrency."""
    settings = settings or default_settings
    settings.validate()
    client = client or build_client(settings)

    report = RunReport(
        pool_size=settings.redis_pool_size,
        concurrency=settings.worker_concurrency,
    )

    with ThreadPoolExecutor(max_workers=settings.worker_concurrency) as pool:
        futures = {pool.submit(deliver, job, client, settings): job for job in jobs}
        for future in as_completed(futures):
            job = futures[future]
            try:
                future.result()
                report.delivered += 1
            except ConnectionPoolExhausted as exc:
                report.exhausted += 1
                if len(report.errors) < 10:
                    report.errors.append(f"{job.id}: {exc}")
            except Exception as exc:  # noqa: BLE001 - report, never crash the batch
                report.failed += 1
                if len(report.errors) < 10:
                    report.errors.append(f"{job.id}: {type(exc).__name__}: {exc}")

    report.peak_connections = client.peak_in_use
    return report
