"""Comparability judge.

Answers one question: *may this recalled incident inform the current one?*

The default answer is no. Recalled memory is evidence, not truth, and the most
convincing failure mode of a memory agent is confidently reusing a fix that resolved a
different mechanism with the same symptom. So a deterministic pre-filter runs first, and
the LLM is only asked about candidates that survive it.
"""

from __future__ import annotations

from ..config import Settings, settings as default_settings
from ..llm import LLMClient, LLMError
from ..logging_setup import get_logger
from ..memory.schemas import derive_component
from ..models import ComparabilityCheck, Incident, MemoryRef
from ..prompts import COMPARABILITY_SCHEMA, COMPARABILITY_SYSTEM, comparability_user_prompt

log = get_logger("comparability")

# A candidate must share at least this much with the current incident to be considered.
_MIN_KEYWORD_OVERLAP = 1


class ComparabilityJudge:
    def __init__(self, llm: LLMClient, settings: Settings | None = None) -> None:
        self.llm = llm
        self.settings = settings or default_settings

    # ── public API ──────────────────────────────────────────
    def judge(self, incident: Incident, refs: list[MemoryRef]) -> ComparabilityCheck:
        if not refs:
            return ComparabilityCheck(
                comparable=False,
                confidence=1.0,
                reason="No prior incident memory was recalled for this failure.",
                source="heuristic",
            )

        candidates = self._prefilter(incident, refs)
        if not candidates:
            return ComparabilityCheck(
                comparable=False,
                confidence=0.8,
                reason=(
                    f"{len(refs)} memory item(s) were recalled, but none matched the current "
                    "class, component, or changed files."
                ),
                rejected_because=["no-candidate-passed-deterministic-prefilter"],
                source="heuristic",
            )

        try:
            return self._judge_with_llm(incident, candidates, total_recalled=len(refs))
        except LLMError as exc:
            log.warning("comparability LLM unavailable (%s); using deterministic fallback", exc)
            return self._heuristic(incident, candidates, reason=f"LLM unavailable ({exc})")
        except Exception as exc:  # noqa: BLE001
            log.warning("comparability judgement failed (%s); using deterministic fallback", exc)
            return self._heuristic(incident, candidates, reason=f"fallback ({exc})")

    # ── deterministic layers ────────────────────────────────
    def _prefilter(self, incident: Incident, refs: list[MemoryRef]) -> list[MemoryRef]:
        """Keep only memories that plausibly relate to this failure."""
        component = derive_component(incident)
        suspected = {f.replace("\\", "/") for f in incident.evidence.changed_files}
        error_class = incident.error_class.value

        kept: list[MemoryRef] = []
        for ref in refs:
            tags = set(ref.tags or [])
            same_class = f"error-class:{error_class}" in tags
            same_component = component != "unknown" and f"component:{component}" in tags
            text = (ref.text or "").lower()
            file_overlap = any(f.split("/")[-1].lower() in text for f in suspected if f)

            hits = sum([same_class, same_component, file_overlap])
            if hits >= _MIN_KEYWORD_OVERLAP or ref.kind == "observation":
                kept.append(ref)
        if kept:
            return kept[:8]
        # Nothing matched structurally — an observation may still carry the pattern.
        return [ref for ref in refs if ref.kind == "observation"][:3]

    def _heuristic(
        self, incident: Incident, candidates: list[MemoryRef], *, reason: str
    ) -> ComparabilityCheck:
        """Structural fallback: comparable only on class + component agreement."""
        component = derive_component(incident)
        error_class = incident.error_class.value
        best: MemoryRef | None = None
        for ref in candidates:
            tags = set(ref.tags or [])
            if f"error-class:{error_class}" in tags and f"component:{component}" in tags:
                best = ref
                break
        if best is None:
            return ComparabilityCheck(
                comparable=False,
                confidence=0.6,
                reason=f"{reason}. No candidate shared both error class and component.",
                rejected_because=["class-or-component-mismatch"],
                source="heuristic",
            )
        return ComparabilityCheck(
            comparable=True,
            confidence=0.5,
            reason=(
                f"{reason}. A prior incident shares the error class and component; "
                "treat it as a hypothesis to validate, not a decision."
            ),
            prior_incident_id=best.metadata.get("incident_id") or best.document_id,
            prior_outcome=best.metadata.get("outcome"),
            prior_resolution=best.text[:400],
            matched_on=["error-class", "component"],
            source="heuristic",
        )

    # ── LLM layer ───────────────────────────────────────────
    def _judge_with_llm(
        self,
        incident: Incident,
        candidates: list[MemoryRef],
        *,
        total_recalled: int,
    ) -> ComparabilityCheck:
        memories_text = "\n\n".join(
            f"[memory {i}] type={ref.kind} tags={ref.tags} outcome={ref.metadata.get('outcome', '?')}\n{ref.text}"
            for i, ref in enumerate(candidates, start=1)
        )
        payload = self.llm.complete_json(
            [
                {"role": "system", "content": COMPARABILITY_SYSTEM},
                {
                    "role": "user",
                    "content": comparability_user_prompt(
                        current_summary=incident.evidence.compact(),
                        error_class=incident.error_class.value,
                        recalled_memories=memories_text,
                    ),
                },
            ],
            model=self.settings.groq_model,
            json_schema=COMPARABILITY_SCHEMA,
            purpose="comparability",
        )

        check = ComparabilityCheck(
            comparable=bool(payload.get("comparable")),
            confidence=_confidence(payload.get("confidence")),
            reason=str(payload.get("reason") or "").strip(),
            prior_incident_id=payload.get("prior_incident_id") or None,
            prior_resolution=payload.get("prior_resolution") or None,
            prior_failed_fixes=[str(x) for x in (payload.get("prior_failed_fixes") or [])],
            matched_on=[str(x) for x in (payload.get("matched_on") or [])],
            rejected_because=[str(x) for x in (payload.get("rejected_because") or [])],
            source="llm",
        )
        if check.prior_incident_id:
            check.prior_outcome = _outcome_for(check.prior_incident_id, candidates)
        log.info(
            "comparability: comparable=%s confidence=%.2f (%s of %s recalled memories considered)",
            check.comparable,
            check.confidence,
            len(candidates),
            total_recalled,
        )
        return check


def _outcome_for(incident_id: str, candidates: list[MemoryRef]) -> str | None:
    for ref in candidates:
        if (ref.metadata.get("incident_id") or ref.document_id) == incident_id:
            return ref.metadata.get("outcome")
    return None


def _confidence(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
