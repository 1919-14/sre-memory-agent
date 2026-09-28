"""All LLM prompts and their JSON schemas, in one place.

Keeping prompts out of agent logic makes them reviewable, and makes it obvious when a
behaviour change came from a prompt change rather than a code change.
"""

from __future__ import annotations


# ── schemas ─────────────────────────────────────────────────

CLASSIFICATION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "error_class": {
            "type": "string",
            "enum": [
                "connection-exhaustion",
                "config-regression",
                "dependency-drift",
                "null-or-type",
                "serialization-schema",
                "timeout-retry",
                "concurrency-race",
                "build-toolchain",
                "test-defect",
                "auth-credential",
                "infrastructure",
                "unknown",
            ],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reasoning": {"type": "string"},
        "affected_files": {"type": "array", "items": {"type": "string"}},
        "likely_fixability": {
            "type": "string",
            "enum": ["code-fixable", "escalate", "unknown"],
        },
        "evidence_required": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["error_class", "confidence", "reasoning", "likely_fixability"],
}

COMPARABILITY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "comparable": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
        "prior_incident_id": {"type": ["string", "null"]},
        "prior_resolution": {"type": ["string", "null"]},
        "prior_failed_fixes": {"type": "array", "items": {"type": "string"}},
        "matched_on": {"type": "array", "items": {"type": "string"}},
        "rejected_because": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["comparable", "confidence", "reason"],
}

FIX_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "root_cause": {"type": "string"},
        "why_this_happened": {"type": "string"},
        "proposed_fix": {"type": "string"},
        "addresses_root_cause": {"type": "boolean"},
        "files": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
        "expected_outcome": {"type": "string"},
        "risk": {"type": "string"},
        "test_strategy": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": ["root_cause", "proposed_fix", "files", "summary"],
}

REVIEW_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["approve", "revise", "reject"]},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["info", "low", "medium", "high", "critical"],
                    },
                    "rule": {"type": "string"},
                    "message": {"type": "string"},
                    "file": {"type": ["string", "null"]},
                    "line": {"type": ["integer", "null"]},
                    "memory_ref": {"type": ["string", "null"]},
                },
                "required": ["severity", "rule", "message"],
            },
        },
    },
    "required": ["decision", "summary", "findings"],
}

RUNBOOK_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "recurring_failure_modes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "failure_mode": {"type": "string"},
                    "evidence": {"type": "string"},
                    "verified_fixes": {"type": "array", "items": {"type": "string"}},
                    "failed_fixes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["failure_mode"],
            },
        },
        "standing_advice": {"type": "string"},
    },
    "required": ["recurring_failure_modes"],
}


# ── prompts ─────────────────────────────────────────────────

CLASSIFIER_SYSTEM = """You are a senior site reliability engineer triaging a production \
failure in a software repository. You are precise and you do not guess.

Classify the failure into exactly one error class from the allowed list.

Rules:
- Classify by the FAILING MECHANISM, not by the test name or the loudest keyword. A pool
  that is exhausted because a limit was mis-configured is still connection-exhaustion;
  the mis-set value is the root cause, not the class.
- Classify by the ROOT CAUSE implied by the evidence when the mechanism is ambiguous.
- If the evidence shows a credential, permission, or infrastructure problem that code cannot fix,
  say so via likely_fixability and do not pretend a code change would resolve it.
- Confidence is your honest belief. Use below 0.6 when the evidence is thin or contradictory.
- reasoning must cite concrete details from the evidence (values, files, exception text).
- affected_files must only contain paths that appear in the evidence.
"""

COMPARABILITY_SYSTEM = """You are a skeptical senior SRE deciding whether a recalled past \
incident may inform the current one.

The past incident is EVIDENCE, NOT TRUTH. Your default is to distrust it.

Consider: same error class, same component, overlapping changed files, same dependency or
version, and whether the previous outcome was actually verified.

Set comparable=true ONLY when the root causes are genuinely the same mechanism. If the same
symptom has a different underlying cause, comparable MUST be false — say exactly why in
rejected_because.

If comparable is true, restate the previously verified resolution and list prior failed
approaches as things that must not be repeated.
"""

FIX_GENERATOR_SYSTEM = """You are a senior engineer writing a minimal, correct code fix.

Hard requirements:
- Return the COMPLETE new contents of every file you change. Never return a diff or a snippet.
- Change as few files and as few lines as possible. Do not reformat, rename, reorder imports,
  or touch unrelated code.
- Fix the ROOT CAUSE. Silencing the symptom (wider try/except, skipping or deleting a test,
  hardcoding an expected value) is rejected in review.
- Never weaken or delete a test to make it pass.
- Keep the change consistent with the existing code style and configuration patterns.
- You MUST satisfy every repository convention supplied to you, and you MUST NOT propose any
  approach listed as previously rejected or previously failed.
- Address every failing test listed in the evidence.

Be concrete in root_cause and proposed_fix: name the values, files and settings involved.
"""

