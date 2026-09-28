"""Configuration invariants.

These tests encode the rule that makes the pool safe: it is derived from the worker
concurrency, so raising concurrency can never outrun the connections available to it.
"""

from __future__ import annotations

import pytest

from app.config import Settings, settings


def test_pool_size_supports_concurrency() -> None:
    assert settings.redis_pool_size >= settings.worker_concurrency, (
        f"redis_pool_size ({settings.redis_pool_size}) is smaller than "
        f"worker_concurrency ({settings.worker_concurrency}); the pool will be exhausted"
    )


def test_pool_size_is_derived_from_concurrency() -> None:
    """The pool must scale with concurrency, not be a hand-picked constant."""
    assert settings.redis_pool_size >= settings.worker_concurrency * 2, (
        f"redis_pool_size ({settings.redis_pool_size}) does not account for "
        f"worker_concurrency ({settings.worker_concurrency}); retries need headroom too"
    )


def test_validate_rejects_undersized_pool() -> None:
    with pytest.raises(ValueError):
        Settings(redis_pool_size=2, worker_concurrency=8).validate()


def test_settings_defaults_track_module_constants() -> None:
    assert Settings().redis_pool_size == settings.redis_pool_size
    assert Settings().worker_concurrency == settings.worker_concurrency
