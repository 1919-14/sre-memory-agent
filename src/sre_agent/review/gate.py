"""The review gate.

Runs between patch generation and sandbox execution. A blocked patch never executes,
which is both a safety property (nothing untrusted runs) and a token saver (no wasted
sandbox cycle).

Decision precedence:

    any CRITICAL finding        -> reject   (the approach itself is wrong)
    any finding >= block level  -> revise   (retry generation with the findings)
    else                        -> approve
"""

from __future__ import annotations

from ..config import Settings, settings as default_settings
from ..llm import LLMClient
from ..logging_setup import get_logger
from ..models import (
    Incident,
    MemoryRef,
    Patch,
    ReviewDecision,
    ReviewFinding,
    ReviewerKind,
    ReviewVerdict,
    Severity,
)
from .conventions import ConventionsReviewer
from .policy import PolicyReviewer

log = get_logger("review-gate")

_SEVERITY_BY_NAME = {
    "info": Severity.INFO,
    "low": Severity.LOW,
    "medium": Severity.MEDIUM,
    "high": Severity.HIGH,
    "critical": Severity.CRITICAL,
}


class ReviewGate:
    def __init__(self, llm: LLMClient, settings: Settings | None = None) -> None:
        self.llm = llm
        self.settings = settings or default_settings
        self.policy = PolicyReviewer(self.settings)
        self.conventions = ConventionsReviewer(llm, self.settings)
        self.block_threshold = _SEVERITY_BY_NAME.get(
            self.settings.review_block_severity.lower(), Severity.HIGH
        )

    def review(
        self,
        incident: Incident,
        patch: Patch,
        *,
        convention_refs: list[MemoryRef] | None = None,
        rejected_refs: list[MemoryRef] | None = None,
        blast_radius: list[str] | None = None,
        cycles: int = 0,
    ) -> ReviewVerdict:
        if not self.settings.code_review_enabled:
            return ReviewVerdict(
                decision=ReviewDecision.APPROVE,
                summary="Code review gate disabled by configuration.",
                reviewers_run=[],
                cycles=cycles,
            )

        findings: list[ReviewFinding] = []
        summaries: list[str] = []
        reviewers: list[ReviewerKind] = []
        convention_decision: ReviewDecision | None = None

        # 1. Deterministic policy — always runs, cannot be talked out of a rule.
        if self.settings.policy_review_enabled:
            policy_findings, policy_summary = self.policy.review(
                incident, patch, blast_radius=blast_radius
            )
            findings.extend(policy_findings)
            summaries.append(policy_summary)
            reviewers.append(ReviewerKind.POLICY)

        # 2. Conventions + previously rejected patterns, both recalled from Hindsight.
        if self.settings.conventions_review_enabled and self.llm is not None:
            convention_findings, convention_summary, convention_decision = self.conventions.review(
                incident,
                patch,
                conventions=convention_refs or [],
                rejected_patterns=rejected_refs or [],
            )
            if convention_findings or convention_decision is not None:
                findings.extend(convention_findings)
                summaries.append(convention_summary)
                reviewers.append(ReviewerKind.CONVENTIONS)

        decision = self._decide(findings, convention_decision)
        verdict = ReviewVerdict(
            decision=decision,
            summary=" ".join(summaries).strip() or "No review performed.",
            findings=findings,
            reviewers_run=reviewers,
            cycles=cycles,
        )
        log.info(
            "review gate: %s (max severity %s, %s finding(s), reviewers=%s)",
            decision.value,
            verdict.max_severity.value,
            len(findings),
            [r.value for r in reviewers],
        )
        return verdict

    # ── decision logic ──────────────────────────────────────
    def _decide(
        self,
        findings: list[ReviewFinding],
        convention_decision: ReviewDecision | None,
    ) -> ReviewDecision:
        blocking = [f for f in findings if f.severity.rank >= self.block_threshold.rank]
        critical = [f for f in findings if f.severity is Severity.CRITICAL]

        if critical:
            return ReviewDecision.REJECT
        if blocking:
            return ReviewDecision.REVISE
        if convention_decision is ReviewDecision.REJECT:
            return ReviewDecision.REJECT
        if convention_decision is ReviewDecision.REVISE and findings:
            return ReviewDecision.REVISE
        return ReviewDecision.APPROVE

    # ── helper for the fix generator ────────────────────────
    @staticmethod
    def findings_as_instructions(verdict: ReviewVerdict, limit: int = 8) -> str:
        """Render blocking findings as a constraint list for the next attempt."""
        relevant = [f for f in verdict.findings if f.severity.rank >= Severity.MEDIUM.rank]
        if not relevant:
            relevant = verdict.findings
        lines = [
            f"- [{f.severity.value}] {f.rule}: {f.message}"
            + (f" (file: {f.file})" if f.file else "")
            for f in relevant[:limit]
        ]
        return "\n".join(lines)