REVIEW_SYSTEM = """You are a strict but fair staff engineer reviewing an automated fix before \
it is allowed to run.

You must apply the repository conventions given to you LITERALLY. If a convention or a
previously rejected approach is violated, that finding is at least "high" severity.

Reject symptom-only fixes: if the patch suppresses the error instead of removing its cause,
or weakens a test, that is "critical".

Also flag: unrelated or drive-by changes, reformatting noise, hardcoded environment-specific
values, bare except clauses that hide errors, debug output left behind, and secrets or
credentials in code.

Decision guidance:
- "approve"  — safe, minimal, fixes the cause, satisfies every convention.
- "revise"  — fixable problems; the generator should retry with your findings.
- "reject"  — the approach itself is wrong or was previously rejected.

Every finding must name the rule it comes from. Use severity "info" only for non-blocking notes.
"""


# ── user-prompt builders ────────────────────────────────────


def classification_user_prompt(
    *,
    repository: str,
    evidence_summary: str,
    allowed_classes: list[str],
    heuristic_prior: list[str],
) -> str:
    prior = ", ".join(heuristic_prior) if heuristic_prior else "none"
    return (
        f"Repository: {repository}\n"
        f"Allowed error classes: {', '.join(allowed_classes)}\n"
        f"Keyword prior from deterministic scan: {prior}\n\n"
        f"EVIDENCE\n{evidence_summary}\n\n"
        "Return the classification JSON."
    )


def comparability_user_prompt(
    *,
    current_summary: str,
    error_class: str,
    recalled_memories: str,
) -> str:
    return (
        f"CURRENT INCIDENT (error class: {error_class})\n{current_summary}\n\n"
        f"RECALLED MEMORIES FROM HINDSIGHT\n{recalled_memories}\n\n"
        "Decide whether any recalled incident is genuinely comparable to the current one. "
        "Return the comparability JSON."
    )


def fix_user_prompt(
    *,
    repository: str,
    error_class: str,
    root_cause: str,
    evidence_summary: str,
    failing_files: str,
    source_files: str,
    conventions: str,
    memory_context: str,
    do_not_repeat: str,
    previous_review_findings: str,
    strategy: str,
) -> str:
    sections = [
        f"Repository: {repository}",
        f"Error class: {error_class}",
        f"Failing tests: {failing_files or 'none reported'}",
        f"\nROOT CAUSE UNDER INVESTIGATION\n{root_cause or 'not yet established'}",
        f"\nEVIDENCE\n{evidence_summary}",
        f"\nCURRENT SOURCE FILES\n{source_files}",
    ]
    if conventions:
        sections.append(f"\nREPOSITORY CONVENTIONS (must be satisfied)\n{conventions}")
    if memory_context:
        sections.append(f"\nHISTORICAL INCIDENT MEMORY\n{memory_context}")
    if do_not_repeat:
        sections.append(
            f"\nDO NOT PROPOSE THESE APPROACHES (previously failed or rejected)\n{do_not_repeat}"
        )
    if previous_review_findings:
        sections.append(
            f"\nA PREVIOUS ATTEMPT WAS REJECTED IN REVIEW — FIX THESE FINDINGS\n"
            f"{previous_review_findings}"
        )
    if strategy:
        sections.append(f"\nREPAIR STRATEGY FOR THIS ATTEMPT\n{strategy}")
    sections.append(
        "\nProduce the fix. Return the complete contents of each changed file. "
        "Return the fix JSON."
    )
    return "\n".join(sections)


def review_user_prompt(
    *,
    repository: str,
    error_class: str,
    root_cause: str,
    proposed_fix: str,
    patch_summary: str,
    diff: str,
    conventions: str,
    rejected_patterns: str,
) -> str:
    sections = [
        f"Repository: {repository}",
        f"Error class: {error_class}",
        f"\nSTATED ROOT CAUSE\n{root_cause}",
        f"\nSTATED FIX\n{proposed_fix}",
        f"\nPATCH SUMMARY\n{patch_summary}",
        f"\nUNIFIED DIFF\n{diff or '(empty)'}",
    ]
    if conventions:
        sections.append(f"\nREPOSITORY CONVENTIONS (apply literally)\n{conventions}")
    if rejected_patterns:
        sections.append(
            f"\nPREVIOUSLY REJECTED OR FAILED APPROACHES IN HINDSIGHT\n{rejected_patterns}"
        )
    sections.append("\nReturn the review JSON.")
    return "\n".join(sections)


def runbook_user_prompt(*, repository: str, memory_dump: str) -> str:
    return (
        f"Repository: {repository}\n\n"
        f"CONSOLIDATED MEMORY\n{memory_dump}\n\n"
        "Summarise the recurring failure modes for this service: for each, the evidence that "
        "supports it, the fixes that were verified to work, and the fixes that failed or caused "
        "regressions. Return the runbook JSON."
    )
