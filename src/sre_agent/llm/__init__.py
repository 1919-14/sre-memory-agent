"""LLM package: one factory, two clients."""

from __future__ import annotations

from ..config import settings
from ..logging_setup import get_logger
from .base import (
    LLMBudget,
    LLMBudgetExceeded,
    LLMClient,
    LLMError,
    LLMResponse,
    Message,
    ScriptedLLM,
    extract_json,
)
from .groq import GroqLLM

log = get_logger("llm")

__all__ = [
    "GroqLLM",
    "LLMBudget",
    "LLMBudgetExceeded",
    "LLMClient",
    "LLMError",
    "LLMResponse",
    "Message",
    "ScriptedLLM",
    "build_llm",
    "extract_json",
]


def build_llm(
    *,
    budget: LLMBudget | None = None,
    scripted_handlers: dict | None = None,
    force_scripted: bool = False,
) -> LLMClient:
    """Return the appropriate client for the current run mode.

    Offline/replay mode returns a ScriptedLLM, which raises on unknown purposes rather
    than fabricating output.
    """
    budget = budget or LLMBudget(max_calls=settings.max_llm_calls_per_incident)
    if force_scripted or settings.offline or not settings.groq_api_key:
        if not settings.offline and not settings.groq_api_key:
            log.warning(
                "GROQ_API_KEY is not set — falling back to the scripted LLM. "
                "Replay/offline results are clearly marked as simulated."
            )
        return ScriptedLLM(scripted_handlers, budget=budget)
    return GroqLLM(
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        model=settings.groq_model,
        fast_model=settings.groq_model_fast,
        temperature=settings.llm_temperature,
        max_retries=settings.llm_max_retries,
        timeout=settings.llm_timeout_seconds,
        json_mode=settings.llm_json_mode,
        budget=budget,
        fallback_model=settings.groq_model_fallback,
    )
