"""Embedded Hindsight server support.

Running Hindsight locally with no Docker is convenient for a demo, but it exposes three
sharp edges that are worth documenting because they each cost real debugging time — two of
them on a public Hugging Face Space, where the only foreground is the boot log:

1. **`service_tier`.** Hindsight defaults to `service_tier="auto"`, and Groq rejects that
   with HTTP 400 on plans that do not include it:
   ``"`service_tier` `auto` is not available for this org"``.
   Pinning the tier needs two entries: the global knob
   (`HINDSIGHT_API_LLM_GROQ_SERVICE_TIER`) covers the calls that build a provider from the
   default configuration — LLM *verification* is one, and it is the first call the server
   makes — while fact *extraction*, *reflect* and *consolidation* build their own provider
   configuration and need per-task `extra_body` overrides plus the global one. All of them
   are set in :func:`configure_embedded_env`.

2. **Configuration is a snapshot taken at import.** `hindsight_api.config.get_config()`
   caches the parsed environment the first time anything in `hindsight` asks for it, so
   setting `HINDSIGHT_API_*` *after* `import hindsight` is silently ignored — the default
   (`auto`) is what goes on the wire. That is exactly how a Space kept sending
   `service_tier: auto` while the tier was configured a few lines below the import. Call
   :func:`configure_embedded_env` before the import, and :func:`verify_embedded_env` after
   it to report the value the library actually resolved.

3. **The database.** Hindsight can start its embedded PostgreSQL from the magic string
   `"pg0"`, but `MemoryEngine.initialize()` reads the connection URL out of
   `Pg0.start()`'s `info()`, whose `uri` field the pg0 CLI omits while the instance is
   stopped — so a start that returns before the server accepts connections leaves the URL
   unset and fails later as ``ValueError: Database URL is required for migrations``, naming
   neither pg0 nor the database. :func:`ensure_embedded_database` starts pg0 here instead
   and hands Hindsight a real DSN.

Tokens per minute are the remaining constraint: Hindsight's extraction and consolidation
passes are token-heavy, and Groq's free tier allows 8,000 TPM per model, which a handful of
retains will exhaust (HTTP 429). For a demo with many incidents, prefer Hindsight Cloud or a
paid tier — see `HINDSIGHT.md`.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from ..config import Settings, settings as default_settings
from ..logging_setup import get_logger

log = get_logger("hindsight-embedded")

# Tasks inside Hindsight that construct their own LLM provider configuration.
_TASK_EXTRA_BODY_VARS = (
    "HINDSIGHT_API_RETAIN_LLM_EXTRA_BODY",
    "HINDSIGHT_API_REFLECT_LLM_EXTRA_BODY",
    "HINDSIGHT_API_CONSOLIDATION_LLM_EXTRA_BODY",
    "HINDSIGHT_API_MENTAL_MODEL_REFRESH_LLM_EXTRA_BODY",
)

# The body every other call gets, including the default config used for verification.
_GLOBAL_LLM_EXTRA_BODY_VAR = "HINDSIGHT_API_LLM_EXTRA_BODY"

# Embedded PostgreSQL: these mirror `hindsight_api.pg0`'s defaults for the `"pg0"` URL, so
# pg0 finds the same instance — and the same data directory — Hindsight would have used.
_PG0_INSTANCE = "hindsight"
_PG0_USERNAME = "hindsight"
_PG0_PASSWORD = "hindsight"
_PG0_DATABASE = "hindsight"

# `pg0 start` returning 0 is not proof the server is up; this bounds how long we wait for it
# to say so. First start runs `initdb`, which is a few seconds, not a few minutes.
_PG0_READY_TIMEOUT = 120.0


def configure_embedded_env(settings: Settings | None = None) -> dict[str, str]:
    """Set the environment Hindsight needs *before* the server reads its config.

    This must run before ``hindsight`` is imported — the library snapshots the environment
    when it first parses it (see the module docstring).

    Returns the values applied, so a caller can print exactly what was configured.
    """
    settings = settings or default_settings
    tier = settings.hindsight_api_llm_groq_service_tier
    applied: dict[str, str] = {}

    os.environ.setdefault("HINDSIGHT_API_LLM_PROVIDER", settings.hindsight_api_llm_provider)
    os.environ.setdefault("HINDSIGHT_API_LLM_MODEL", settings.hindsight_api_llm_model)
    if settings.groq_api_key:
        os.environ.setdefault("HINDSIGHT_API_LLM_API_KEY", settings.groq_api_key)

    if settings.hindsight_api_llm_provider == "groq" and tier:
        os.environ.setdefault("HINDSIGHT_API_LLM_GROQ_SERVICE_TIER", tier)
        applied["HINDSIGHT_API_LLM_GROQ_SERVICE_TIER"] = tier

        # Every path that builds an LLM provider from the default config needs the global
        # body (verification among them); the four per-task paths below build their own.
        body = json.dumps({"service_tier": tier})
        os.environ.setdefault(_GLOBAL_LLM_EXTRA_BODY_VAR, body)
        applied[_GLOBAL_LLM_EXTRA_BODY_VAR] = body

        for var in _TASK_EXTRA_BODY_VARS:
            os.environ.setdefault(var, body)
            applied[var] = body

    log.info("configured embedded Hindsight env: %s", ", ".join(applied) or "no overrides")
    return applied


def verify_embedded_env(expected_tier: str | None = None) -> str | None:
    """Return the Groq tier Hindsight actually resolved, warning when it is not the wanted one.

    The check exists because the failure it catches is invisible: a variable set after the
    import is ignored and the request goes out with `service_tier: auto` (HTTP 400), which is
    only noticeable hundreds of log lines later. Importing `hindsight_api` here is safe — the
    caller has already imported `hindsight`, so the snapshot is taken either way.
    """
    try:
        from hindsight_api import get_config
    except ImportError:  # pragma: no cover - only reachable without hindsight installed
        return None

    tier = get_config().llm_groq_service_tier
    if expected_tier and tier != expected_tier:
        log.warning(
            "Hindsight resolved service tier %r, not %r: HINDSIGHT_API_LLM_GROQ_SERVICE_TIER "
            "was set after `hindsight` was imported, and the environment is snapshotted then",
            tier,
            expected_tier,
        )
    else:
        log.info("Hindsight Groq service tier in effect: %r", tier)
    return tier


def ensure_embedded_database(*, ready_timeout: float = _PG0_READY_TIMEOUT) -> str:
    """Start embedded PostgreSQL (pg0) and return the DSN to hand to Hindsight.

    See point 3 of the module docstring for why Hindsight's own pg0 startup is not used. The
    short version: this keeps the failure attached to the database. If pg0 refuses to start
    we raise with its own message, if it starts we wait until it reports itself running, and
    Hindsight is then given a plain ``postgresql://`` URL and never touches pg0 at all.
    """
    try:
        from pg0 import Pg0
    except ImportError as exc:
        raise RuntimeError(
            "embedded PostgreSQL is not installed. Install it with `pip install pg0-embedded`, "
            "or point HINDSIGHT_BASE_URL at a Hindsight that brings its own database."
        ) from exc

    instance = Pg0(
        name=_PG0_INSTANCE,
        username=_PG0_USERNAME,
        password=_PG0_PASSWORD,
        database=_PG0_DATABASE,
    )
    try:
        info = instance.start()
    except Exception as exc:  # noqa: BLE001 - pg0 raises its own error types
        raise RuntimeError(
            f"embedded PostgreSQL failed to start ({exc}); "
            f"inspect it with `pg0 logs --name {_PG0_INSTANCE}`"
        ) from exc

    # `running` flips only once the server accepts connections, so that — not pg0's exit
    # code — is the readiness signal. A running instance that then reports no port is a
    # contradiction, and `_embedded_dsn` says so instead of spinning here for nothing.
    deadline = time.monotonic() + ready_timeout
    while not info.running:
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"embedded PostgreSQL did not report itself running within {ready_timeout:.0f}s "
                f"({info!r}); inspect it with `pg0 logs --name {_PG0_INSTANCE}`"
            )
        time.sleep(0.5)
        info = instance.info()

    uri = info.uri or _embedded_dsn(info.port)
    log.info("embedded PostgreSQL is ready on 127.0.0.1:%s", info.port)
    return uri


def stop_embedded_database() -> None:
    """Best-effort stop, so the next start finds a cleanly shut down data directory."""
    try:
        from pg0 import Pg0
    except ImportError:  # pragma: no cover - nothing to stop
        return
    try:
        Pg0(
            name=_PG0_INSTANCE,
            username=_PG0_USERNAME,
            password=_PG0_PASSWORD,
            database=_PG0_DATABASE,
        ).stop()
    except Exception as exc:  # noqa: BLE001 - shutdown must not raise
        log.warning("could not stop embedded PostgreSQL cleanly: %s", exc)


def _embedded_dsn(port: int | None) -> str:
    """Build the DSN from pg0's parts, for releases whose ``info`` omits ``uri``."""
    if not port:
        raise RuntimeError("embedded PostgreSQL did not report a port")
    return f"postgresql://{_PG0_USERNAME}:{_PG0_PASSWORD}@127.0.0.1:{port}/{_PG0_DATABASE}"


