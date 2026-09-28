"""Connection pool semantics.

A checkout must always be matched by exactly one release, on every path. These tests fail
if a retry path can leak a connection, which is the failure mode that drains a pool even
when it is correctly sized.
"""

from __future__ import annotations

import pytest

from app.jobs import Job
from app.redis_client import ConnectionPoolExhausted, RedisClient, TransientRedisError


def test_pool_exhaustion_raises() -> None:
    client = RedisClient(pool_size=2)
    client._acquire()
    client._acquire()
    with pytest.raises(ConnectionPoolExhausted):
        client._acquire()


def test_connections_released_after_transient_failure() -> None:
    client = RedisClient(pool_size=4)
    job = Job(id="msg-000001", transient_failures=1)

    result = client.execute(job, max_attempts=3)

    assert result["status"] == "delivered"
    assert client.in_use == 0, f"{client.in_use} connection(s) leaked after a retry"


def test_connections_released_on_every_path_for_a_batch() -> None:
    client = RedisClient(pool_size=4)
    jobs = [Job(id=f"msg-{i:06d}", transient_failures=1) for i in range(12)]

    for job in jobs:
        client.execute(job, max_attempts=3)

    assert client.in_use == 0, f"{client.in_use} connection(s) leaked across the batch"
    assert client.peak_in_use <= client.pool_size


def test_transient_error_is_retried_on_a_fresh_connection() -> None:
    client = RedisClient(pool_size=2)
    job = Job(id="msg-000042", transient_failures=2)

    result = client.execute(job, max_attempts=3)

    assert result["job_id"] == "msg-000042"
    assert client.in_use == 0


def test_persistent_transient_errors_raise_runtime_error() -> None:
    client = RedisClient(pool_size=2)
    job = Job(id="msg-000099", transient_failures=10)

    with pytest.raises(RuntimeError):
        client.execute(job, max_attempts=3)

    assert client.in_use == 0, "a permanently failing job must not leak its connection"
