"""Conventions reviewer.

The reason this exists as a separate stage: memory changes behaviour here too. The
reviewer checks the patch against standing conventions AND against approaches that were
previously rejected, both recalled from Hindsight. Without the memory lookup this would
just be a generic lint pass.
"""

from __future__ import annotations

from ..config import Settings, settings as default_settings
from ..llm import LLMClient, LLMError
from ..logging_setup import get_logger
from ..models import (
    Incident,
    MemoryRef,
    Patch,
    ReviewDecision,
    ReviewFinding,
    ReviewerKind,
    Severity,
)
from ..prompts import REVIEW_SCHEMA, REVIEW_SYSTEM, review_user_prompt

log = get_logger("review-conventions")


class ConventionsReviewer:
    def __init__(self, llm: LLMClient, settings: Settings | None = None) -> None:
        self.llm = llm
        self.settings = settings or default_settings

    def format_memories(self, refs: list[MemoryRef]) -> str:
        if not refs:
            return ""
        lines: list[str] = []
        for index, ref in enumerate(refs, start=1):
            header = f"[{index}] ({ref.kind or 'memory'}"
            if ref.document_id:
                header += f", doc={ref.document_id}"
            header += ")"
            lines.append(f"{header} {ref.text}")
            if ref.metadata.get("incident_id"):
                lines.append(f"    source incident: {ref.metadata['incident_id']}")
        return "\n".join(lines)

    def review(
        self,
        incident: Incident,
        patch: Patch,
        *,
        conventions: list[MemoryRef],
        rejected_patterns: list[MemoryRef],
    ) -> tuple[list[ReviewFinding], str, ReviewDecision | None]:
        conventions_text = self.format_memories(conventions)
        rejected_text = self.format_memories(rejected_patterns)

        if not conventions_text and not rejected_text:
            log.info("conventions review skipped: no convention memory available")
            return [], "No convention memory was available to review against.", None

        prompt = review_user_prompt(
            repository=incident.repository or "unknown",
            error_class=incident.error_class.value,
            root_cause=patch.root_cause,
            proposed_fix=patch.proposed_fix,
            patch_summary=patch.summary,
            diff=patch.diff,
            conventions=conventions_text,
            rejected_patterns=rejected_text,
        )
        try:
            payload = self.llm.complete_json(
                [
                    {"role": "system", "content": REVIEW_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                model=self.settings.review_model,
                json_schema=REVIEW_SCHEMA,
                purpose="review_patch",
            )
        except LLMError as exc:
            log.warning("conventions review unavailable: %s", exc)
            return [], f"Conventions review could not run: {exc}", None

        findings = self._parse_findings(payload, conventions + rejected_patterns)
        decision = _coerce_decision(payload.get("decision"))
        summary = str(payload.get("summary") or "").strip() or "Conventions review completed."
        log.info("conventions review: %s — %s finding(s)", decision.value, len(findings))
        return findings, summary, decision

    # ── parsing ─────────────────────────────────────────────
    def _parse_findings(self, payload: dict, memories: list[MemoryRef]) -> list[ReviewFinding]:
        raw = payload.get("findings")
        if not isinstance(raw, list):
            return []
        findings: list[ReviewFinding] = []
        for entry in raw[:10]:
            if not isinstance(entry, dict):
                continue
            rule = str(entry.get("rule") or "convention").strip()
            message = str(entry.get("message") or "").strip()
            if not message:
                continue
            memory_ref, memory_text = self._cite(rule, message, memories)
            findings.append(
                ReviewFinding(
                    severity=_coerce_severity(entry.get("severity")),
                    rule=rule,
                    message=message,
                    file=(str(entry["file"]) if entry.get("file") else None),
                    line=(int(entry["line"]) if isinstance(entry.get("line"), int) else None),
                    reviewer=ReviewerKind.CONVENTIONS,
                    memory_ref=memory_ref,
                    memory_text=memory_text,
                )
            )
        return findings

    @staticmethod
    def _cite(rule: str, message: str, memories: list[MemoryRef]) -> tuple[str | None, str | None]:
        """Attach the recalled memory a finding appears to be based on.

        Deliberately a conservative textual match: we would rather show no citation than
        attribute a finding to the wrong memory.
        """
        haystack = f"{rule} {message}".lower()
        best: tuple[str | None, str | None] = (None, None)
        for ref in memories:
            text = (ref.text or "").lower()
            if not text:
                continue
            words = [w for w in text.split() if len(w) > 4][:12]
            overlap = sum(1 for word in words if word in haystack)
            if overlap >= 3 or text[:40] in haystack:
                best = (ref.memory_id, ref.text)
                break
        return best


def _coerce_decision(value: object) -> ReviewDecision:
    try:
        return ReviewDecision(str(value).strip().lower())
    except ValueError:
        return ReviewDecision.REVISE


def _coerce_severity(value: object) -> Severity:
    try:
        return Severity(str(value).strip().lower())
    except ValueError:
        return Severity.MEDIUM
