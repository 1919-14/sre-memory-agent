"""Configuration loading. Every value must come from the environment, never the code."""

from __future__ import annotations

from pathlib import Path

from sre_agent.config import Settings


def test_csv_lists_are_parsed_from_strings() -> None:
    """Values arrive from .env as plain CSV, not JSON."""
    settings = Settings(
        specialist_classes="connection-exhaustion,config-regression",
        escalate_classes="auth-credential,infrastructure,unknown",
        allowed_patch_paths="src/, app/, config/",
    )

    assert settings.specialist_classes == ["connection-exhaustion", "config-regression"]
    assert settings.escalate_classes == ["auth-credential", "infrastructure", "unknown"]
    assert settings.allowed_patch_paths == ["src/", "app/", "config/"]


def test_bank_names_are_namespaced_and_distinct(tmp_path, monkeypatch) -> None:
    settings = Settings(hindsight_bank_prefix="sre:", demo_repo_path="./demo/redis-worker-app")
    # Pin the repository so the bank name does not depend on whether the generated demo
    # repo happens to exist on this machine.
    monkeypatch.setattr(Settings, "live_repo_dir", property(lambda self: tmp_path / "absent"))

    assert settings.hindsight_bank == "sre:redis-worker-app"
    assert settings.convention_bank == "sre:redis-worker-app:conventions"
    assert settings.hindsight_bank != settings.convention_bank


def test_relative_paths_resolve_against_the_project_root() -> None:
    settings = Settings(demo_repo_path="./demo/redis-worker-app", runs_dir="./data/runs")

    assert settings.template_dir.is_absolute()
    assert settings.template_dir == settings.base_dir / "demo" / "redis-worker-app"
    assert settings.runs_dir_path == settings.base_dir / "data" / "runs"


def test_sqlite_path_is_derived_from_the_database_url() -> None:
    settings = Settings(database_url="sqlite:///./data/agent.db")

    assert settings.sqlite_path.name == "agent.db"
    assert settings.sqlite_path.is_absolute()


def test_model_selection_falls_back_to_a_known_model() -> None:
    settings = Settings(groq_model="openai/gpt-oss-120b", classifier_model="", code_review_model="")

    assert settings.groq_model_fast, "a fast model must always be configured"
    assert settings.classification_model == settings.groq_model_fast
    assert settings.review_model == settings.groq_model


def test_offline_mode_is_implied_by_replay() -> None:
    assert Settings(demo_replay_mode=True).offline is True
    assert Settings(llm_offline=True).offline is True
    assert Settings(llm_offline=False, demo_replay_mode=False).offline is False


def test_missing_credentials_are_reported() -> None:
    settings = Settings(groq_api_key="", llm_offline=False)

    assert "GROQ_API_KEY" in settings.missing_credentials()


def test_configured_repo_wins_when_it_is_a_git_repository(tmp_path, monkeypatch) -> None:
    configured = tmp_path / "my-service"
    (configured / ".git").mkdir(parents=True)
    live = tmp_path / "demo-repo"
    (live / ".git").mkdir(parents=True)

    settings = Settings(demo_repo_path=str(configured))
    monkeypatch.setattr(Settings, "live_repo_dir", property(lambda self: live))

    assert settings.repo_dir == configured


def test_generated_demo_repo_is_used_when_configured_path_is_not_a_repo(tmp_path, monkeypatch) -> None:
    """The tracked template is not a git repo, so the generated one is used instead."""
    template = tmp_path / "template"
    template.mkdir()
    live = tmp_path / "demo-repo"
    (live / ".git").mkdir(parents=True)

    settings = Settings(demo_repo_path=str(template))
    monkeypatch.setattr(Settings, "live_repo_dir", property(lambda self: live))

    assert settings.repo_dir == live


def test_falls_back_to_the_configured_path_when_nothing_exists(tmp_path, monkeypatch) -> None:
    template = tmp_path / "template"
    template.mkdir()

    settings = Settings(demo_repo_path=str(template))
    monkeypatch.setattr(Settings, "live_repo_dir", property(lambda self: tmp_path / "absent"))

    assert settings.repo_dir == template


def test_ensure_dirs_creates_the_working_directories(tmp_path) -> None:
    settings = Settings(
        runs_dir=str(tmp_path / "runs"),
        runbook_dir=str(tmp_path / "runbook"),
        database_url=f"sqlite:///{tmp_path / 'db' / 'agent.db'}",
    )

    settings.ensure_dirs()

    assert settings.runs_dir_path.is_dir()
    assert settings.runbook_dir_path.is_dir()
    assert settings.sqlite_path.parent.is_dir()
