"""Embedded Hindsight server support.

Running Hindsight locally with no Docker is convenient for a demo, but a free Groq plan
exposes two sharp edges that are worth documenting because they cost real debugging time:

1. **`service_tier`.** Hindsight defaults to `service_tier="auto"`, and Groq rejects that
   with HTTP 400 on plans that do not include it:
   ``"`service_tier` `auto` is not available for this org"``.
   The global knob (`HINDSIGHT_API_LLM_GROQ_SERVICE_TIER`) covers some calls, but fact
   *extraction*, *reflect* and *consolidation* build their own provider configuration, so
   each task needs its own `extra_body` override. Both are set here.

2. **Tokens per minute.** Hindsight's extraction and consolidation passes are token-heavy.
   Groq's free tier allows 8,000 TPM per model, which a handful of retains will exhaust
   (HTTP 429). For a demo with many incidents, prefer Hindsight Cloud or a paid tier —
   see `HINDSIGHT.md`.
"""

from __future__ import annotations

import json
import os
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


def configure_embedded_env(settings: Settings | None = None) -> dict[str, str]:
    """Set the environment Hindsight needs *before* the server reads its config.

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

        # Per-task overrides: the global tier is not honoured by every code path.
        body = json.dumps({"service_tier": tier})
        for var in _TASK_EXTRA_BODY_VARS:
            os.environ.setdefault(var, body)
            applied[var] = body

    log.info("configured embedded Hindsight env: %s", ", ".join(applied) or "no overrides")
    return applied


def start_embedded_server(settings: Settings | None = None) -> Any:
    """Start the embedded Hindsight server and return the running server object.

    Caller is responsible for `stop()`. Raises RuntimeError with an actionable message when
    the optional `hindsight-all` package is missing.
    """
    settings = settings or default_settings
    try:
        from hindsight import HindsightServer
    except ImportError as exc:
        raise RuntimeError(
            "The embedded Hindsight server is not installed. Either install it with "
            "`venv/Scripts/python.exe -m pip install hindsight-all`, or use Hindsight "
            "Cloud by pointing HINDSIGHT_BASE_URL at https://api.hindsight.vectorize.io."
        ) from exc

    if not settings.groq_api_key and settings.hindsight_api_llm_provider == "groq":
        raise RuntimeError(
            "GROQ_API_KEY is required: Hindsight uses an LLM to extract memories from "
            "incident reports."
        )

    configure_embedded_env(settings)
    host, port = _host_port(settings.hindsight_base_url)
    server = HindsightServer(
        db_url="pg0",
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
