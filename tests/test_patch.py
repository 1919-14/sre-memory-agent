"""Patch building, validation and application."""

from __future__ import annotations

from sre_agent.models import FileEdit, Patch
from sre_agent.patch import (
    PatchValidator,
    apply_edits,
    build_patch_diff,
    line_counts,
    patch_from_payload,
    revert,
)


def make_patch(files: list[tuple[str, str]]) -> Patch:
    return patch_from_payload(
        {
            "root_cause": "pool too small",
            "proposed_fix": "derive the pool",
            "summary": "derive pool size",
            "files": [{"path": p, "content": c} for p, c in files],
        },
        incident_id="INC-TEST",
        attempt_number=1,
    )


# ── building ────────────────────────────────────────────────


def test_payload_becomes_a_patch() -> None:
    patch = make_patch([("app/config.py", "X = 1\n")])

    assert patch.touch_paths() == ["app/config.py"]
    assert patch.incident_id == "INC-TEST"
    assert patch.summary == "derive pool size"


def test_payload_without_files_is_rejected() -> None:
    import pytest

    from sre_agent.patch import PatchBuildError

    with pytest.raises(PatchBuildError):
        patch_from_payload({"summary": "x", "files": []}, incident_id="I", attempt_number=1)


# ── validation ──────────────────────────────────────────────


def test_valid_patch_passes(tmp_path, temp_repo) -> None:
    patch = make_patch([("app/config.py", "REDIS_POOL_SIZE = 80\n")])

    result = PatchValidator().validate(patch, temp_repo)

    assert result.ok is True
    assert result.files_changed == 1
    assert result.lines_added > 0


def test_forbidden_path_is_rejected(temp_repo) -> None:
    patch = make_patch([(".github/workflows/ci.yml", "name: ci\n")])

    result = PatchValidator().validate(patch, temp_repo)

    assert result.ok is False
    assert any("allowed patch paths" in error for error in result.errors)


def test_path_traversal_is_rejected(temp_repo) -> None:
    patch = make_patch([("../outside.py", "x = 1\n")])

    result = PatchValidator().validate(patch, temp_repo)

    assert result.ok is False
    assert any("traversal" in error for error in result.errors)


def test_hardcoded_secret_is_rejected(temp_repo) -> None:
    patch = make_patch([("app/thing.py", "TOKEN = 'gsk_abcdefghijklmnopqrst'\n")])

    result = PatchValidator().validate(patch, temp_repo)

    assert result.ok is False
    assert any("secret" in error for error in result.errors)


def test_no_op_patch_is_rejected(temp_repo) -> None:
    """Proposing the file's existing content changes nothing and must not pass."""
    existing = (temp_repo / "app" / "config.py").read_text(encoding="utf-8")
    patch = make_patch([("app/config.py", existing)])

    result = PatchValidator().validate(patch, temp_repo)

    assert result.ok is False
    assert any("no actual change" in error for error in result.errors)


def test_oversized_patch_is_rejected(temp_repo) -> None:
    big = "\n".join(f"VALUE_{i} = {i}" for i in range(400))
    patch = make_patch([("app/big.py", big)])

    result = PatchValidator().validate(patch, temp_repo)

    assert result.ok is False
    assert any("exceeding the limit" in error for error in result.errors)


def test_suspicious_content_is_only_a_warning(temp_repo) -> None:
    patch = make_patch([("app/debug.py", "def f():\n    print('hello')\n")])

    result = PatchValidator().validate(patch, temp_repo)

    assert result.ok is True
    assert any("debug" in warning for warning in result.warnings)


# ── diffs ───────────────────────────────────────────────────


def test_diff_is_generated_from_contents(temp_repo) -> None:
    patch = make_patch([("app/config.py", "REDIS_POOL_SIZE = 80\n")])

    diff = build_patch_diff(temp_repo, patch.files)
    added, removed = line_counts(diff)

    assert diff.startswith("--- a/app/config.py")
    assert added >= 1
    assert removed >= 1


# ── application ─────────────────────────────────────────────


def test_apply_and_revert(temp_repo) -> None:
    original = (temp_repo / "app" / "config.py").read_text(encoding="utf-8")
    edits = [FileEdit(path="app/config.py", content="REDIS_POOL_SIZE = 999\n")]

    result = apply_edits(temp_repo, edits)

    assert result.ok is True
    assert (temp_repo / "app" / "config.py").read_text(encoding="utf-8") == "REDIS_POOL_SIZE = 999\n"

    reverted = revert(temp_repo, result.snapshot)

    assert reverted == ["app/config.py"]
    assert (temp_repo / "app" / "config.py").read_text(encoding="utf-8") == original


def test_apply_creates_new_files_and_revert_removes_them(temp_repo) -> None:
    edits = [FileEdit(path="app/brand_new.py", content="VALUE = 1\n")]

    result = apply_edits(temp_repo, edits)

    assert result.created == ["app/brand_new.py"]
    assert (temp_repo / "app" / "brand_new.py").is_file()

    revert(temp_repo, result.snapshot)

    assert not (temp_repo / "app" / "brand_new.py").exists()


def test_apply_refuses_to_escape_the_workspace(temp_repo) -> None:
    result = apply_edits(temp_repo, [FileEdit(path="../escaped.py", content="x = 1\n")])

    assert result.ok is False
    assert not (temp_repo.parent / "escaped.py").exists()
