"""The review gate is the last line of defence before anything executes."""

from __future__ import annotations

from sre_agent.config import Settings
from sre_agent.llm import ScriptedLLM
from sre_agent.models import (
    Classification,
    ErrorClass,
    Evidence,
    FileEdit,
    Fixability,
    Incident,
    Patch,
    ReviewDecision,
    Severity,
)
from sre_agent.review import PolicyReviewer, ReviewGate


def incident(files: list[str] | None = None) -> Incident:
    item = Incident(repository="demo", error="boom")
    item.evidence = Evidence(
        changed_files=files or ["app/config.py"],
        failing_tests=["tests/test_config.py::test_pool_size_supports_concurrency"],
    )
    item.classification = Classification(
        error_class=ErrorClass.CONNECTION_EXHAUSTION,
        confidence=0.9,
        likely_fixability=Fixability.CODE_FIXABLE,
    )
    return item


def patch_with(content: str, path: str = "app/config.py") -> Patch:
    return Patch(
        files=[FileEdit(path=path, content=content)],
        root_cause="pool too small",
        proposed_fix="derive the pool",
        summary="derive pool size",
        test_strategy="run the suite",
        diff=f"--- a/{path}\n+++ b/{path}\n+{content.splitlines()[0] if content else ''}\n",
    )


# ── policy reviewer ─────────────────────────────────────────


def test_clean_patch_has_no_blocking_findings() -> None:
    findings, summary = PolicyReviewer().review(
        incident(), patch_with("REDIS_POOL_SIZE = max(8, WORKER_CONCURRENCY * 2)\n")
    )

    assert not [f for f in findings if f.severity is Severity.CRITICAL]
    assert "passed" in summary


def test_shell_execution_is_critical() -> None:
    findings, _ = PolicyReviewer().review(
        incident(), patch_with("import os\nos.system('rm -rf /tmp/x')\n")
    )

    assert any(f.severity is Severity.CRITICAL for f in findings)
    assert any(f.rule == "no-shell-execution" for f in findings)


def test_skipping_a_test_is_critical() -> None:
    findings, _ = PolicyReviewer().review(
        incident(), patch_with("@pytest.mark.skip(reason='flaky')\ndef test_x():\n    pass\n")
    )

    assert any(f.rule == "no-test-suppression" for f in findings)


def test_bare_except_is_high_severity() -> None:
    findings, _ = PolicyReviewer().review(
        incident(), patch_with("def f():\n    try:\n        g()\n    except:\n        pass\n")
    )

    assert any(f.rule == "no-bare-except" and f.severity is Severity.HIGH for f in findings)


def test_hardcoded_credential_is_critical() -> None:
    findings, _ = PolicyReviewer().review(
        incident(), patch_with("TOKEN = 'sk-abcdefghijklmnopqrstuvwx'\n")
    )

    assert any(f.rule == "no-hardcoded-secrets" for f in findings)


def test_weakened_assertion_is_flagged() -> None:
    findings, _ = PolicyReviewer().review(
        incident(["tests/test_config.py"]),
        patch_with("def test_x():\n    assert True\n", path="tests/test_config.py"),
    )

    assert any(f.rule == "no-weakened-tests" for f in findings)


def test_unrelated_file_touch_is_noted() -> None:
    findings, _ = PolicyReviewer().review(
        incident(["app/config.py"]), patch_with("VALUE = 2\n", path="app/completely_other.py")
    )

    assert any("unrelated" in f.rule or "extra-files" in f.rule for f in findings)


# ── gate decisions ──────────────────────────────────────────


def test_gate_approves_a_clean_patch() -> None:
    gate = ReviewGate(ScriptedLLM())

    verdict = gate.review(incident(), patch_with("REDIS_POOL_SIZE = 80\n"))

    assert verdict.decision is ReviewDecision.APPROVE
    assert verdict.approved is True


def test_gate_rejects_critical_findings() -> None:
    gate = ReviewGate(ScriptedLLM())

    verdict = gate.review(incident(), patch_with("import os\nos.system('ls')\n"))

    assert verdict.decision is ReviewDecision.REJECT
    assert verdict.approved is False
    assert verdict.max_severity is Severity.CRITICAL
    assert verdict.blocked_findings()


def test_gate_requests_revision_for_high_severity() -> None:
    gate = ReviewGate(ScriptedLLM())

    verdict = gate.review(
        incident(),
        patch_with("def f():\n    try:\n        g()\n    except:\n        pass\n"),
    )

    assert verdict.decision is ReviewDecision.REVISE


def test_gate_can_be_disabled() -> None:
    # A dedicated Settings instance: mutating the shared settings singleton would leak
    # into every other test (and every other component) in this process.
    gate = ReviewGate(ScriptedLLM(), Settings(code_review_enabled=False))

    verdict = gate.review(incident(), patch_with("import os\nos.system('ls')\n"))

    assert verdict.decision is ReviewDecision.APPROVE
    assert verdict.reviewers_run == []


def test_findings_become_instructions_for_the_next_attempt() -> None:
    gate = ReviewGate(ScriptedLLM())
    verdict = gate.review(incident(), patch_with("def f():\n    try:\n        g()\n    except:\n        pass\n"))

    instructions = gate.findings_as_instructions(verdict)

    assert "no-bare-except" in instructions
