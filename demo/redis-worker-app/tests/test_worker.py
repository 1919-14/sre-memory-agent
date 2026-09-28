"""Delivery worker behaviour."""

from __future__ import annotations

from app.config import Settings
from app.jobs import build_jobs
from app.redis_client import RedisClient
from app.worker import run_jobs


def test_all_jobs_complete() -> None:
    """A realistic batch, a tenth of which hit one transient error first."""
    jobs = build_jobs(200, transient_every=10)

    report = run_jobs(jobs)

    assert report.ok, f"errors while delivering: {report.errors[:5]}"
    assert report.delivered == 200
    assert report.total == 200


def test_report_records_pool_and_concurrency() -> None:
    jobs = build_jobs(20)

    report = run_jobs(jobs)

    assert report.pool_size == Settings().redis_pool_size
    assert report.concurrency == Settings().worker_concurrency
    assert report.peak_connections <= report.pool_size


def test_retry_path_does_not_leak_connections() -> None:
    """Every job needs one retry, so any leak on the retry path shows up immediately."""
    client = RedisClient(pool_size=8)
    settings = Settings(worker_concurrency=4, redis_pool_size=8)
    jobs = build_jobs(8, transient_every=1)

    report = run_jobs(jobs, settings=settings, client=client)

    assert report.ok, f"errors while delivering: {report.errors[:5]}"
    assert client.in_use == 0, f"{client.in_use} connection(s) leaked during the batch"


def test_concurrency_is_respected() -> None:
    jobs = build_jobs(40)
    settings = Settings(worker_concurrency=4, redis_pool_size=8)

    report = run_jobs(jobs, settings=settings)

    assert report.delivered == 40
    assert report.peak_connections <= settings.redis_pool_size
