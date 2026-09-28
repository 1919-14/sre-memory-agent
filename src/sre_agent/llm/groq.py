"""Live LLM client for Groq's OpenAI-compatible chat completions API.

Design notes that matter in practice:

* Groq's free tier rate-limits aggressively, so retries use exponential backoff and
  honour `Retry-After`.
* Small models intermittently emit malformed JSON. Instead of failing the incident we
  make one focused "repair" call that shows the model its own invalid output.
* The agent must never hang on stage, so every request has a hard timeout.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import httpx

from .base import LLMBudget, LLMClient, LLMError, LLMResponse, Message, extract_json

log = logging.getLogger("sre_agent.llm.groq")

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

SYSTEM_JSON_HINT = (
    "Respond with a single valid JSON object and nothing else. "
    "No markdown fences, no commentary before or after."
)


class GroqLLM(LLMClient):
    """OpenAI-compatible client pointed at Groq."""

    simulated = False

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        fast_model: str | None = None,
        temperature: float = 0.1,
        max_retries: int = 3,
        timeout: float = 90.0,
        json_mode: bool = True,
        budget: LLMBudget | None = None,
        fallback_model: str = "",
    ) -> None:
        super().__init__(budget)
        if not api_key:
            raise LLMError("GROQ_API_KEY is not set; cannot create a live LLM client")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.fast_model = fast_model or model
        # Model availability differs per account and per plan. A configured model that
        # this account cannot access must not take the agent offline mid-demo, so we
        # retry once on a known-good model and report the substitution loudly.
        self.fallback_model = fallback_model
        self.substitutions: list[str] = []
        self.temperature = temperature
        self.max_retries = max(1, max_retries)
        self.timeout = timeout
        self.json_mode = json_mode
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=15.0),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "sre-memory-agent/0.1",
            },
        )

    # ── public API ──────────────────────────────────────────
    def complete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        purpose: str = "",
    ) -> LLMResponse:
        self.budget.check()
        model = model or self.model
        temperature = self.temperature if temperature is None else temperature
        wants_json = json_schema is not None or self.json_mode

        payload_messages = list(messages)
        if json_schema is not None:
            payload_messages = _inject_schema(payload_messages, json_schema)

        started = time.perf_counter()
        try:
            response = self._request(
                model=model,
                messages=payload_messages,
                temperature=temperature,
                json_mode=json_schema is not None,
                purpose=purpose,
            )
        except LLMError as exc:
            if not _is_model_unavailable(exc) or not self.fallback_model or model == self.fallback_model:
                raise
            note = (
                f"Model {model!r} is not available on this account; retried with "
                f"{self.fallback_model!r}. Update GROQ_MODEL in .env to silence this."
            )
            log.warning(note)
            if note not in self.substitutions:
                self.substitutions.append(note)
            model = self.fallback_model
            response = self._request(
                model=model,
                messages=payload_messages,
                temperature=temperature,
                json_mode=json_schema is not None,
                purpose=purpose,
            )

        text = _first_choice_text(response)
        usage = response.get("usage") or {}
        structured = extract_json(text) if wants_json else None

        # Repair pass: the model returned prose or broken JSON when JSON was required.
        if json_schema is not None and structured is None:
            log.warning("Malformed JSON for purpose=%s; attempting repair", purpose)
            text, structured, repair_usage = self._repair(
                model=model,
                messages=payload_messages,
                bad_output=text,
                json_schema=json_schema,
                purpose=purpose,
            )
            usage = {
                "prompt_tokens": int(usage.get("prompt_tokens", 0))
                + repair_usage.get("prompt_tokens", 0),
                "completion_tokens": int(usage.get("completion_tokens", 0))
                + repair_usage.get("completion_tokens", 0),
            }

        result = LLMResponse(
            text=text,
            structured=structured,
            model=model,
            purpose=purpose,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        self.budget.record(result)
        log.info(
            "llm purpose=%s model=%s tokens=%s latency=%sms",
            purpose,
            model,
            result.total_tokens,
            result.latency_ms,
        )
        return result

    def close(self) -> None:
        self._client.close()

    # ── internals ───────────────────────────────────────────
    def _request(
        self,
        *,
        model: str,
        messages: list[Message],
        temperature: float,
        json_mode: bool,
        purpose: str,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._client.post(f"{self.base_url}/chat/completions", json=body)
                if resp.status_code >= 400:
                    if resp.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                        delay = _backoff_delay(attempt, resp.headers.get("retry-after"))
                        log.warning(
                            "Groq %s for purpose=%s; retry %s/%s in %.1fs",
                            resp.status_code,
                            purpose,
                            attempt,
                            self.max_retries,
                            delay,
                        )
                        time.sleep(delay)
                        continue
                    raise LLMError(
                        f"Groq API error {resp.status_code} (purpose={purpose}): "
                        f"{_truncate(resp.text)}"
                    )
                return resp.json()
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    delay = _backoff_delay(attempt, None)
                    log.warning("Groq timeout for purpose=%s; retry in %.1fs", purpose, delay)
                    time.sleep(delay)
                    continue
                raise LLMError(f"Groq request timed out after {self.timeout}s ({purpose})") from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(_backoff_delay(attempt, None))
                    continue
                raise LLMError(f"Groq transport error ({purpose}): {exc}") from exc

        raise LLMError(f"Groq request failed after {self.max_retries} attempts ({purpose}): {last_error}")

    def _repair(
        self,
        *,
        model: str,
        messages: list[Message],
        bad_output: str,
        json_schema: dict[str, Any],
        purpose: str,
    ) -> tuple[str, dict[str, Any] | None, dict[str, int]]:
        import json as _json

        repair_messages = [
            *messages,
            {"role": "assistant", "content": _truncate(bad_output, 2000)},
            {
                "role": "user",
                "content": (
                    "That response was not valid JSON. Reply with ONLY a JSON object matching "
                    f"this schema, with no markdown fences and no extra text:\n"
                    f"{_json.dumps(json_schema)}"
                ),
            },
        ]
        try:
            response = self._request(
                model=model,
                messages=repair_messages,
                temperature=0.0,
                json_mode=True,
                purpose=f"{purpose}:repair",
            )
        except LLMError as exc:
            log.warning("JSON repair call failed (%s)", exc)
            return bad_output, None, {}

        text = _first_choice_text(response)
        usage = response.get("usage") or {}
        tokens = {
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
        }
        structured = extract_json(text)
        if structured is None:
            log.error("JSON repair produced invalid output for purpose=%s", purpose)
        return text, structured, tokens


# ── helpers ─────────────────────────────────────────────────


def _inject_schema(messages: list[Message], json_schema: dict[str, Any]) -> list[Message]:
    """Append the required output schema as a system instruction."""
    import json as _json

    instruction = (
        f"{SYSTEM_JSON_HINT}\n\nRequired output schema (JSON Schema):\n"
        f"{_json.dumps(json_schema, indent=2)}"
    )
    out = list(messages)
    if out and out[0].get("role") == "system":
        out[0] = {
            "role": "system",
            "content": f"{out[0]['content']}\n\n{instruction}",
        }
    else:
        out.insert(0, {"role": "system", "content": instruction})
    return out


def _first_choice_text(response: dict[str, Any]) -> str:
    try:
        choices = response.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content")
        if content is None:
            # Some models return reasoning_content instead
            content = message.get("reasoning_content") or ""
        return str(content)
    except (AttributeError, IndexError, TypeError):
        return ""


def _is_model_unavailable(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "model_not_found" in message
        or "does not exist or you do not have access" in message
        or "no access to model" in message
    )


def _backoff_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(30.0, max(0.5, float(retry_after)))
        except (TypeError, ValueError):
            pass
    return min(20.0, (2 ** (attempt - 1)) * 1.5) + random.uniform(0, 0.5)


def _truncate(text: str, limit: int = 600) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"
