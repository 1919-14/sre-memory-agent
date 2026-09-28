"""A small Redis client with a bounded connection pool.

Deliberately dependency-free so the delivery worker can run anywhere, including inside a
sandbox with no network access.
"""

from __future__ import annotations

import threading


class ConnectionPoolExhausted(RuntimeError):
    """Raised when every connection in the pool is checked out."""


class TransientRedisError(RuntimeError):
    """A retryable Redis error (timeout, failover, temporary pressure)."""


class Connection:
    def __init__(self, conn_id: str) -> None:
        self.conn_id = conn_id

    def run(self, job) -> dict:
        """Execute one delivery job. Raises TransientRedisError to simulate a retry."""
        if job.transient_failures > 0:
            # A real-world blip: the connection was handed out, the command timed out,
            # and the caller must retry. The caller still owns the connection.
            job.transient_failures -= 1
            raise TransientRedisError(f"connection {self.conn_id} timed out for job {job.id}")
        return {"job_id": job.id, "channel": job.channel, "status": "delivered"}


class RedisClient:
    """Bounded pool. Every checkout must be matched by exactly one release."""

    def __init__(self, pool_size: int, *, host: str = "localhost") -> None:
        self.pool_size = pool_size
        self.host = host
        self._in_use = 0
        self._counter = 0
        self._peak = 0
        self._lock = threading.Lock()

    # ── pool accounting (observable, so failures are diagnosable) ──
    @property
    def in_use(self) -> int:
        return self._in_use

    @property
    def peak_in_use(self) -> int:
        return self._peak

    def _acquire(self) -> Connection:
        with self._lock:
            if self._in_use >= self.pool_size:
                raise ConnectionPoolExhausted(
                    f"Redis connection pool exhausted: {self._in_use} of "
                    f"{self.pool_size} connections are in use (host={self.host})"
                )
            self._in_use += 1
            self._peak = max(self._peak, self._in_use)
            self._counter += 1
            return Connection(f"conn-{self._counter:04d}")

    def _release(self, connection: Connection) -> None:
        with self._lock:
            self._in_use = max(0, self._in_use - 1)

    # ── job execution ───────────────────────────────────────
    def execute(self, job, *, max_attempts: int = 3) -> dict:
        """Run a job, retrying transient errors on a fresh connection.

        The connection is released on EVERY path — success and failure alike — so a
        retry can never leak one. That invariant is what keeps the pool from draining.
        """
        last_error: Exception | None = None
        for _attempt in range(max_attempts):
            connection = self._acquire()
            try:
                return connection.run(job)
            except TransientRedisError as exc:
                last_error = exc
            finally:
                self._release(connection)
        raise RuntimeError(f"job {job.id} failed after {max_attempts} attempts") from last_error
