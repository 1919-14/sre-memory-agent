"""Controlled rollback.

A rollback is a reviewed, auditable plan. It never runs automatically, and it is never
the end of the story: the incident that caused it is still retained to Hindsight, because
knowing that a whole family of fixes does NOT work is exactly as valuable as knowing one
that does.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Settings, settings as default_settings
from ..logging_setup import get_logger
from ..models import Incident
from .git_tools import GitError, GitRepo, RollbackPlan

log = get_logger("rollback")


@dataclass
class RollbackOutcome:
    planned: bool = False
    executed: bool = False
    awaiting_approval: bool = False
    plan: dict = field(default_factory=dict)
    detail: str = ""
    verified_commit: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "planned": self.planned,
            "executed": self.executed,
            "awaiting_approval": self.awaiting_approval,
            "plan": self.plan,
            "detail": self.detail,
            "verified_commit": self.verified_commit,
            "error": self.error,
        }


class RollbackManager:
    def __init__(self, repo: GitRepo, settings: Settings | None = None) -> None:
        self.repo = repo
        self.settings = settings or default_settings
        self._pending: RollbackPlan | None = None

    # ── planning ────────────────────────────────────────────
    def plan(self, incident: Incident) -> RollbackOutcome:
        target_ref = (
            incident.previous_good_commit
            or self.repo.last_known_good(self.settings.git_last_known_good_ref)
        )
        outcome = RollbackOutcome()
        try:
            plan = self.repo.plan_rollback(target_ref)
        except GitError as exc:
            outcome.error = str(exc)
            outcome.detail = f"Could not build a rollback plan: {exc}"
            log.error("rollback planning failed: %s", exc)
            return outcome

        self._pending = plan
        outcome.planned = True
        outcome.plan = plan.to_dict()
        outcome.detail = plan.description
        return outcome

    # ── execution ───────────────────────────────────────────
    def execute(
        self,
        incident: Incident,
        *,
        approved: bool | None = None,
    ) -> RollbackOutcome:
        """Execute the pending rollback, honouring the approval gate."""
        outcome = RollbackOutcome()
        if self._pending is None:
            outcome = self.plan(incident)
            if not outcome.planned:
                return outcome

        assert self._pending is not None
        requires_approval = self.settings.require_approval_for_rollback
        outcome.planned = True
        outcome.plan = self._pending.to_dict()

        if requires_approval and approved is not True:
            outcome.awaiting_approval = True
            outcome.detail = (
                "Rollback is gated: administrator approval is required before execution."
            )
            log.warning("rollback awaiting administrator approval (incident %s)", incident.id)
            return outcome

        try:
            result = self.repo.execute_rollback(self._pending, confirm=True)
        except GitError as exc:
            outcome.error = str(exc)
            outcome.detail = f"Rollback failed: {exc}"
            log.error("rollback execution failed: %s", exc)
            return outcome

        outcome.executed = True
        outcome.verified_commit = result.get("head", "")
        outcome.detail = (
            f"Repository restored to {result.get('restored_to', '')[:8]}; "
            f"working tree verified."
        )
        log.warning("rollback completed for incident %s: %s", incident.id, outcome.detail)
        return outcome

    def approve_and_execute(self, incident: Incident) -> RollbackOutcome:
        return self.execute(incident, approved=True)

    @property
    def pending(self) -> RollbackPlan | None:
        return self._pending
