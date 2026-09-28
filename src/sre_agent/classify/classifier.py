"""Failure classifier.

Two paths, in order:

1. A deterministic keyword scan produces a prior. This always runs, so classification
   still works with no API key and in replay mode.
2. If the LLM is available, it makes the authoritative call and must justify itself.

If the LLM fails (rate limit, malformed output, budget), we fall back to the heuristic
prior and mark `source="heuristic"` — the UI shows that, so a degraded classification is
never presented as a model decision.
"""

from __future__ import annotations

from ..config import Settings, settings as default_settings
from ..llm import LLMClient, LLMError
from ..logging_setup import get_logger
from ..models import Classification, ErrorClass, Fixability, Incident
from ..prompts import CLASSIFICATION_SCHEMA, CLASSIFIER_SYSTEM, classification_user_prompt
from . import taxonomy

log = get_logger("classifier")


class Classifier:
    def __init__(self, llm: LLMClient, settings: Settings | None = None) -> None:
        self.llm = llm
        self.settings = settings or default_settings

    # ── public API ──────────────────────────────────────────
    def classify(self, incident: Incident) -> Classification:
        if not self.settings.classifier_enabled:
            return self._heuristic(incident, reason="classifier disabled by configuration")

        prior = self._prior(incident)
        try:
            return self._classify_with_llm(incident, prior)
        except LLMError as exc:
            log.warning("LLM classification failed (%s); using heuristic prior", exc)
            return self._heuristic(
                incident,
                reason=f"heuristic fallback: LLM classification unavailable ({exc})",
            )
        except Exception as exc:  # noqa: BLE001 - classification must never crash a run
            log.warning("Unexpected classifier error (%s); using heuristic prior", exc)
            return self._heuristic(incident, reason=f"heuristic fallback: {exc}")

    # ── LLM path ────────────────────────────────────────────
    def _classify_with_llm(
        self, incident: Incident, prior: list[str]
    ) -> Classification:
        prompt = classification_user_prompt(
            repository=incident.repository or "unknown",
            evidence_summary=incident.evidence.compact(),
            allowed_classes=taxonomy.class_names(),
            heuristic_prior=prior,
        )
        payload = self.llm.complete_json(
            [
                {"role": "system", "content": CLASSIFIER_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            model=self.settings.classification_model,
            json_schema=CLASSIFICATION_SCHEMA,
            purpose="classify",
        )

        error_class = _coerce_class(payload.get("error_class"))
        confidence = _coerce_confidence(payload.get("confidence"))
        affected = [str(p) for p in (payload.get("affected_files") or [])][:20]
        reasoning = str(payload.get("reasoning") or "").strip()

        result = Classification(
            error_class=error_class,
            confidence=confidence,
            reasoning=reasoning,
            affected_files=affected or list(incident.evidence.changed_files),
            likely_fixability=_coerce_fixability(payload.get("likely_fixability")),
            evidence_required=[str(e) for e in (payload.get("evidence_required") or [])],
            model=self.settings.classification_model,
            source="llm",
        )
        return self._finalize(result)

    # ── heuristic path ──────────────────────────────────────
    def _heuristic(self, incident: Incident, *, reason: str) -> Classification:
        hits = self._prior(incident)
        scored = taxonomy.score_text(self._haystack(incident))
        if scored:
            error_class, count = scored[0]
            confidence = min(0.75, 0.4 + 0.1 * count)
        elif hits:
            error_class = ErrorClass(hits[0])
            confidence = 0.4
        else:
            error_class, confidence = ErrorClass.UNKNOWN, 0.2

        return self._finalize(
            Classification(
                error_class=error_class,
                confidence=confidence,
                reasoning=f"{reason}. Deterministic keyword signals: "
                f"{', '.join(hits) if hits else 'none matched'}.",
                affected_files=list(incident.evidence.changed_files),
                evidence_required=list(taxonomy.spec_for(error_class).evidence_required),
                source="heuristic",
                model="heuristic",
            )
        )

    # ── shared post-processing ──────────────────────────────
    def _finalize(self, classification: Classification) -> Classification:
        """Resolve fixability, attach the specialist, and enforce the escalate rules."""
        spec = taxonomy.spec_for(classification.error_class)

        if classification.error_class.value in self.settings.escalate_classes:
            classification.likely_fixability = Fixability.ESCALATE
        elif classification.likely_fixability is Fixability.UNKNOWN:
            classification.likely_fixability = taxonomy.default_fixability(
                classification.error_class
            )

        # A specialist is only attached when it is enabled in configuration.
        if spec.specialist and classification.error_class.value in self.settings.specialist_classes:
            classification.specialist = spec.specialist
        else:
            classification.specialist = None

        if not classification.evidence_required:
            classification.evidence_required = list(spec.evidence_required)

        # Low confidence means we cannot safely patch what we do not understand.
        if (
            classification.confidence < self.settings.classifier_min_confidence
            and classification.likely_fixability is Fixability.CODE_FIXABLE
        ):
            log.info(
                "classification confidence %.2f below threshold %.2f -> escalate",
                classification.confidence,
                self.settings.classifier_min_confidence,
            )
            classification.likely_fixability = Fixability.ESCALATE

        return classification

    # ── helpers ─────────────────────────────────────────────
    @staticmethod
    def _haystack(incident: Incident) -> str:
        return " ".join(
            [
                incident.error or "",
                incident.evidence.error_message or "",
                incident.evidence.stack_trace or "",
                incident.evidence.logs or "",
                incident.evidence.diff_summary or "",
                " ".join(incident.evidence.changed_files),
            ]
        )

    def _prior(self, incident: Incident) -> list[str]:
        return [cls.value for cls, _signal in taxonomy.heuristic_signals(self._haystack(incident))]


def _coerce_class(value: object) -> ErrorClass:
    if isinstance(value, ErrorClass):
        return value
    try:
        return ErrorClass(str(value).strip().lower())
    except ValueError:
        return ErrorClass.UNKNOWN


def _coerce_confidence(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _coerce_fixability(value: object) -> Fixability:
    if isinstance(value, Fixability):
        return value
    try:
        return Fixability(str(value).strip().lower())
    except ValueError:
        return Fixability.UNKNOWN
