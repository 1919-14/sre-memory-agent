"""Hindsight-backed memory store.

This is the only module that talks to Hindsight. Everything else consumes plain
domain objects, so the memory layer can be swapped or faked in tests without touching
agent logic.

Verified against hindsight-client 0.10.1:

    Hindsight(base_url, api_key=None, timeout=300.0, max_attempts=3)
    retain(bank_id, content, timestamp: datetime|None, context, document_id,
           metadata: dict[str,str], tags: list[str], update_mode, ...)
    recall(bank_id, query, types, max_tokens, budget, tags, tags_match,
           prefer_observations, include_source_facts, ...)
    reflect(bank_id, query, budget, context, response_schema, tags, ...)
    create_bank(bank_id, name, mission, disposition_skepticism, enable_observations,
                enable_temporal_retrieval, enable_graph_retrieval, enable_reranking, ...)
    update_bank_config(bank_id, memory_defense: dict, audit_log_enabled: bool, ...)
    create_mental_model(bank_id, name, source_query, tags, id)
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..config import Settings, settings as default_settings
from ..logging_setup import get_logger
from ..models import Incident, MemoryRef, Patch, ReviewVerdict
from . import schemas

log = get_logger("memory")

RUNBOOK_QUESTION = (
    "What are the recurring failure modes in this service, which fixes have been "
    "verified to work, and which fixes have failed or caused regressions?"
)

INCIDENT_BANK_MISSION = (
    "Remember software incidents for this repository so future failures are diagnosed "
    "faster: the symptom, the suspected change, the root cause, every repair attempted "
    "with its result, the verification evidence, and the final outcome. Both successful "
    "and failed repairs matter — a failed fix is a fact worth remembering."
)

INCIDENT_REFLECT_MISSION = (
    "Act as a skeptical senior SRE. Weigh evidence, prefer fixes that were actually "
    "verified, and explicitly flag history that is stale, version-distant, or not "
    "comparable to the current failure. Memory is evidence, not truth."
)

CONVENTION_BANK_MISSION = (
    "Remember this repository's engineering conventions and the outcomes of past code "
    "reviews: which patterns were rejected and why, which fixes were accepted, and the "
    "architectural constraints that automated fixes must respect."
)

# Placeholders Hindsight serves while a mental model is still being generated.
_RUNBOOK_PLACEHOLDERS = ("generating content", "pending", "in progress", "generating")

# Substrings identifying provider rate limiting, which Hindsight reports as an HTTP 500
# with the provider's message embedded in the body.
_QUOTA_MARKERS = (
    "rate limit reached",
    "rate_limit_exceeded",
    "quota exhausted",
    "tokens per minute",
    "too many requests",
)


class MemoryStoreError(RuntimeError):
    """Any failure originating in the memory layer."""


class MemoryUnavailable(MemoryStoreError):
    """Hindsight cannot be reached or the SDK is missing."""


class MemoryStore:
    """Thin, defensive wrapper over the Hindsight client."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings
        self.incident_bank = self.settings.hindsight_bank
        self.convention_bank = self.settings.convention_bank
        self._client: Any = None
        self._executor: ThreadPoolExecutor | None = None
        self._banks_ready = False
        self._version: str = ""
        self.memory_defense_applied: bool | None = None
        self.memory_defense_note: str = "not attempted"
        # Called before a provider-throttled call sleeps: (operation, seconds, attempt).
        # The API layer uses this to tell the operator that the agent is waiting on an
        # external dependency rather than stalled, using the provider's own retry window.
        self.on_retry: Callable[[str, float, int], None] | None = None
        self._counters: dict[str, int] = {
            "retains": 0,
            "recalls": 0,
            "reflects": 0,
            "failures": 0,
        }

    # ── connection ──────────────────────────────────────────
    def _sdk_thread(self) -> ThreadPoolExecutor:
        """The one thread every SDK call runs on.

        This matters more than it looks. The SDK bridges synchronous calls to async with
        `loop.run_until_complete(...)` on the *calling thread's* event loop, and the
        httpx/anyio state inside its client binds to whichever loop touched it first.
        FastAPI runs each synchronous route handler on a different threadpool thread, so one
        shared client was being driven from several event loops in turn — which raised
        "Timeout context manager should be used inside a task" on perfectly healthy
        operations (listing memories, reading the runbook, checking readiness). Pinning the
        client to a single thread keeps a single loop for its entire life.
        """
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hindsight-sdk")
        return self._executor

    def _ensure_client(self) -> Any:
        """Build the SDK client. Only ever called on the SDK thread."""
        if self._client is None:
            try:
                from hindsight_client import Hindsight
            except ImportError as exc:  # pragma: no cover - install-time issue
                raise MemoryUnavailable(
                    "hindsight-client is not installed. Run: "
                    "venv/Scripts/python.exe -m pip install -r requirements.txt"
                ) from exc
            self._client = Hindsight(
                base_url=self.settings.hindsight_base_url,
                api_key=self.settings.hindsight_api_key or None,
                timeout=300.0,
                max_attempts=3,
            )
        return self._client

    def _invoke(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Call an SDK method on the SDK thread, re-raising its exception here."""

        def run() -> Any:
            return getattr(self._ensure_client(), method)(*args, **kwargs)

        return self._sdk_thread().submit(run).result()

    def invoke(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Call a raw SDK method on the SDK thread.

        Exposed for probes and scripts that want the unmediated SDK call while still honouring
        the single-thread rule. Application code should prefer the named methods.
        """
        return self._invoke(method, *args, **kwargs)

    @property
    def client(self) -> Any:
        """The raw SDK client, for single-threaded callers such as scripts.

        Agent and API code must use the wrapper methods instead: touching this from a request
        thread would reintroduce the cross-loop failure described in `_sdk_thread`.
        """
        return self._ensure_client()

    def health(self) -> tuple[bool, str]:
        """Return (reachable, human-readable detail). Never raises.

        Readiness is probed over plain HTTP rather than through the SDK, and the reason is
        worth recording: the SDK's methods bridge to async internally (`_run_async`), and
        FastAPI runs synchronous route handlers in a threadpool thread where that bridge
        raises ``Timeout context manager should be used inside a task``. The result was a
        perfectly healthy server being reported as unreachable on every `/api/status` call.
        A synchronous GET has no event loop to depend on, so it is correct from any thread.
        """
        base = self.settings.hindsight_base_url.rstrip("/")
        try:
            payload = self._http_json(f"{base}/version")
        except Exception as exc:  # noqa: BLE001 - report any connectivity problem
            self._version = ""
            return (
                False,
                f"Cannot reach Hindsight at {self.settings.hindsight_base_url}: "
                f"{type(exc).__name__}: {exc}",
            )
        self._version = str(payload.get("api_version") or "").strip()
        detail = f"Hindsight {self._version or 'reachable'} at {self.settings.hindsight_base_url}"
        return True, detail

    def _http_json(self, url: str, timeout: float = 5.0) -> dict[str, Any]:
        """Minimal synchronous JSON GET, authenticated when the endpoint requires it."""
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        if self.settings.hindsight_api_key:
            request.add_header("Authorization", f"Bearer {self.settings.hindsight_api_key}")
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured URL
            return json.loads(response.read().decode("utf-8"))

    @property
    def version(self) -> str:
        return self._version

    # ── bank setup ──────────────────────────────────────────
    def ensure_banks(self) -> None:
        """Create/verify both banks and apply memory policy. Idempotent."""
        if self._banks_ready:
            return
        try:
            self._ensure_incident_bank()
            self._ensure_convention_bank()
        except MemoryUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            self._counters["failures"] += 1
            raise MemoryStoreError(f"Failed to prepare Hindsight banks: {exc}") from exc
        self._banks_ready = True

    def _ensure_incident_bank(self) -> None:
        created = self._create_bank(
            bank_id=self.incident_bank,
            name="SRE Incident Memory",
            mission=INCIDENT_BANK_MISSION,
            observations_mission=(
                "Consolidate recurring failure modes for this service and the fixes that "
                "were actually verified, including fixes that failed."
            ),
            retain_mission=(
                "Extract incident facts: symptom, environment, suspected change, root "
                "cause, each repair attempted with its result, verification evidence, "
                "final outcome, and which approach must not be repeated."
            ),
            reflect_mission=INCIDENT_REFLECT_MISSION,
            skepticism=5,
            literalism=3,
        )
        if not created:
            log.info("Hindsight incident bank already exists: %s", self.incident_bank)
        self._apply_bank_policy(self.incident_bank)

    def _ensure_convention_bank(self) -> None:
        if not self.settings.convention_memory_enabled:
            return
        created = self._create_bank(
            bank_id=self.convention_bank,
            name="SRE Convention Memory",
            mission=CONVENTION_BANK_MISSION,
            observations_mission=(
                "Consolidate this repository's standing coding conventions and the review "
                "patterns that were rejected, so they can be enforced consistently."
            ),
            retain_mission=(
                "Extract durable engineering conventions, architectural constraints, and "
                "code review decisions (especially rejected approaches and the reason)."
            ),
            reflect_mission=(
                "Act as a strict but fair code reviewer for this repository. Apply the "
                "standing conventions literally and cite the convention behind each "
                "objection."
            ),
            skepticism=4,
            literalism=5,
        )
        if not created:
            log.info("Hindsight convention bank already exists: %s", self.convention_bank)

    def _create_bank(
        self,
        *,
        bank_id: str,
        name: str,
        mission: str,
        observations_mission: str,
        retain_mission: str,
        reflect_mission: str,
        skepticism: int,
        literalism: int,
    ) -> bool:
        """Return True when the bank was created, False when it already existed."""
        try:
            self._invoke(
                "create_bank",
                bank_id=bank_id,
                name=name,
                mission=mission,
                background=mission,
                disposition_skepticism=skepticism,
                disposition_literalism=literalism,
                disposition_empathy=1,
                enable_observations=True,
                observations_mission=observations_mission,
                retain_mission=retain_mission,
                reflect_mission=reflect_mission,
                enable_text_search=True,
                enable_temporal_retrieval=True,
                enable_graph_retrieval=True,
                enable_reranking=True,
            )
            log.info("Created Hindsight bank %s", bank_id)
            return True
        except Exception as exc:  # noqa: BLE001 - existence is signalled by an error
            # Most likely "bank already exists"; confirm by reading its config.
            try:
                self._invoke("get_bank_config", bank_id)
                return False
            except Exception as inner:  # noqa: BLE001
                raise MemoryStoreError(
                    f"Could not create or read bank {bank_id!r}: {exc} (verify: {inner})"
                ) from exc

    def _apply_bank_policy(self, bank_id: str) -> None:
        """Apply the security/traceability policy that matters for SRE data."""
        if not self.settings.hindsight_memory_defense:
            self.memory_defense_note = "disabled by configuration"
            self.memory_defense_applied = False
            return
        try:
            self._invoke(
                "update_bank_config",
                bank_id=bank_id,
                audit_log_enabled=True,
                memory_defense={"enabled": True, "action": "redact"},
            )
            self.memory_defense_applied = True
            self.memory_defense_note = "enabled (secret/PII redaction) + audit log"
            log.info("Memory Defense enabled on %s", bank_id)
        except Exception as exc:  # noqa: BLE001 - policy shape varies by server version
            self.memory_defense_applied = False
            self.memory_defense_note = (
                f"could not enable via client ({type(exc).__name__}); "
                "enable it in the Hindsight control plane if required"
            )
            log.warning("Memory Defense not applied on %s: %s", bank_id, exc)

    # ── provider quota handling ─────────────────────────────
    def _call(self, operation: str, method: str, **kwargs: Any) -> Any:
        """Run an SDK call on the SDK thread, waiting out provider rate limits.

        When the provider's per-minute token budget is exhausted, Hindsight returns HTTP
        500 with the provider message embedded (``Provider quota exhausted (...)``). That
        is not a defect in this code, and it must not cost the agent an incident's
        memory, so the call waits the window the provider asked for and retries.

        `method` is the SDK method *name*, so the client is resolved inside the SDK thread
        rather than on the calling one.
        """
        attempt = 0
        while True:
            try:
                return self._invoke(method, **kwargs)
            except Exception as exc:  # noqa: BLE001 - re-raised when not a quota error
                wait = self._quota_wait(exc, attempt)
                if wait is None:
                    raise
                attempt += 1
                log.warning(
                    "%s is rate limited by the LLM provider; retrying in %.0fs (retry %s/%s)",
                    operation,
                    wait,
                    attempt,
                    self.settings.memory_quota_max_retries,
                )
                if self.on_retry is not None:
                    try:
                        self.on_retry(operation, wait, attempt)
                    except Exception:  # noqa: BLE001 - reporting must not break the retry
                        log.debug("retry notifier raised", exc_info=True)
                time.sleep(wait)

    def _quota_wait(self, exc: Exception, attempt: int) -> float | None:
        """Seconds to wait before retrying, or None when this is not a quota error."""
        if attempt >= self.settings.memory_quota_max_retries:
            return None
        text = str(exc).lower()
        if not any(marker in text for marker in _QUOTA_MARKERS):
            return None
        # The provider usually says when to come back: "Please try again in 18.1s".
        match = re.search(r"try again in ([\d.]+)\s*s", text)
        wait = float(match.group(1)) + 1.0 if match else 5.0 * (2**attempt)
        return min(wait, self.settings.memory_quota_max_wait_seconds)

    # ── incident memory: write ──────────────────────────────
    def retain_incident(self, incident: Incident) -> dict[str, Any]:
        """Store the full incident trajectory. Idempotent on incident id."""
        self.ensure_banks()
        tags = schemas.incident_tags(incident)
        content = schemas.render_incident_document(incident)
        metadata = schemas.incident_metadata(incident)
        try:
            response = self._call(
                "retain incident",
                "retain",
                bank_id=self.incident_bank,
                content=content,
                context="incident postmortem: production failure, repair attempts and outcome",
                document_id=incident.id,
                timestamp=incident.created_at,
                metadata=metadata,
                tags=tags,
            )
            self._counters["retains"] += 1
            items = int(getattr(response, "items_count", 0) or 0)
            log.info(
                "retained incident %s (%s tags, %s items)",
                incident.id,
                len(tags),
                items,
            )
            return {
                "bank_id": getattr(response, "bank_id", self.incident_bank),
                "items_count": items,
                "success": bool(getattr(response, "success", True)),
                "content_chars": len(content),
                "tags": tags,
            }
        except Exception as exc:  # noqa: BLE001
            self._counters["failures"] += 1
            raise MemoryStoreError(f"retain(incident={incident.id}) failed: {exc}") from exc

    def retain_conventions(self, conventions: list[str], *, document_id: str = "conventions-core") -> dict[str, Any]:
        """Seed (or refresh) the standing conventions for this repository."""
        if not self.settings.convention_memory_enabled:
            return {"skipped": "convention memory disabled"}
        self.ensure_banks()
        body = "\n".join(f"- {line}" for line in conventions)
        content = (
            f"STANDING ENGINEERING CONVENTIONS FOR {self.settings.repo_dir.name}\n"
            "These are authoritative rules applied during automated code review.\n"
            f"{body}"
        )
        try:
            response = self._call(
                "retain conventions",
                "retain",
                bank_id=self.convention_bank,
                content=content,
                context="engineering conventions for this repository (authoritative rules)",
                document_id=document_id,
                # "unset" = timeless reference material, not a dated event
                timestamp=None,
                tags=schemas.convention_tags(),
            )
            self._counters["retains"] += 1
            log.info("retained %s conventions", len(conventions))
            return {
                "items_count": int(getattr(response, "items_count", 0) or 0),
                "conventions": len(conventions),
            }
        except Exception as exc:  # noqa: BLE001
            self._counters["failures"] += 1
            raise MemoryStoreError(f"retain(conventions) failed: {exc}") from exc

    def retain_rejected_pattern(
        self,
        incident: Incident,
        patch: Patch,
        verdict: ReviewVerdict,
    ) -> dict[str, Any]:
        """Remember a patch the reviewer refused, so the generator stops proposing it."""
        if not self.settings.convention_memory_enabled:
            return {"skipped": "convention memory disabled"}
        self.ensure_banks()
        rules = [f"[{f.severity.value}] {f.rule}: {f.message}" for f in verdict.findings]
        content = schemas.render_rejected_pattern(
            incident,
            patch_summary=patch.summary or patch.proposed_fix or "(no summary)",
            summary=verdict.summary or "(no summary)",
            rules=rules[:10],
        )
        try:
            response = self._call(
                "retain rejected pattern",
                "retain",
                bank_id=self.convention_bank,
                content=content,
                context="code review outcome: patch rejected before execution",
                document_id=f"review-{patch.id}",
                timestamp=incident.created_at,
                metadata={
                    "incident_id": incident.id,
                    "patch_id": patch.id,
                    "error_class": incident.error_class.value,
                    "max_severity": verdict.max_severity.value,
                },
                tags=schemas.rejected_pattern_tags(incident),
            )
            self._counters["retains"] += 1
            return {"items_count": int(getattr(response, "items_count", 0) or 0)}
        except Exception as exc:  # noqa: BLE001
            self._counters["failures"] += 1
            raise MemoryStoreError(f"retain(rejected pattern) failed: {exc}") from exc

    # ── incident memory: read ───────────────────────────────
    def recall_similar_incidents(
        self,
        incident: Incident,
        *,
        query: str | None = None,
        max_tokens: int | None = None,
    ) -> list[MemoryRef]:
        self.ensure_banks()
        query = query or self._build_recall_query(incident)
        tags = schemas.recall_query_tags(incident)
        try:
            response = self._call(
                "recall incidents",
                "recall",
                bank_id=self.incident_bank,
                query=query,
                types=self.settings.hindsight_recall_types,
                max_tokens=max_tokens or self.settings.hindsight_recall_max_tokens,
                budget=self.settings.hindsight_recall_budget,
                tags=tags,
                tags_match="any",
                prefer_observations=self.settings.hindsight_prefer_observations,
                include_source_facts=self.settings.hindsight_include_source_facts,
            )
            self._counters["recalls"] += 1
        except Exception as exc:  # noqa: BLE001
            self._counters["failures"] += 1
            raise MemoryStoreError(f"recall(incidents) failed: {exc}") from exc

        refs = [
            schemas.to_memory_ref(result, retrieved_for=f"incidents:{incident.error_class.value}")
            for result in (response.results or [])
        ]
        self._attach_source_facts(refs, getattr(response, "source_facts", None))
        log.info("recalled %s incident memories (tags=%s)", len(refs), tags)
        return refs

    def recall_conventions(
        self,
        incident: Incident,
        patch: Patch,
        *,
        max_tokens: int = 2000,
    ) -> list[MemoryRef]:
        """Hard rules + previously rejected approaches for this kind of change."""
        if not self.settings.convention_memory_enabled:
            return []
        self.ensure_banks()
        files = ", ".join(patch.touch_paths()) or "unspecified files"
        summary = patch.summary or patch.proposed_fix or "unspecified change"
        query = (
            f"Which repository conventions, architectural constraints, or previously "
            f"rejected approaches apply to this change in {files}? "
            f"Proposed change: {summary}. Error class: {incident.error_class.value}."
        )
        try:
            response = self._call(
                "recall conventions",
                "recall",
                bank_id=self.convention_bank,
                query=query,
                types=["world", "experience", "observation"],
                max_tokens=max_tokens,
                budget="mid",
                tags=[schemas.KIND_CONVENTION, schemas.KIND_REJECTED],
                tags_match="any",
                prefer_observations=False,
                include_source_facts=self.settings.hindsight_include_source_facts,
            )
            self._counters["recalls"] += 1
        except Exception as exc:  # noqa: BLE001
            self._counters["failures"] += 1
            raise MemoryStoreError(f"recall(conventions) failed: {exc}") from exc

        refs = [
            schemas.to_memory_ref(result, retrieved_for="conventions")
            for result in (response.results or [])
        ]
        self._attach_source_facts(refs, getattr(response, "source_facts", None))
        log.info("recalled %s convention memories", len(refs))
        return refs

    def reflect(
        self,
        query: str,
        *,
        bank_id: str | None = None,
        context: str | None = None,
        response_schema: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        budget: str = "mid",
    ) -> tuple[str, dict[str, Any] | None]:
        """Reason across memories. Returns (text, structured_output)."""
        self.ensure_banks()
        try:
            response = self._call(
                "reflect",
                "reflect",
                bank_id=bank_id or self.incident_bank,
                query=query,
                budget=budget,
                context=context,
                response_schema=response_schema,
                tags=tags,
                tags_match="any",
                include_facts=True,
            )
            self._counters["reflects"] += 1
        except Exception as exc:  # noqa: BLE001
            self._counters["failures"] += 1
            raise MemoryStoreError(f"reflect failed: {exc}") from exc
        structured = getattr(response, "structured_output", None)
        return str(getattr(response, "text", "") or ""), structured

    # ── runbook (mental model) ──────────────────────────────
    def ensure_runbook(self, mental_model_id: str = "service-runbook") -> str | None:
        """Create the runbook mental model if absent; return its id when available."""
        self.ensure_banks()
        try:
            self._invoke(
                "create_mental_model",
                bank_id=self.incident_bank,
                name="Service Runbook",
                source_query=RUNBOOK_QUESTION,
                id=mental_model_id,
                tags=[f"service:{self.settings.repo_dir.name}"],
            )
            log.info("created runbook mental model %s", mental_model_id)
            return mental_model_id
        except Exception as exc:  # noqa: BLE001 - already exists is the common case
            try:
                self._invoke("get_mental_model", self.incident_bank, mental_model_id)
                return mental_model_id
            except Exception:  # noqa: BLE001
                log.warning("runbook mental model unavailable: %s", exc)
                return None

    def read_runbook(self, mental_model_id: str = "service-runbook") -> str:
        """Read the standing runbook. A plain read — no retrieval, no LLM call.

        Hindsight generates mental models in the background and serves a placeholder while
        it works. Returning that placeholder as content would put the literal string
        "Generating content..." in front of a user and write it to the runbook file, so an
        unfinished model reads as an empty runbook instead.
        """
        try:
            model = self._invoke(
                "get_mental_model",
                self.incident_bank,
                mental_model_id,
                detail="content",
            )
        except Exception as exc:  # noqa: BLE001
            # "No runbook yet" is a normal state on a fresh bank, not a failure.
            text = str(exc)
            if "404" in text or "not found" in text.lower():
                log.info("no runbook mental model yet (%s)", mental_model_id)
                return ""
            raise MemoryStoreError(f"read runbook failed: {exc}") from exc

        if isinstance(model, dict):
            candidates = [model.get(key) for key in ("content", "text", "answer")]
        else:
            candidates = [getattr(model, key, None) for key in ("content", "text", "answer")]
        for value in candidates:
            if not value:
                continue
            text = str(value).strip()
            if text.lower().startswith(_RUNBOOK_PLACEHOLDERS):
                log.info("runbook mental model is still generating in Hindsight")
                return ""
            return text
        return ""

    def refresh_runbook(self, mental_model_id: str = "service-runbook") -> None:
        try:
            self._invoke("refresh_mental_model", self.incident_bank, mental_model_id)
        except Exception as exc:  # noqa: BLE001
            raise MemoryStoreError(f"refresh runbook failed: {exc}") from exc

    def write_runbook_to_disk(self, content: str, filename: str = "runbook.md") -> str:
        """Project the runbook onto disk so it is a real file the agent maintains."""
        target = self.settings.runbook_dir_path
        target.mkdir(parents=True, exist_ok=True)
        path = target / filename
        header = (
            f"# Service Runbook — {self.settings.repo_dir.name}\n\n"
            "_Maintained automatically by the SRE Memory Agent from its Hindsight "
            "mental model. Do not edit by hand._\n\n"
        )
        path.write_text(header + (content or "_No consolidated knowledge yet._"), encoding="utf-8")
        return str(path)

    # ── introspection ───────────────────────────────────────
    def list_memories(
        self,
        bank_id: str | None = None,
        *,
        memory_type: str | None = None,
        search_query: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRef]:
        try:
            response = self._invoke(
                "list_memories",
                bank_id=bank_id or self.incident_bank,
                type=memory_type,
                search_query=search_query,
                limit=limit,
            )
        except Exception as exc:  # noqa: BLE001
            raise MemoryStoreError(f"list_memories failed: {exc}") from exc
        items = getattr(response, "memories", None) or getattr(response, "items", None) or []
        return [schemas.to_memory_ref(item, retrieved_for="browse") for item in items]

    def counters(self) -> dict[str, int]:
        return dict(self._counters)

    def status(self) -> dict[str, Any]:
        reachable, detail = self.health()
        return {
            "reachable": reachable,
            "detail": detail,
            "version": self._version,
            "incident_bank": self.incident_bank,
            "convention_bank": self.convention_bank,
            "memory_defense": self.memory_defense_note,
            "counters": self.counters(),
        }

    def close(self) -> None:
        """Close the client on its own thread, then stop that thread."""
        if self._client is not None:
            try:
                self._sdk_thread().submit(self._client.close).result(timeout=10)
            except Exception:  # noqa: BLE001 - best effort
                pass
            self._client = None
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None

    # ── internals ───────────────────────────────────────────
    def _build_recall_query(self, incident: Incident) -> str:
        """Keep under the 500-token query cap: symptom + change, never the whole trace."""
        parts = [
            f"{incident.error_class.value} failure",
            incident.error[:400],
        ]
        if incident.evidence.changed_files:
            parts.append(f"changed files: {', '.join(incident.evidence.changed_files[:8])}")
        if incident.evidence.diff_summary:
            parts.append(incident.evidence.diff_summary[:800])
        if incident.evidence.failing_tests:
            parts.append(f"failing tests: {', '.join(incident.evidence.failing_tests[:5])}")
        return "\n".join(part for part in parts if part)

    @staticmethod
    def _attach_source_facts(refs: list[MemoryRef], source_facts: Any) -> None:
        if not source_facts:
            return
        lookup: dict[str, Any] = {}
        if isinstance(source_facts, dict):
            lookup = source_facts
        for ref in refs:
            for fact_id in ref.source_fact_ids:
                fact = lookup.get(fact_id)
                if fact is not None:
                    ref.source_facts.append(
                        schemas.to_memory_ref(fact, retrieved_for="source-fact")
                    )
