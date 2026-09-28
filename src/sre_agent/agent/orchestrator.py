"""The agent orchestrator.

Runs the complete loop for one incident:

    evidence -> classify -> recall -> comparability -> [generate -> validate -> review
    -> sandbox -> verify -> regress] -> recover | escalate | roll back -> retain

Design rules that keep this honest:

* **Memory is evidence.** A recalled fix is a hypothesis. The comparability judge decides
  whether it may be reused, and a refusal is recorded and shown.
* **Review before execution.** A blocked patch never runs, so nothing untrusted executes
  and no sandbox cycle is wasted.
* **A repair attempt is a sandbox execution.** Review revisions and validation rejections
  are recorded in the ledger but do not consume the repair budget.
* **Every terminal state writes memory** — including rollback and escalation.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone

from ..classify import Classifier
from ..config import Settings, settings as default_settings
from ..llm import LLMBudgetExceeded, LLMClient, build_llm
from ..logging_setup import get_logger
from ..memory import MemoryStore, MemoryStoreError
from ..models import (
    Attempt,
    AttemptSource,
    AttemptStatus,
    Classification,
    ErrorClass,
    Evidence,
    EventStatus,
    ExecutionEvent,
    Fixability,
    Incident,
    IncidentStatus,
    MemoryRef,
    Outcome,
    Patch,
    ReviewDecision,
    RunMode,
    Stage,
)
from ..patch.validator import PatchValidator
from ..review import ReviewGate
from ..sandbox import SandboxExecutor
from ..tools.evidence import EvidenceCollector
from ..tools.git_tools import GitRepo
from ..tools.regression import RegressionChecker
from ..tools.rollback import RollbackManager
from .comparability import ComparabilityJudge
from .fix_generator import (
    FixGenerationError,
    FixGenerator,
    collect_failed_approaches,
    format_conventions,
    format_memory_context,
)

log = get_logger("agent")

EventSink = Callable[[ExecutionEvent], None]


class SREAgent:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        llm: LLMClient | None = None,
        memory: MemoryStore | None = None,
        event_sink: EventSink | None = None,
        skill_sink: Callable[[Incident], None] | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self.llm = llm or build_llm()
        self.memory = memory
        self.event_sink = event_sink
        self.skill_sink = skill_sink

        self.repo = GitRepo(self.settings.repo_dir)
        self.classifier = Classifier(self.llm, self.settings)
        self.fix_generator = FixGenerator(self.llm, self.settings)
        self.review_gate = ReviewGate(self.llm, self.settings)
        self.validator = PatchValidator(self.settings)
        self.sandbox = SandboxExecutor(self.settings)
        self.rollback = RollbackManager(self.repo, self.settings)
        self.regression = RegressionChecker(
            max_new_failures=self.settings.regression_max_new_failures,
            flake_reruns=self.settings.regression_flake_reruns,
            check_blast_radius=self.settings.regression_blast_radius_check,
        )
        self.warnings: list[str] = list(self.sandbox.warnings)
        # Wall-clock start of each in-flight stage, keyed by (incident id, stage). A stage
        # opening with RUNNING and closing with any other status gets a measured
        # `duration_ms` attached, so the interface can show how long a step really took
        # instead of estimating it.
        self._stage_clock: dict[tuple[str, str], float] = {}

    # ── setup ───────────────────────────────────────────────
    def prepare(self) -> list[str]:
        """Verify dependencies once per process. Returns human-readable warnings."""
        warnings: list[str] = list(self.warnings)

        if not self.repo.is_repo():
            warnings.append(f"{self.settings.repo_dir} is not a git repository")

        if self.memory is not None:
            reachable, detail = self.memory.health()
            if not reachable:
                warnings.append(f"Hindsight unavailable: {detail}")
            else:
                try:
                    self.memory.ensure_banks()
                except MemoryStoreError as exc:
                    warnings.append(f"Hindsight bank setup failed: {exc}")
        return warnings

    # ── main entry point ────────────────────────────────────
    def run_incident(self, incident: Incident, *, collect_evidence: bool = True) -> Incident:
        started = time.perf_counter()
        incident.repo_path = str(self.settings.repo_dir)
        if not incident.repository:
            incident.repository = self.settings.repo_dir.name
        if not incident.branch and self.repo.is_repo():
            incident.branch = self.repo.current_branch()
        if not incident.commit_sha and self.repo.is_repo():
            incident.commit_sha = self.repo.current_commit()

        self._event(
            incident,
            Stage.DETECTED,
            f"Incident detected in {incident.repository} via {incident.trigger}",
            status=EventStatus.OK,
            trigger=incident.trigger,
            commit=incident.commit_sha[:8],
        )

        try:
            # ── 1. gather evidence ──────────────────────────
            incident.status = IncidentStatus.ANALYZING
            self._event(
                incident,
                Stage.DETECTED,
                "Collecting evidence: failing tests, commit diff and environment",
                status=EventStatus.RUNNING,
                phase="evidence",
            )
            if collect_evidence and not incident.evidence.test_report:
                incident.evidence = self._collect_evidence(incident)
            self._event(
                incident,
                Stage.DETECTED,
                f"Collected evidence: {len(incident.evidence.failing_tests)} failing test(s), "
                f"{len(incident.evidence.changed_files)} changed file(s)",
                status=EventStatus.OK,
                error=incident.evidence.error_message[:300],
                changed_files=incident.evidence.changed_files[:10],
            )

            # ── 2. classify ─────────────────────────────────
            self._event(
                incident,
                Stage.CLASSIFIED,
                "Classifying the failure against the error taxonomy",
                status=EventStatus.RUNNING,
            )
            incident.classification = self.classifier.classify(incident)
            incident.status = IncidentStatus.CLASSIFIED
            classification = incident.classification
            self._event(
                incident,
                Stage.CLASSIFIED,
                f"Classified as {classification.error_class.value} "
                f"(confidence {classification.confidence:.2f}, source {classification.source})",
                status=EventStatus.OK,
                error_class=classification.error_class.value,
                confidence=classification.confidence,
                fixability=classification.likely_fixability.value,
                specialist=classification.specialist,
                reasoning=classification.reasoning,
            )

            # ── 3. escalate when code cannot fix it ─────────
            if classification.likely_fixability is Fixability.ESCALATE:
                return self._escalate(incident, classification, started)

            # ── 4. recall memory ────────────────────────────
            self._recall(incident)

            # ── 5. attempt repairs ──────────────────────────
            if self._repair_loop(incident):
                return self._finalize_recovered(incident, started)

            # ── 6. recovery failed ──────────────────────────
            return self._finalize_failed(incident, started)

        except LLMBudgetExceeded as exc:
            incident.warn(str(exc))
            self._event(
                incident, Stage.ESCALATED, f"Aborted: {exc}", status=EventStatus.FAILED
            )
            incident.status = IncidentStatus.ESCALATED
            incident.outcome = Outcome.ABORTED
            incident.escalation_reason = f"Safety stop: {exc}"
            incident.resolved_at = datetime.now(timezone.utc)
            self._retain(incident, "aborted")
            return incident
        except Exception as exc:  # noqa: BLE001 - never lose an incident to a crash
            log.exception("incident run failed")
            incident.warn(f"Agent error: {type(exc).__name__}: {exc}")
            incident.status = IncidentStatus.FAILED
            incident.outcome = Outcome.ABORTED
            incident.escalation_reason = f"Agent error: {exc}"
            incident.resolved_at = datetime.now(timezone.utc)
            incident.touch()
            incident.metrics.duration_s = time.perf_counter() - started
            self._event(
                incident,
                Stage.ESCALATED,
                f"Agent error, incident preserved: {exc}",
                status=EventStatus.FAILED,
            )
            self._retain(incident, "error")
            return incident

    # ── 1. evidence ─────────────────────────────────────────
    def _collect_evidence(self, incident: Incident) -> Evidence:
        collector = EvidenceCollector(self.repo)
        return collector.collect(
            source=incident.trigger,
            previous_good=incident.previous_good_commit,
            error_override=incident.error,
        )

    # ── 4. memory recall ────────────────────────────────────
    def _recall(self, incident: Incident) -> None:
        incident.status = IncidentStatus.RECALLING_MEMORY
        self._event(
            incident,
            Stage.RECALLING,
            "Searching Hindsight for comparable past incidents",
            status=EventStatus.RUNNING,
            query_tags=[
                f"service:{incident.repository}",
                f"error-class:{incident.error_class.value}",
            ],
        )
        if self.memory is None:
            incident.warn("Memory layer not configured; running without historical context")
            self._event(
                incident,
                Stage.RECALLING,
                "No memory layer configured — proceeding without historical context",
                status=EventStatus.WARN,
            )
            return

        try:
            refs = self.memory.recall_similar_incidents(incident)
        except MemoryStoreError as exc:
            incident.warn(f"Hindsight recall failed: {exc}")
            self._event(
                incident, Stage.RECALLING, f"Recall failed: {exc}", status=EventStatus.FAILED
            )
            return

        incident.memory_refs = refs
        incident.metrics.memories_recalled = len(refs)
        self._event(
            incident,
            Stage.RECALLING,
            f"Recalled {len(refs)} relevant memory item(s) from Hindsight",
            status=EventStatus.OK,
            query_tags=[
                f"service:{incident.repository}",
                f"error-class:{incident.error_class.value}",
            ],
            memories=[
                {
                    "id": r.memory_id,
                    "kind": r.kind,
                    "relevance": round(r.relevance, 4),
                    "text": r.text[:400],
                    "document_id": r.document_id,
                    "metadata": r.metadata,
                    "tags": r.tags,
                }
                for r in refs[:12]
            ],
        )

        # Comparability: memory is evidence, not truth.
        self._event(
            incident,
            Stage.COMPARABILITY,
            "Judging whether the recalled memory applies to this failure",
            status=EventStatus.RUNNING,
            recalled=len(refs),
        )
        judge = ComparabilityJudge(self.llm, self.settings)
        check = judge.judge(incident, refs)
        incident.comparability = check
        if check.comparable:
            self._event(
                incident,
                Stage.COMPARABILITY,
                f"Comparable prior incident found: {check.prior_incident_id or 'prior record'}"
                f" (confidence {check.confidence:.2f})",
                status=EventStatus.OK,
                comparable=True,
                reason=check.reason,
                matched_on=check.matched_on,
                prior_resolution=(check.prior_resolution or "")[:600],
            )
        else:
            incident.rejected_memories = refs
            self._event(
                incident,
                Stage.COMPARABILITY,
                "Recalled memory is NOT applicable — generating a fresh fix",
                status=EventStatus.WARN,
                comparable=False,
                reason=check.reason,
                rejected_because=check.rejected_because,
            )
        for ref in refs:
            ref.influence = (
                "compared against the current failure; judged not comparable"
                if not check.comparable
                else "supplied the prior resolution to adapt"
            )

    # ── 5. repair loop ──────────────────────────────────────
    def _repair_loop(self, incident: Incident) -> bool:
        """Try to repair the incident. Returns True when repaired and verified."""
        executions = 0
        proposals = 0
        consecutive_blocks = 0
        max_proposals = self.settings.max_repair_attempts * (
            self.settings.max_review_cycles + 1
        ) + 1
        review_findings = ""

        while (
            executions < self.settings.max_repair_attempts and proposals < max_proposals
        ):
            proposals += 1
            attempt = Attempt(
                number=len(incident.attempts) + 1,
                strategy=self._strategy_label(incident),
            )
            incident.attempts.append(attempt)

            # ── propose ─────────────────────────────────────
            incident.status = IncidentStatus.GENERATING_FIX
            self._event(
                incident,
                Stage.GENERATING,
                f"Attempt {attempt.number}: generating and validating a candidate repair",
                status=EventStatus.RUNNING,
                attempt=attempt.number,
                reuse_prior=bool(incident.comparability and incident.comparability.comparable),
            )
            try:
                patch, source, derived_from = self._propose(incident, attempt, review_findings)
            except FixGenerationError as exc:
                attempt.status = AttemptStatus.SANDBOX_ERROR
                attempt.error = str(exc)
                attempt.finished_at = datetime.now(timezone.utc)
                self._event(
                    incident,
                    Stage.GENERATING,
                    f"Attempt {attempt.number}: could not generate a patch ({exc})",
                    status=EventStatus.FAILED,
                )
                continue

            attempt.patch = patch
            attempt.source = source
            self._event(
                incident,
                Stage.GENERATING,
                f"Attempt {attempt.number}: proposed fix via {source.value} — {patch.summary or patch.proposed_fix[:120]}",
                status=EventStatus.OK,
                attempt=attempt.number,
                patch_id=patch.id,
                source=source.value,
                files=patch.touch_paths(),
                root_cause=patch.root_cause[:400],
                derived_from=derived_from,
            )

            # ── validate (deterministic, before anything executes) ──
            validation = self.validator.validate(patch, self.settings.repo_dir)
            attempt.validation = validation
            if not validation.ok:
                attempt.status = AttemptStatus.REJECTED_BY_VALIDATION
                attempt.error = "; ".join(validation.errors)
                attempt.finished_at = datetime.now(timezone.utc)
                self._event(
                    incident,
                    Stage.GENERATING,
                    f"Attempt {attempt.number} rejected by patch validation: {attempt.error}",
                    status=EventStatus.FAILED,
                    attempt=attempt.number,
                    errors=validation.errors,
                    warnings=validation.warnings,
                )
                continue

            # ── review gate (before any execution) ──────────
            incident.status = IncidentStatus.REVIEWING
            self._event(
                incident,
                Stage.REVIEW,
                f"Attempt {attempt.number}: running the review gate before anything executes",
                status=EventStatus.RUNNING,
                attempt=attempt.number,
            )
            verdict, convention_refs, rejected_refs = self._review(incident, patch, attempt)
            attempt.review = verdict
            self._event(
                incident,
                Stage.REVIEW,
                f"Attempt {attempt.number} review: {verdict.decision.value.upper()} — {verdict.summary}",
                attempt=attempt.number,
                status=(
                    EventStatus.OK
                    if verdict.approved
                    else EventStatus.WARN
                    if verdict.decision is ReviewDecision.REVISE
                    else EventStatus.FAILED
                ),
                patch_id=patch.id,
                decision=verdict.decision.value,
                max_severity=verdict.max_severity.value,
                reviewers=[r.value for r in verdict.reviewers_run],
                findings=[
                    {
                        "severity": f.severity.value,
                        "rule": f.rule,
                        "message": f.message,
                        "file": f.file,
                        "reviewer": f.reviewer.value,
                        "memory_text": (f.memory_text or "")[:300] or None,
                    }
                    for f in verdict.findings[:15]
                ],
            )

            if not verdict.approved:
                consecutive_blocks += 1
                attempt.status = AttemptStatus.BLOCKED_BY_REVIEW
                attempt.error = verdict.summary
                attempt.explanation = "Patch never executed; blocked at the review gate."
                attempt.finished_at = datetime.now(timezone.utc)

                if verdict.decision is ReviewDecision.REJECT:
                    self._retain_rejected(incident, patch, verdict)
                    review_findings = ""
                    consecutive_blocks = 0
                    continue

                review_findings = ReviewGate.findings_as_instructions(verdict)
                if consecutive_blocks > self.settings.max_review_cycles:
                    self._event(
                        incident,
                        Stage.REVIEW,
                        f"Attempt {attempt.number}: review cycles exhausted, changing approach",
                        status=EventStatus.WARN,
                    )
                    self._retain_rejected(incident, patch, verdict)
                    review_findings = ""
                    consecutive_blocks = 0
                incident.metrics.memories_rejected += 1 if rejected_refs else 0
                continue

            review_findings = ""
            consecutive_blocks = 0

            # ── sandbox: reproduce -> apply -> verify -> regress ──
            executions += 1
            incident.status = IncidentStatus.SANDBOX_TESTING
            self._event(
                incident,
                Stage.SANDBOX,
                f"Attempt {attempt.number}: reproducing the failure, then testing the "
                "patched repository in isolation",
                status=EventStatus.RUNNING,
                attempt=attempt.number,
                backend=self.sandbox.backend.name,
                isolated=self.sandbox.backend.name == "docker",
            )
            sandbox = self.sandbox.execute(incident, patch, keep_workspace=False)
            attempt.sandbox = sandbox
            self._event(
                incident,
                Stage.SANDBOX,
                self._sandbox_message(attempt.number, sandbox),
                status=self._sandbox_status(sandbox),
                backend=sandbox.backend,
                isolated=sandbox.isolated,
                error_reproduced=sandbox.error_reproduced,
                patch_applied=sandbox.patch_applied,
                verify=(sandbox.test_report.summary_line() if sandbox.test_report else None),
                full=(sandbox.full_report.summary_line() if sandbox.full_report else None),
                duration_s=round(sandbox.duration_s, 2),
                error=sandbox.error,
            )
            if sandbox.error:
                attempt.status = AttemptStatus.SANDBOX_ERROR
                attempt.error = sandbox.error
                attempt.finished_at = datetime.now(timezone.utc)
                continue

            # ── verification + regression comparison ────────
            # One computation answers both questions — is the original failure gone, and did
            # anything else break — so both steps announce that they are running before it and
            # report their own result after it. Neither is announced as finished early.
            incident.status = IncidentStatus.VERIFYING
            self._event(
                incident,
                Stage.VERIFY,
                f"Attempt {attempt.number}: verifying the original failure is resolved",
                status=EventStatus.RUNNING,
                attempt=attempt.number,
            )
            self._event(
                incident,
                Stage.REGRESSION,
                f"Attempt {attempt.number}: comparing the full suite against the last known-good "
                "baseline",
                status=EventStatus.RUNNING,
                attempt=attempt.number,
            )
            regression = self._check_regression(incident, patch, sandbox)
            attempt.regression = regression
            self._event(
                incident,
                Stage.VERIFY,
                self._verification_message(attempt.number, sandbox, regression),
                status=(
                    EventStatus.OK if regression.original_error_resolved else EventStatus.FAILED
                ),
                attempt=attempt.number,
                original_error_resolved=regression.original_error_resolved,
                reproduce=(
                    sandbox.reproduce_report.summary_line() if sandbox.reproduce_report else None
                ),
                verify=(sandbox.test_report.summary_line() if sandbox.test_report else None),
                full=(sandbox.full_report.summary_line() if sandbox.full_report else None),
            )
            self._event(
                incident,
                Stage.REGRESSION,
                self._regression_message(attempt.number, regression),
                status=EventStatus.OK if regression.acceptable else EventStatus.FAILED,
                original_error_resolved=regression.original_error_resolved,
                new_failures=regression.new_failures,
                flaky=regression.flaky,
                blast_radius=regression.blast_radius,
                notes=regression.notes,
            )

            if regression.acceptable and sandbox.test_report is not None and sandbox.test_report.green:
                attempt.status = AttemptStatus.SUCCEEDED
                attempt.finished_at = datetime.now(timezone.utc)
                incident.root_cause = patch.root_cause or incident.root_cause
                incident.final_resolution = patch.proposed_fix or patch.summary
                incident.verification = (
                    f"Original failure resolved; {sandbox.test_report.summary_line()}; "
                    f"{regression.notes}"
                )
                if executions == 1:
                    incident.metrics.first_attempt_success = True
                return True

            attempt.status = (
                AttemptStatus.REGRESSION_FAILED
                if regression.original_error_resolved
                else AttemptStatus.VERIFICATION_FAILED
            )
            attempt.error = regression.notes
            attempt.finished_at = datetime.now(timezone.utc)
            incident.metrics.regression_rate += 1 if regression.new_failures else 0

        return False

    # ── proposal strategy ───────────────────────────────────
    def _propose(
        self, incident: Incident, attempt: Attempt, review_findings: str
    ) -> tuple[Patch, AttemptSource, str | None]:
        check = incident.comparability
        reuse = bool(check and check.comparable and check.confidence >= 0.5)
        is_first = attempt.number == 1

        source = AttemptSource.GENERATED_FIX
        memory_context = ""
        derived_from: str | None = None

        if reuse and is_first and check is not None:
            source = (
                AttemptSource.HISTORICAL_FIX
                if check.confidence >= 0.7
                else AttemptSource.ADAPTED_HISTORICAL_FIX
            )
            derived_from = check.prior_incident_id
            memory_context = format_memory_context(incident.memory_refs)
        elif attempt.number > 1:
            # Later attempts have seen their own failures; the ledger is the context.
            source = AttemptSource.GENERATED_FIX

        if incident.classification and incident.classification.specialist and attempt.number == 1:
            source = AttemptSource.SPECIALIST_FIX if not reuse else source

        prior_failed = list(check.prior_failed_fixes) if check else []
        do_not_repeat = collect_failed_approaches(incident, prior_failed)

        strategy_extra = ""
        if attempt.number > 1 and incident.attempts:
            previous = [a for a in incident.attempts if a.number < attempt.number and a.patch]
            if previous:
                last = previous[-1]
                strategy_extra = (
                    f"The previous attempt ({last.status.value}) did not resolve the incident.\n"
                    f"Previous approach: {(last.patch.proposed_fix or '')[:400]}\n"
                    f"Outcome detail: {(last.error or '')[:400]}\n"
                    "Choose a DIFFERENT mechanism for this attempt."
                )

        patch = self.fix_generator.generate(
            incident,
            attempt_number=attempt.number,
            source=source,
            memory_context=memory_context,
            conventions="",
            do_not_repeat=do_not_repeat,
            previous_review_findings=review_findings,
            strategy=strategy_extra or "",
            derived_from_incident=derived_from,
        )
        return patch, source, derived_from

    # ── review ──────────────────────────────────────────────
    def _review(
        self, incident: Incident, patch: Patch, attempt: Attempt
    ) -> tuple[object, list[MemoryRef], list[MemoryRef]]:
        conventions: list[MemoryRef] = []
        rejected: list[MemoryRef] = []
        if self.memory is not None and self.settings.convention_memory_enabled:
            try:
                refs = self.memory.recall_conventions(incident, patch)
                conventions = [r for r in refs if "kind:convention" in (r.tags or [])]
                rejected = [r for r in refs if "kind:rejected-pattern" in (r.tags or [])]
                incident.convention_refs = conventions
                if rejected:
                    incident.metrics.memories_rejected += len(rejected)
            except MemoryStoreError as exc:
                incident.warn(f"Convention memory recall failed: {exc}")

        blast = []
        try:
            from ..tools.regression import blast_radius

            blast = blast_radius(
                self.settings.repo_dir, patch.touch_paths()
            ) if self.settings.regression_blast_radius_check else []
        except Exception:  # noqa: BLE001 - advisory only
            blast = []

        verdict = self.review_gate.review(
            incident,
            patch,
            convention_refs=conventions,
            rejected_refs=rejected,
            blast_radius=blast,
            cycles=attempt.number - 1,
        )
        return verdict, conventions, rejected

    # ── regression ──────────────────────────────────────────
    def _check_regression(self, incident: Incident, patch: Patch, sandbox) -> object:
        baseline = self._baseline_report(incident)
        return self.regression.compare(
            baseline=baseline,
            after=sandbox.full_report or sandbox.test_report,
            original_failing=incident.evidence.failing_tests,
            repo_path=self.settings.repo_dir,
            changed_files=patch.touch_paths(),
            rerun=(
                (lambda nodeids: self._rerun(incident, patch, nodeids))
                if self.settings.regression_flake_reruns > 0
                else None
            ),
        )

    def _baseline_report(self, incident: Incident):
        """The full-suite report from the last known-good state.

        Captured on demand by checking out the baseline commit in a throwaway workspace,
        so "new failure" has a real definition rather than being assumed.
        """
        cached = getattr(self, "_baseline_cache", None)
        if cached is not None:
            return cached
        try:
            collector = EvidenceCollector(self.repo)
            reference = collector.repo
            good = incident.previous_good_commit or reference.last_known_good()
            if not good:
                return None
            from ..tools.test_runner import run_pytest
            import shutil
            import subprocess
            import tempfile
            from pathlib import Path

            with tempfile.TemporaryDirectory(prefix="sre-baseline-") as tmp:
                target = Path(tmp) / "baseline"
                subprocess.run(
                    ["git", "clone", "--quiet", "--no-hardlinks", str(self.settings.repo_dir), str(target)],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
                subprocess.run(
                    ["git", "-C", str(target), "checkout", "--quiet", good],
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
                shutil.rmtree(target / ".git", ignore_errors=True)
                report = run_pytest(target, suite_label="baseline")
            self._baseline_cache = report
            log.info("captured baseline: %s", report.summary_line())
            return report
        except Exception as exc:  # noqa: BLE001 - fall back to the incident's own view
            log.warning("could not capture a baseline report: %s", exc)
            return None

    def _rerun(self, incident: Incident, patch: Patch, nodeids: list[str]):
        result = self.sandbox.execute(
            incident, patch, reproduce_tests=nodeids, full_suite=False, keep_workspace=False
        )
        from ..models import TestReport

        return result.test_report or TestReport(suite_label="rerun", exit_code=1)

    # ── terminal states ─────────────────────────────────────
    def _escalate(
        self, incident: Incident, classification: Classification, started: float
    ) -> Incident:
        incident.status = IncidentStatus.ESCALATED
        incident.outcome = Outcome.ESCALATED
        incident.escalation_reason = (
            f"Classified as {classification.error_class.value}, which code cannot fix "
            f"(fixability={classification.likely_fixability.value}). "
            f"Reasoning: {classification.reasoning}"
        )
        incident.final_resolution = "Escalated to a human operator; no code change attempted."
        incident.verification = "Not applicable — no patch was proposed."
        incident.resolved_at = datetime.now(timezone.utc)
        incident.touch()
        incident.metrics.duration_s = time.perf_counter() - started
        self._event(
            incident,
            Stage.ESCALATED,
            "Escalating to a human: this failure is not code-fixable. No patch was attempted.",
            status=EventStatus.WARN,
            error_class=classification.error_class.value,
            reason=incident.escalation_reason,
        )
        self._retain(incident, "escalation")
        return incident

    def _finalize_recovered(self, incident: Incident, started: float) -> Incident:
        incident.status = IncidentStatus.RECOVERED
        incident.outcome = Outcome.RECOVERED
        incident.resolved_at = datetime.now(timezone.utc)
        incident.touch()
        incident.metrics.duration_s = time.perf_counter() - started
        incident.metrics.attempts_used = sum(
            1 for a in incident.attempts if a.sandbox is not None
        )
        incident.metrics.memories_reused = sum(
            1
            for a in incident.attempts
            if a.source in (AttemptSource.HISTORICAL_FIX, AttemptSource.ADAPTED_HISTORICAL_FIX)
        )
        self._event(
            incident,
            Stage.RESOLVED,
            f"Recovered in {incident.metrics.attempts_used} repair attempt(s) "
            f"({incident.metrics.duration_s:.1f}s)",
            status=EventStatus.OK,
            root_cause=incident.root_cause[:400],
            resolution=incident.final_resolution[:400],
            verification=incident.verification[:400],
        )
        self._retain(incident, "recovery")
        return incident

    def _finalize_failed(self, incident: Incident, started: float) -> Incident:
        incident.status = IncidentStatus.ROLLBACK_REQUIRED
        incident.escalation_reason = (
            f"Repair budget exhausted after {self.settings.max_repair_attempts} attempt(s). "
            "The agent could not produce a verified fix."
        )
        self._event(
            incident,
            Stage.ROLLBACK,
            f"Repair budget exhausted after {len(incident.attempts)} proposal(s) — "
            "preparing a rollback plan",
            status=EventStatus.FAILED,
        )

        plan = self.rollback.plan(incident)
        incident.status = IncidentStatus.ROLLING_BACK
        self._event(
            incident,
            Stage.ROLLBACK,
            "Restoring the repository to the last known-good commit",
            status=EventStatus.RUNNING,
            target_commit=(incident.previous_good_commit or "")[:8],
        )
        outcome = self.rollback.execute(
            incident,
            approved=None if self.settings.require_approval_for_rollback else True,
        )
        if outcome.awaiting_approval:
            incident.status = IncidentStatus.ROLLBACK_REQUIRED
            incident.final_resolution = "Rollback planned and awaiting administrator approval."
            self._event(
                incident,
                Stage.ROLLBACK,
                outcome.detail,
                status=EventStatus.WARN,
                plan=outcome.plan,
                awaiting_approval=True,
            )
        elif outcome.executed:
            incident.status = IncidentStatus.ROLLED_BACK
            incident.outcome = Outcome.ROLLED_BACK
            incident.rollback_commit = outcome.verified_commit
            incident.final_resolution = (
                f"Rolled back to the last known-good commit "
                f"{outcome.verified_commit[:8] or outcome.plan.get('target_commit', '')[:8]} and "
                "escalated to the on-call engineer."
            )
            self._event(
                incident,
                Stage.ROLLBACK,
                f"Rolled back: {outcome.detail}",
                status=EventStatus.WARN,
                plan=outcome.plan,
                restored_to=outcome.verified_commit,
            )
        else:
            incident.status = IncidentStatus.ESCALATED
            incident.outcome = Outcome.ESCALATED
            incident.warn(outcome.detail)
            incident.final_resolution = "Rollback could not be completed; escalated to a human."
            self._event(
                incident,
                Stage.ROLLBACK,
                f"Rollback failed: {outcome.detail}",
                status=EventStatus.FAILED,
                error=outcome.error,
            )

        incident.verification = (
            "No candidate fix passed verification and regression checks."
        )
        incident.resolved_at = datetime.now(timezone.utc)
        incident.touch()
        incident.metrics.duration_s = time.perf_counter() - started
        incident.metrics.attempts_used = sum(1 for a in incident.attempts if a.sandbox is not None)
        self._retain(incident, "rollback")
        return incident

    # ── memory writes ───────────────────────────────────────
    def _retain(self, incident: Incident, label: str) -> None:
        if self.memory is None:
            return
        self._event(
            incident,
            Stage.MEMORY,
            "Writing this incident back to Hindsight memory, including what failed",
            status=EventStatus.RUNNING,
            label=label,
            bank=self.memory.incident_bank,
        )
        try:
            result = self.memory.retain_incident(incident)
        except MemoryStoreError as exc:
            incident.warn(f"Hindsight retain failed: {exc}")
            self._event(
                incident,
                Stage.MEMORY,
                f"Failed to store this incident in memory: {exc}",
                status=EventStatus.FAILED,
            )
            return

        self._event(
            incident,
            Stage.MEMORY,
            f"Incident stored in Hindsight ({result.get('items_count', 0)} memory item(s) "
            f"from {result.get('content_chars', 0)} characters of report)",
            status=EventStatus.OK,
            bank=self.memory.incident_bank,
            tags=result.get("tags", []),
            label=label,
        )

    def _retain_rejected(self, incident: Incident, patch: Patch, verdict) -> None:
        if self.memory is None or not self.settings.convention_memory_enabled:
            return
        try:
            self.memory.retain_rejected_pattern(incident, patch, verdict)
            self._event(
                incident,
                Stage.MEMORY,
                "Rejected approach stored in convention memory so it is not proposed again",
                status=EventStatus.OK,
                bank=self.memory.convention_bank,
                rule=[f.rule for f in verdict.findings[:5]],
            )
        except MemoryStoreError as exc:
            incident.warn(f"Could not store the rejected approach: {exc}")

    # ── events ──────────────────────────────────────────────
    def _event(
        self,
        incident: Incident,
        stage: Stage,
        message: str,
        *,
        status: EventStatus = EventStatus.OK,
        **metadata: object,
    ) -> ExecutionEvent:
        key = (incident.id, stage.value)
        if status is EventStatus.RUNNING:
            self._stage_clock[key] = time.perf_counter()
        elif status is not EventStatus.PENDING:
            opened = self._stage_clock.pop(key, None)
            if opened is not None and "duration_ms" not in metadata:
                metadata["duration_ms"] = int((time.perf_counter() - opened) * 1000)
        event = incident.add_event(stage, message, status, **metadata)
        log.info("[%s] %s: %s", incident.id, stage.value, message)
        if self.event_sink is not None:
            try:
                self.event_sink(event)
            except Exception:  # noqa: BLE001 - a broken sink must not break a run
                log.warning("event sink raised; continuing")
        return event

    # ── messages ────────────────────────────────────────────
    @staticmethod
    def _strategy_label(incident: Incident) -> str:
        check = incident.comparability
        if check and check.comparable:
            return f"reuse prior incident {check.prior_incident_id or ''}".strip()
        return "fresh diagnosis (no comparable prior incident)"

    @staticmethod
    def _sandbox_message(number: int, sandbox) -> str:
        if sandbox.error:
            return f"Attempt {number}: sandbox error — {sandbox.error}"
        parts = [f"Attempt {number}: patched workspace tested via {sandbox.backend}"]
        if sandbox.reproduce_report is not None:
            parts.append(
                "failure reproduced"
                if sandbox.error_reproduced
                else "failure did NOT reproduce (fix would not be evidence)"
            )
        if sandbox.test_report is not None:
            parts.append(f"verify {sandbox.test_report.summary_line()}")
        if sandbox.full_report is not None:
            parts.append(f"full suite {sandbox.full_report.summary_line()}")
        return " — ".join(parts)

    @staticmethod
    def _sandbox_status(sandbox) -> EventStatus:
        if sandbox.error:
            return EventStatus.FAILED
        if sandbox.test_report is not None and sandbox.test_report.green:
            return EventStatus.OK
        return EventStatus.WARN

    @staticmethod
    def _regression_message(number: int, regression) -> str:
        if regression.acceptable:
            return f"Attempt {number}: regression check passed — {regression.notes}"
        return f"Attempt {number}: regression check failed — {regression.notes}"

    @staticmethod
    def _verification_message(number: int, sandbox, regression) -> str:
        """Say whether the original failure is genuinely gone, in measured terms."""
        before = sandbox.reproduce_report.summary_line() if sandbox.reproduce_report else None
        after = sandbox.test_report.summary_line() if sandbox.test_report else None
        if not regression.original_error_resolved:
            return (
                f"Attempt {number}: the original failure is still present after the patch"
                + (f" ({after})" if after else "")
            )
        detail = f" — before: {before}; after: {after}" if before and after else ""
        return f"Attempt {number}: original failure resolved{detail}"
