"""Build a Patch from an LLM payload.

The model is asked for complete file contents. Anything malformed is surfaced as a
structured error instead of being coerced into something plausible-looking.
"""

from __future__ import annotations

from typing import Any

from ..logging_setup import get_logger
from ..models import AttemptSource, FileEdit, Patch

log = get_logger("patch-builder")


class PatchBuildError(ValueError):
    pass


def patch_from_payload(
    payload: dict[str, Any],
    *,
    incident_id: str,
    attempt_number: int,
    source: AttemptSource = AttemptSource.GENERATED_FIX,
    model: str = "",
    latency_ms: int = 0,
    derived_from_incident: str | None = None,
) -> Patch:
    """Convert a validated LLM JSON payload into a Patch."""
    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise PatchBuildError("LLM payload contained no `files` array")

    edits: list[FileEdit] = []
    for entry in raw_files:
        if not isinstance(entry, dict):
            raise PatchBuildError(f"Invalid file entry: {entry!r}")
        path = str(entry.get("path") or "").strip()
        content = entry.get("content")
        if not path:
            raise PatchBuildError("File entry is missing `path`")
        if not isinstance(content, str):
            raise PatchBuildError(f"File entry for {path} is missing string `content`")
        edits.append(
            FileEdit(path=path, content=content, rationale=str(entry.get("rationale") or ""))
        )

    patch = Patch(
        incident_id=incident_id,
        attempt_number=attempt_number,
        source=source,
        root_cause=str(payload.get("root_cause") or "").strip(),
        why_this_happened=str(payload.get("why_this_happened") or "").strip(),
        proposed_fix=str(payload.get("proposed_fix") or "").strip(),
        files=edits,
        expected_outcome=str(payload.get("expected_outcome") or "").strip(),
        risk=str(payload.get("risk") or "").strip(),
        test_strategy=str(payload.get("test_strategy") or "").strip(),
        summary=str(payload.get("summary") or "").strip(),
        addresses_root_cause=bool(payload.get("addresses_root_cause", True)),
        model=model,
        latency_ms=latency_ms,
        derived_from_incident=derived_from_incident,
    )
    log.info(
        "built patch %s for %s: %s file(s) via %s",
        patch.id[:8],
        incident_id,
        len(edits),
        source.value,
    )
    return patch
