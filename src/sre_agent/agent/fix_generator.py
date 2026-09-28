"""Fix generation.

Produces a candidate Patch. The *source* of a patch is a first-class part of the domain
model, because it is the memory story: was this reused from a verified prior incident,
adapted from one, or generated from scratch?

Constraints are passed in as explicit text rather than hoping the model remembers:
conventions, historical context, previously failed approaches, and the findings from a
rejected review. The `do_not_repeat` list is the mechanism that stops the agent trying
the same broken fix twice.
"""

from __future__ import annotations

from ..config import Settings, settings as default_settings
from ..llm import LLMClient, LLMError
from ..logging_setup import get_logger
from ..models import AttemptSource, Incident, MemoryRef, Patch
from ..patch.builder import PatchBuildError, patch_from_payload
from ..prompts import FIX_GENERATOR_SYSTEM, FIX_SCHEMA, fix_user_prompt
from ..tools.evidence import find_test_files, read_source_files

log = get_logger("fix-generator")

_MAX_CONTEXT_FILES = 12


class FixGenerationError(RuntimeError):
    pass


class FixGenerator:
    def __init__(self, llm: LLMClient, settings: Settings | None = None) -> None:
        self.llm = llm
        self.settings = settings or default_settings

    def generate(
        self,
        incident: Incident,
        *,
        attempt_number: int,
        source: AttemptSource = AttemptSource.GENERATED_FIX,
        memory_context: str = "",
        conventions: str = "",
        do_not_repeat: str = "",
        previous_review_findings: str = "",
        strategy: str = "",
        derived_from_incident: str | None = None,
        extra_context: str = "",
    ) -> Patch:
        prompt = fix_user_prompt(
            repository=incident.repository or "unknown",
            error_class=incident.error_class.value,
            root_cause=incident.root_cause,
            evidence_summary=incident.evidence.compact(),
            failing_files=", ".join(incident.evidence.failing_tests[:10]),
            source_files=self._source_context(incident) + extra_context,
            conventions=conventions,
            memory_context=memory_context,
            do_not_repeat=do_not_repeat,
            previous_review_findings=previous_review_findings,
            strategy=strategy or _strategy_text(source),
        )

        try:
            payload, response = self.llm.complete_structured(
                [
                    {"role": "system", "content": FIX_GENERATOR_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                model=self.settings.groq_model,
                json_schema=FIX_SCHEMA,
                purpose="generate_patch",
            )
        except LLMError as exc:
            raise FixGenerationError(f"Fix generation failed: {exc}") from exc

        try:
            patch = patch_from_payload(
                payload,
                incident_id=incident.id,
                attempt_number=attempt_number,
                source=source,
                model=response.model,
                latency_ms=response.latency_ms,
                derived_from_incident=derived_from_incident,
            )
        except PatchBuildError as exc:
            raise FixGenerationError(f"Fix generation returned an unusable patch: {exc}") from exc

        if not patch.root_cause and incident.root_cause:
            patch.root_cause = incident.root_cause
        return patch

    # ── context assembly ────────────────────────────────────
    def _source_context(self, incident: Incident) -> str:
        """Give the model the files it actually needs, and no more."""
        paths: list[str] = []
        for candidate in [
            *find_test_files(incident.evidence.repo_path, incident.evidence.failing_tests),
            *(incident.classification.affected_files if incident.classification else []),
            *incident.evidence.changed_files,
        ]:
            normalized = (candidate or "").replace("\\", "/").lstrip("./")
            if normalized and normalized not in paths:
                paths.append(normalized)

        if not paths:
            log.warning("no source files identified for incident %s", incident.id)

        return read_source_files(
            incident.evidence.repo_path,
            paths[:_MAX_CONTEXT_FILES],
            max_chars=6000,
        )


def _strategy_text(source: AttemptSource) -> str:
    return {
        AttemptSource.HISTORICAL_FIX: (
            "A previously verified resolution exists for a comparable incident. Reuse its "
            "approach, adapting it to the current code. Do not apply it blindly: if the "
            "current code differs in a way that makes it wrong, say so and fix the real cause."
        ),
        AttemptSource.ADAPTED_HISTORICAL_FIX: (
            "Adapt the previously verified resolution to the current repository state. "
            "Explain what you changed relative to the historical fix and why."
        ),
        AttemptSource.SPECIALIST_FIX: (
            "Apply the class-specific repair guidance. Gather the required evidence mentally "
            "from what is provided, and fix the mechanism rather than the symptom."
        ),
        AttemptSource.GENERATED_FIX: (
            "No comparable prior incident exists. Diagnose from first principles using the "
            "evidence, the diff, and the failing tests."
        ),
    }[source]


def format_memory_context(refs: list[MemoryRef], *, limit: int = 6) -> str:
    """Render recalled incidents for the generator prompt."""
    if not refs:
        return ""
    lines: list[str] = []
    for index, ref in enumerate(refs[:limit], start=1):
        incident_id = ref.metadata.get("incident_id") or ref.document_id or f"memory-{index}"
        outcome = ref.metadata.get("outcome", "unknown")
        lines.append(f"[{index}] incident={incident_id} outcome={outcome} type={ref.kind}")
        lines.append(f"    {ref.text.strip()[:1200]}")
    return "\n".join(lines)


def format_conventions(refs: list[MemoryRef], *, limit: int = 12) -> str:
    if not refs:
        return ""
    return "\n".join(f"- {ref.text.strip()}" for ref in refs[:limit])


def collect_failed_approaches(
    incident: Incident,
    prior_failed: list[str] | None = None,
) -> str:
    """Everything the agent must not try again.

    Three sources: the prior incident's failed fixes, this incident's own failed attempts,
    and anything rejected in review. This is the negative-memory ledger.
    """
    lines: list[str] = []
    for item in prior_failed or []:
        lines.append(f"- (previous incident) {item}")
    for attempt in incident.attempts:
        if attempt.patch is None:
            continue
        if attempt.status.value in ("succeeded", "pending"):
            continue
        rationale = attempt.patch.proposed_fix or attempt.patch.summary
        if rationale:
            lines.append(f"- (attempt {attempt.number}, {attempt.status.value}) {rationale}")
        if attempt.regression and attempt.regression.new_failures:
            lines.append(
                f"  caused regressions: {', '.join(attempt.regression.new_failures[:3])}"
            )
    return "\n".join(lines)
