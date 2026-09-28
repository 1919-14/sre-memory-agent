"""LLM client interface, call budget, and JSON parsing helpers.

The agent talks to an `LLMClient`. Two implementations exist:

* `GroqLLM`     — live, OpenAI-compatible HTTP calls to Groq
* `ScriptedLLM` — deterministic canned answers for tests and replay

`ScriptedLLM` never invents an answer: if no handler is registered it raises, so a
replay can never silently present fabricated reasoning as a real LLM result.
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Callable

from pydantic import BaseModel, Field

Message = dict[str, str]


class LLMError(RuntimeError):
    """Raised when the LLM cannot produce a usable response."""


class LLMBudgetExceeded(LLMError):
    """Raised when an incident exceeds its LLM call budget."""


class LLMResponse(BaseModel):
    text: str = ""
    structured: dict[str, Any] | None = None
    model: str = ""
    purpose: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    repaired: bool = False
    simulated: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMBudget(BaseModel):
    """Per-incident call/token ceiling so a runaway loop cannot burn the demo."""

    max_calls: int = 60
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    max_tokens: int = 0  # 0 = unlimited
    log: list[dict[str, Any]] = Field(default_factory=list)

    def check(self) -> None:
        if self.max_calls and self.calls >= self.max_calls:
            raise LLMBudgetExceeded(
                f"LLM call budget exhausted ({self.calls}/{self.max_calls} calls this incident)"
            )

    def record(self, response: LLMResponse) -> None:
        self.calls += 1
        self.prompt_tokens += response.prompt_tokens
        self.completion_tokens += response.completion_tokens
        self.log.append(
            {
                "purpose": response.purpose,
                "model": response.model,
                "calls": self.calls,
                "tokens": response.total_tokens,
                "simulated": response.simulated,
            }
        )

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMClient(ABC):
    """Minimal surface the agent depends on."""

    simulated: bool = False

    def __init__(self, budget: LLMBudget | None = None) -> None:
        self.budget = budget or LLMBudget()

    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        purpose: str = "",
    ) -> LLMResponse:
        """Return a completion. Implementations must never raise on empty output."""

    def complete_structured(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        purpose: str = "",
    ) -> tuple[dict[str, Any], LLMResponse]:
        """Complete and require a JSON object back, keeping the response metadata.

        Callers that need to record which model ran (and how long it took) use this;
        callers that only want the data use `complete_json`.
        """
        response = self.complete(
            messages,
            model=model,
            json_schema=json_schema,
            temperature=temperature,
            purpose=purpose,
        )
        if response.structured is not None:
            return response.structured, response
        parsed = extract_json(response.text)
        if parsed is None:
            raise LLMError(
                f"LLM returned non-JSON output for purpose={purpose!r}: {response.text[:400]}"
            )
        return parsed, response

    def complete_json(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        purpose: str = "",
    ) -> dict[str, Any]:
        """Complete and return only the JSON object."""
        data, _response = self.complete_structured(
            messages,
            model=model,
            json_schema=json_schema,
            temperature=temperature,
            purpose=purpose,
        )
        return data

    # ── introspection ───────────────────────────────────────
    @property
    def calls(self) -> int:
        return self.budget.calls

    @property
    def tokens(self) -> int:
        return self.budget.total_tokens


class ScriptedLLM(LLMClient):
    """Deterministic LLM for tests and replay mode.

    Handlers are keyed by `purpose` (e.g. "classify", "generate_patch"). A handler is
    either a static payload or a callable receiving the messages.
    """

    simulated = True

    def __init__(
        self,
        handlers: dict[str, Any] | None = None,
        *,
        budget: LLMBudget | None = None,
        model: str = "scripted",
    ) -> None:
        super().__init__(budget)
        self._handlers: dict[str, Any] = dict(handlers or {})
        self._model = model
        self.unhandled: list[str] = []

    def register(self, purpose: str, handler: Any) -> None:
        self._handlers[purpose] = handler

    def has(self, purpose: str) -> bool:
        return purpose in self._handlers

    def complete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        purpose: str = "",
    ) -> LLMResponse:
        started = time.perf_counter()
        self.budget.check()
        if purpose not in self._handlers:
            self.unhandled.append(purpose)
            raise LLMError(
                f"ScriptedLLM has no handler for purpose={purpose!r}. "
                "Offline/replay mode refuses to fabricate LLM output."
            )
        handler = self._handlers[purpose]
        payload = handler(messages) if callable(handler) else handler

        structured: dict[str, Any] | None = None
        text = ""
        if isinstance(payload, dict):
            structured = payload
            text = json.dumps(payload)
        else:
            text = str(payload)
            if json_schema is not None or _looks_like_json(text):
                structured = extract_json(text)

        response = LLMResponse(
            text=text,
            structured=structured,
            model=model or self._model,
            purpose=purpose,
            latency_ms=int((time.perf_counter() - started) * 1000),
            simulated=True,
        )
        self.budget.record(response)
        return response


# ── JSON extraction ─────────────────────────────────────────

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _looks_like_json(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("{") or stripped.startswith("[")


def extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON object extraction from an LLM response.

    Handles code fences, leading prose, and trailing commentary. Returns None when no
    parseable object exists — callers decide whether that is fatal.
    """
    if not text:
        return None

    candidates: list[str] = []
    stripped = text.strip()
    candidates.append(stripped)

    for match in _FENCE_RE.findall(text):
        candidates.append(match.strip())

    # Widest balanced-brace slice
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
    return None


def json_loads_or_none(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


Handler = Callable[[list[Message]], Any]
