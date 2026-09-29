"""Embedded Hindsight startup: environment ordering and the embedded database.

Both of these regressed on a Hugging Face Space, and both failed in ways that pointed at
something other than the real cause, so they are pinned here:

* `hindsight` snapshots the environment when it first parses it, so configuration written
  after the import is ignored — the server then sent Groq `service_tier: auto` and got 400.
* Hindsight's implicit `db_url="pg0"` startup reads the DSN out of `pg0 info`, whose `uri`
  field is absent while the instance is stopped, which surfaced as
  `ValueError: Database URL is required for migrations`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from sre_agent.config import Settings
from sre_agent.memory import embedded

REPO_ROOT = Path(__file__).resolve().parents[1]


class _Info:
    """Stand-in for `pg0.InstanceInfo`: only the fields the bootstrap reads."""

    def __init__(self, running: bool, port: int | None = None, uri: str | None = None) -> None:
        self.running = running
        self.port = port
        self.uri = uri

    def __repr__(self) -> str:  # keeps failure messages readable
        return f"_Info(running={self.running}, port={self.port}, uri={self.uri})"


def _install_fake_pg0(
    monkeypatch: pytest.MonkeyPatch,
    *,
    start: _Info | None = None,
    start_error: Exception | None = None,
    info: list[_Info] | None = None,
) -> dict[str, Any]:
    """Replace the `pg0` module with a scripted one and record how it was constructed."""
    recorded: dict[str, Any] = {}
    polls = list(info or [])

    class _Pg0:
        def __init__(self, **kwargs: Any) -> None:
            recorded["kwargs"] = kwargs

        def start(self) -> _Info:
            if start_error is not None:
                raise start_error
            assert start is not None
            return start

        def info(self) -> _Info:
            if polls:
                return polls.pop(0)
            assert start is not None, "info() polled after a failed start"
            return start

    module = types.ModuleType("pg0")
    module.Pg0 = _Pg0
    monkeypatch.setitem(sys.modules, "pg0", module)
    return recorded


def test_embedded_env_sets_the_tier_for_every_llm_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default config (verification) and the per-task configs all need the tier."""
    for var in ("HINDSIGHT_API_LLM_PROVIDER", "HINDSIGHT_API_LLM_MODEL", "HINDSIGHT_API_LLM_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    tier_vars = ("HINDSIGHT_API_LLM_GROQ_SERVICE_TIER", "HINDSIGHT_API_LLM_EXTRA_BODY")
    for var in (*tier_vars, *embedded._TASK_EXTRA_BODY_VARS):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(groq_api_key="gsk-test", hindsight_api_llm_groq_service_tier="on_demand")
    applied = embedded.configure_embedded_env(settings)

    assert applied["HINDSIGHT_API_LLM_GROQ_SERVICE_TIER"] == "on_demand"
    assert os.environ["HINDSIGHT_API_LLM_GROQ_SERVICE_TIER"] == "on_demand"
    # The global body covers the default config; the four per-task ones cover extraction,
    # reflect, consolidation and mental-model refresh.
    assert os.environ["HINDSIGHT_API_LLM_EXTRA_BODY"] == '{"service_tier": "on_demand"}'
    for var in embedded._TASK_EXTRA_BODY_VARS:
        assert os.environ[var] == '{"service_tier": "on_demand"}'
    assert os.environ["HINDSIGHT_API_LLM_MODEL"] == settings.hindsight_api_llm_model
    assert os.environ["HINDSIGHT_API_LLM_API_KEY"] == "gsk-test"


def test_embedded_env_does_not_overwrite_an_explicit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator's setting wins; that is the whole point of `setdefault`."""
    monkeypatch.setenv("HINDSIGHT_API_LLM_GROQ_SERVICE_TIER", "flex")
    monkeypatch.setenv("HINDSIGHT_API_LLM_EXTRA_BODY", '{"service_tier": "flex"}')

    embedded.configure_embedded_env(Settings(groq_api_key="gsk-test"))

    assert os.environ["HINDSIGHT_API_LLM_GROQ_SERVICE_TIER"] == "flex"
    assert os.environ["HINDSIGHT_API_LLM_EXTRA_BODY"] == '{"service_tier": "flex"}'


def test_importing_the_memory_module_does_not_import_hindsight() -> None:
    """The ordering in the launcher is only possible while nothing imports `hindsight` early.

    A fresh interpreter importing `sre_agent.memory.embedded` must leave `hindsight` out of
    `sys.modules`, or calling `configure_embedded_env` first would be too late for the
    launcher, however carefully the launcher is written.
    """
    code = (
        "import sys; import sre_agent.memory.embedded; "
        "print('hindsight' in sys.modules, 'hindsight_api' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False False", "hindsight was imported as a side effect"


def test_embedded_database_builds_the_dsn_when_pg0_omits_the_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`pg0 info` has no `uri` key at all while stopped, and pg0 0.15.2 can start without it."""
    recorded = _install_fake_pg0(monkeypatch, start=_Info(running=True, port=54329))

    dsn = embedded.ensure_embedded_database()

    assert dsn == "postgresql://hindsight:hindsight@127.0.0.1:54329/hindsight"
    # Same instance name and credentials Hindsight's own pg0 handling would use, so the
    # data directory (and therefore the agent's memory) is the one it already knows.
    assert recorded["kwargs"] == {
        "name": "hindsight",
        "username": "hindsight",
        "password": "hindsight",
        "database": "hindsight",
    }


def test_embedded_database_prefers_the_uri_pg0_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_pg0(
        monkeypatch,
        start=_Info(running=True, port=5433, uri="postgresql://u:p@127.0.0.1:5433/db"),
    )

    assert embedded.ensure_embedded_database() == "postgresql://u:p@127.0.0.1:5433/db"


def test_embedded_database_waits_for_a_start_that_is_not_ready_yet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero exit code is not readiness: the port only appears once the server accepts."""
    _install_fake_pg0(
        monkeypatch,
        start=_Info(running=False),
        info=[_Info(running=False), _Info(running=True, port=54330)],
    )

    dsn = embedded.ensure_embedded_database()

    assert dsn == "postgresql://hindsight:hindsight@127.0.0.1:54330/hindsight"


def test_embedded_database_timeout_names_the_real_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_pg0(monkeypatch, start=_Info(running=False))

    with pytest.raises(RuntimeError) as excinfo:
        embedded.ensure_embedded_database(ready_timeout=0)

    assert "did not report itself running" in str(excinfo.value)
    assert "pg0 logs --name hindsight" in str(excinfo.value)


def test_embedded_database_rejects_a_running_instance_without_a_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_pg0(monkeypatch, start=_Info(running=True, port=None, uri=None))

    with pytest.raises(RuntimeError, match="did not report a port"):
        embedded.ensure_embedded_database()


def test_embedded_database_start_failure_keeps_pg0s_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_pg0(monkeypatch, start_error=RuntimeError("could not bind port 5432"))

    with pytest.raises(RuntimeError) as excinfo:
        embedded.ensure_embedded_database()

    message = str(excinfo.value)
    assert "could not bind port 5432" in message
    assert "embedded PostgreSQL failed to start" in message


def test_missing_pg0_is_reported_as_a_missing_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pg0", None)

    with pytest.raises(RuntimeError, match="pg0-embedded"):
        embedded.ensure_embedded_database()


def test_verify_embedded_env_reports_the_tier_hindsight_actually_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hindsight_api = pytest.importorskip("hindsight_api")
    resolved = types.SimpleNamespace(llm_groq_service_tier="auto")
    monkeypatch.setattr(hindsight_api, "get_config", lambda: resolved)

    # `auto` is what Groq rejects with HTTP 400, so it must be surfaced, not swallowed.
    assert embedded.verify_embedded_env("on_demand") == "auto"
    assert embedded.verify_embedded_env("auto") == "auto"
