"""A recorded trajectory has to replay correctly on a host that did not record it.

The deployment replays trajectories recorded on a developer's machine. Without re-anchoring,
the evidence the interface displays would name a directory that exists on nobody's laptop but
the author's — which on a public deployment also publishes a stranger's filesystem layout.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import sre_agent.config as config_module
from sre_agent.agent.recorder import TrajectoryRecorder, _rebase_paths, _recorded_root
from sre_agent.models import Attempt, Evidence, Incident, SandboxResult

# The machine that recorded the run. Deliberately Windows-style: the deployment replays these
# recordings on Linux, which is the case the separator handling exists for.
RECORDED_ROOT = r"C:\Users\someone\projects\sre-memory-agent"


def payload(*, root: str | None = RECORDED_ROOT) -> dict:
    """A minimal recording shaped like a real one, with paths from the recording host."""
    incident = Incident(
        id="INC-replay01",
        repository="demo-repo",
        repo_path=f"{RECORDED_ROOT}\\data\\demo-repo",
        error="RedisConnectionError: connection pool exhausted",
        evidence=Evidence(
            error_message="RedisConnectionError: connection pool exhausted",
            repo_path=f"{RECORDED_ROOT}\\data\\demo-repo",
            failing_tests=["tests\\test_worker.py::test_all_jobs_complete"],
        ),
    )
    incident.attempts = [
        Attempt(
            number=1,
            sandbox=SandboxResult(
                backend="local",
                workspace=f"{RECORDED_ROOT}\\data\\sandbox\\ws-1a2b3c",
            ),
        )
    ]
    data = incident.model_dump(mode="json")
    if root is not None:
        data["_root"] = root
    return data


@pytest.fixture
def recorder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TrajectoryRecorder:
    """A recorder running on a *different* host from the one that recorded the payload."""
    monkeypatch.setattr(config_module, "BASE_DIR", tmp_path)
    return TrajectoryRecorder(config_module.settings)


def store(recorder: TrajectoryRecorder, data: dict) -> Path:
    path = recorder.path_for(str(data["id"]))
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_recording_from_another_host_is_reanchored(recorder, tmp_path):
    store(recorder, payload())
    incident = recorder.load("INC-replay01")

    assert incident is not None
    assert incident.repo_path == str(tmp_path / "data" / "demo-repo")
    assert incident.evidence.repo_path == str(tmp_path / "data" / "demo-repo")
    # Nested inside an attempt's sandbox report, and separators follow the new host.
    assert incident.attempts[0].sandbox.workspace == str(tmp_path / "data" / "sandbox" / "ws-1a2b3c")


def test_no_trace_of_the_recording_host_survives(recorder):
    store(recorder, payload())
    incident = recorder.load("INC-replay01")

    assert incident is not None
    dumped = json.dumps(incident.model_dump(mode="json"))
    assert "someone" not in dumped
    assert _recorded_root(payload()) not in dumped


def test_a_recording_without_a_stored_root_is_still_reanchored(recorder, tmp_path):
    """Recordings made before the root was stored are recovered from the repository path."""
    store(recorder, payload(root=None))
    incident = recorder.load("INC-replay01")

    assert incident is not None
    assert incident.repo_path == str(tmp_path / "data" / "demo-repo")
    assert "someone" not in json.dumps(incident.model_dump(mode="json"))


def test_the_recording_host_is_left_exactly_as_recorded(recorder, tmp_path):
    """On the machine that recorded the run, replaying must not rewrite anything."""
    store(recorder, payload(root=str(tmp_path)))
    incident = recorder.load("INC-replay01")

    assert incident is not None
    assert incident.repo_path == f"{RECORDED_ROOT}\\data\\demo-repo"


def test_a_windows_recording_rebased_onto_a_linux_root_uses_forward_slashes():
    """The case the deployment hits: recorded on Windows, replayed in a Linux container."""
    rebased = _rebase_paths(
        {
            "repo_path": f"{RECORDED_ROOT}\\data\\demo-repo",
            "attempts": [{"sandbox": {"workspace": f"{RECORDED_ROOT}\\data\\sandbox\\ws-1a2b3c"}}],
        },
        RECORDED_ROOT,
        "/app",
    )

    assert rebased["repo_path"] == "/app/data/demo-repo"
    assert rebased["attempts"][0]["sandbox"]["workspace"] == "/app/data/sandbox/ws-1a2b3c"


def test_a_path_inside_a_sentence_is_not_rewritten(recorder):
    """Strings are only rewritten when they *are* the path.

    A path embedded in prose is left as recorded, and the recorder logs that it did so —
    rewriting arbitrary prose risks corrupting a message to fix a cosmetic path.
    """
    data = payload()
    line = f"could not read {RECORDED_ROOT}\\data\\demo-repo\\app\\config.py"
    data["warnings"] = [line]
    store(recorder, data)
    incident = recorder.load("INC-replay01")

    assert incident is not None
    assert incident.repo_path != f"{RECORDED_ROOT}\\data\\demo-repo"
    assert incident.warnings == [line]


def test_saving_stores_the_host_it_ran_on(recorder, tmp_path):
    incident = Incident(id="INC-save0001", repository="demo-repo", error="boom")
    path = recorder.save(incident)

    assert path is not None
    assert json.loads(path.read_text(encoding="utf-8"))["_root"] == str(tmp_path)