def start_embedded_server(settings: Settings | None = None) -> Any:
    """Start the embedded Hindsight server and return the running server object.

    Caller is responsible for `stop()`. Raises RuntimeError with an actionable message when
    the optional `hindsight-all` package is missing.
    """
    settings = settings or default_settings
    if not settings.groq_api_key and settings.hindsight_api_llm_provider == "groq":
        raise RuntimeError(
            "GROQ_API_KEY is required: Hindsight uses an LLM to extract memories from "
            "incident reports."
        )

    # Before the import below: everything Hindsight reads from the environment has to be in
    # place by then (see the module docstring).
    configure_embedded_env(settings)
    db_url = ensure_embedded_database()

    try:
        from hindsight import HindsightServer
    except ImportError as exc:
        raise RuntimeError(
            "The embedded Hindsight server is not installed. Either install it with "
            "`venv/Scripts/python.exe -m pip install hindsight-all`, or use Hindsight "
            "Cloud by pointing HINDSIGHT_BASE_URL at https://api.hindsight.vectorize.io."
        ) from exc

    verify_embedded_env(settings.hindsight_api_llm_groq_service_tier)

    host, port = _host_port(settings.hindsight_base_url)
    server = HindsightServer(
        db_url=db_url,
        llm_provider=settings.hindsight_api_llm_provider,
        llm_api_key=settings.groq_api_key,
        llm_model=settings.hindsight_api_llm_model,
        host=host,
        port=port,
        log_level="warning",
    )
    server.start(timeout=settings.hindsight_start_timeout)
    log.info("embedded Hindsight started at %s", server.url)
    return server


def _host_port(base_url: str) -> tuple[str, int]:
    """Parse host/port from a base URL so the server matches what clients expect."""
    from urllib.parse import urlparse

    parsed = urlparse(base_url if "//" in base_url else f"//{base_url}")
    return parsed.hostname or "127.0.0.1", parsed.port or 8888
