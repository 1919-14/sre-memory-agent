"""Environment-backed configuration.

All settings come from the process environment or `.env` (never hardcoded).
Mirrors the variables documented in `.env.example`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# `NoDecode` stops pydantic-settings from JSON-decoding list fields out of the
# environment, so the values can stay plain CSV ("a,b,c") as documented in .env.
CsvList = Annotated[list[str], NoDecode]

BASE_DIR = Path(__file__).resolve().parents[2]


def _csv(value: Any) -> list[str]:
    """Accept "a,b,c" or a real list and return a clean list of strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── LLM (Groq, OpenAI-compatible) ───────────────────────
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
    # Verified available on a standard Groq account. Note: `qwen/qwen3-32b` from the
    # hackathon brief is NOT served on every plan — check GET /openai/v1/models before
    # trusting a model name.
    groq_model_fast: str = "openai/gpt-oss-20b"
    # Used automatically if the configured model is not available on this account.
    groq_model_fallback: str = "openai/gpt-oss-20b"
    llm_temperature: float = 0.1
    llm_max_retries: int = 3
    llm_timeout_seconds: float = 90.0
    llm_json_mode: bool = True
    # Force the deterministic scripted LLM (no network). Also implied by replay mode.
    llm_offline: bool = False

    # ── Hindsight (agent memory) ────────────────────────────
    hindsight_base_url: str = "http://localhost:8888"
    hindsight_api_key: str = ""
    hindsight_bank_prefix: str = "sre:"
    hindsight_bank_template: str = "sre-incident"
    hindsight_recall_budget: str = "mid"
    hindsight_recall_max_tokens: int = 3000
    hindsight_recall_types: CsvList = ["world", "experience", "observation"]
    hindsight_prefer_observations: bool = True
    hindsight_include_source_facts: bool = True
    hindsight_memory_defense: bool = True
    hindsight_seed_on_startup: bool = True
    hindsight_api_llm_provider: str = "groq"
    hindsight_api_llm_model: str = "openai/gpt-oss-120b"
    # Groq rejects `service_tier: auto` on plans that do not include it (HTTP 400:
    # "`service_tier` `auto` is not available for this org"). Hindsight defaults to
    # `auto`, so we pin the standard tier. Valid: on_demand | flex | auto.
    hindsight_api_llm_groq_service_tier: str = "on_demand"
    # First start initialises embedded PostgreSQL and downloads embedding/reranker models.
    hindsight_start_timeout: int = 300
    # Provider quota (HTTP 429, surfaced by Hindsight as a 500 "Provider quota exhausted")
    # is not a code defect, and a blip must not lose an incident's memory. These bound the
    # wait-and-retry around memory calls.
    memory_quota_max_retries: int = 3
    memory_quota_max_wait_seconds: float = 90.0

    # ── Error coverage / taxonomy ───────────────────────────
    classifier_enabled: bool = True
    classifier_model: str = ""  # blank -> falls back to groq_model_fast
    classifier_min_confidence: float = 0.6
    specialist_classes: CsvList = ["connection-exhaustion", "config-regression"]
    escalate_classes: CsvList = ["auth-credential", "infrastructure", "unknown"]
    generic_fallback_enabled: bool = True

    # ── Code review gate ────────────────────────────────────
    code_review_enabled: bool = True
    policy_review_enabled: bool = True
    conventions_review_enabled: bool = True
    code_review_model: str = ""  # blank -> groq_model
    max_review_cycles: int = 2
    review_block_severity: str = "high"
    review_require_rootcause: bool = True

    # ── Convention memory ───────────────────────────────────
    convention_memory_enabled: bool = True
    convention_bank_suffix: str = ":conventions"
    convention_seed_path: str = "./config/conventions.py"

    # ── Regression detection ────────────────────────────────
    regression_check_enabled: bool = True
    regression_suite: str = "full"
    regression_baseline: str = "last-known-good"
    regression_max_new_failures: int = 0
    regression_flake_reruns: int = 2
    regression_blast_radius_check: bool = True

    # ── Repair budget / safety rails ────────────────────────
    max_repair_attempts: int = 3
    max_llm_calls_per_incident: int = 60
    max_incident_seconds: int = 600
    patch_max_files: int = 5
    patch_max_lines: int = 200
    patch_min_confidence: float = 0.5
    allowed_patch_paths: CsvList = ["src/", "app/", "config/", "tests/"]
    forbidden_patch_paths: CsvList = [".github/", "infra/", "migrations/", "secrets/"]
    require_approval_for_rollback: bool = False
    require_approval_for_deploy: bool = False

    # ── Sandbox ─────────────────────────────────────────────
    sandbox_backend: str = "auto"  # auto | docker | local
    sandbox_image: str = "python:3.12-slim"
    sandbox_timeout_seconds: int = 300
    sandbox_network: str = "none"
    sandbox_memory_limit: str = "1g"
    sandbox_cpus: int = 2
    sandbox_copy_repo: bool = True

    # ── Target repository under repair ──────────────────────
    demo_repo_path: str = "./demo/redis-worker-app"
    demo_branch: str = "main"
    git_last_known_good_ref: str = "origin/main"
    git_author_name: str = "sre-memory-agent"

    # ── App ─────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"
    log_to_file: bool = True
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    database_url: str = "sqlite:///./data/agent.db"
    runs_dir: str = "./data/runs"
    runbook_dir: str = "./data/runbook"
    cors_origins: CsvList = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # ── Demo reliability ────────────────────────────────────
    demo_replay_mode: bool = False
    demo_record_trajectories: bool = True

    # ── validators ──────────────────────────────────────────
    @field_validator(
        "hindsight_recall_types",
        "specialist_classes",
        "escalate_classes",
        "allowed_patch_paths",
        "forbidden_patch_paths",
        "cors_origins",
        mode="before",
    )
    @classmethod
    def _split_csv(cls, value: Any) -> list[str]:
        return _csv(value)

    # ── derived paths & helpers ─────────────────────────────
    def abspath(self, value: str | Path) -> Path:
        """Resolve a configured path against the repository root."""
        path = Path(value)
        return path if path.is_absolute() else (BASE_DIR / path)

    @property
    def base_dir(self) -> Path:
        return BASE_DIR

    @property
    def template_dir(self) -> Path:
        """The tracked, pristine copy of the demo service (never modified)."""
        return self.abspath(self.demo_repo_path)

    @property
    def live_repo_dir(self) -> Path:
        """Where `scripts/setup_demo_repo.py` builds the demo repository history.

        Kept under `data/` so the generated git repository never makes the tracked
        template look dirty.
        """
        return self.abspath("./data/demo-repo")

    @property
    def repo_dir(self) -> Path:
        """The repository the agent operates on.

        Priority: an explicitly configured path that is a real git repo, then the
        generated demo repository, then the configured path as-is. This lets the demo
        run out of the box without editing `DEMO_REPO_PATH`, while still pointing at
        your own repository if you set it.
        """
        configured = self.abspath(self.demo_repo_path)
        if (configured / ".git").exists():
            return configured
        if (self.live_repo_dir / ".git").exists():
            return self.live_repo_dir
        return configured

    @property
    def data_dir(self) -> Path:
        return self.abspath("./data")

    @property
    def runs_dir_path(self) -> Path:
        return self.abspath(self.runs_dir)

    @property
    def runbook_dir_path(self) -> Path:
        return self.abspath(self.runbook_dir)

    @property
    def sqlite_path(self) -> Path:
        """Filesystem path for the SQLite database (DATABASE_URL may be a URL)."""
        url = self.database_url
        prefix = "sqlite:///"
        if url.startswith(prefix):
            return self.abspath(url[len(prefix) :])
        return self.abspath("./data/agent.db")

    @property
    def classification_model(self) -> str:
        return self.classifier_model or self.groq_model_fast

    @property
    def review_model(self) -> str:
        return self.code_review_model or self.groq_model

    @property
    def offline(self) -> bool:
        """True when no network LLM calls may be made."""
        return self.llm_offline or self.demo_replay_mode

    @property
    def hindsight_bank(self) -> str:
        slug = self.repo_dir.name or "repo"
        return f"{self.hindsight_bank_prefix}{slug}"

    @property
    def convention_bank(self) -> str:
        return f"{self.hindsight_bank}{self.convention_bank_suffix}"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.runs_dir_path, self.runbook_dir_path):
            path.mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    def missing_credentials(self) -> list[str]:
        """Credentials needed for a live run that are not configured."""
        missing: list[str] = []
        if not self.offline and not self.groq_api_key:
            missing.append("GROQ_API_KEY")
        if not self.offline and self.hindsight_base_url.startswith("https") and not self.hindsight_api_key:
            missing.append("HINDSIGHT_API_KEY")
        return missing


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
