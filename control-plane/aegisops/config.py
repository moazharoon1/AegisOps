"""Central configuration (environment variables, prefix AEGIS_ unless noted). See .env.example."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from aegisops.domain.enums import EnvironmentKind, RunMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AEGIS_", env_file=None, extra="ignore")

    # ------------------------------------------------------------ runtime
    environment: EnvironmentKind = EnvironmentKind.CLUSTER
    storage_backend: str = "dynamodb"  # dynamodb | memory
    enable_simulation: bool = False  # local-only scenario injection endpoints
    log_level: str = "INFO"
    keys_dir: Path = Path(".aegisops/keys")
    data_dir: Path = Path(".data")  # artifacts live under <data_dir>/artifacts
    version: str = "0.1.0"

    # ------------------------------------------------------------ AI
    llm_mode: str = "auto"  # auto | live | record | replay | deterministic
    model_specialist: str = "gpt-5.4-mini-2026-03-17"
    model_analyst: str = "gpt-5.4-2026-03-05"
    embedding_model: str = "text-embedding-3-small"
    replay_dir: Path = Path("../evaluation/fixtures/replay")
    budget_per_incident_usd: float = 1.0
    budget_per_day_usd: float = 10.0
    max_parallel_model_calls: int = 3
    max_investigation_passes: int = 2
    max_tool_calls_per_agent: int = 12
    compaction_threshold_tokens: int = 12_000
    compaction_target_tokens: int = 6_000

    # ------------------------------------------------------------ workflow
    approval_ttl_seconds: int = 900
    verification_window_seconds: int = 600
    verification_interval_seconds: int = 15
    dedup_ttl_seconds: int = 3600
    grouping_window_minutes: int = 60
    healthy_window_seconds: int = 300  # change recorder: known-good after this long healthy

    # ------------------------------------------------------------ AWS emulation
    aws_endpoint_url: str = Field(default="http://localhost:4566", validation_alias="AWS_ENDPOINT_URL")
    aws_region: str = Field(default="us-east-1", validation_alias="AWS_REGION")
    dynamodb_endpoint_url: str = "http://localhost:8000"
    table_prefix: str = "aegisops"
    artifact_bucket: str = "aegisops-artifacts"
    event_bus: str = "aegisops-events"
    workflow_queue: str = "aegisops-workflow"

    # ------------------------------------------------------------ control-plane PostgreSQL
    database_url: str = "postgresql://aegisops:aegisops@localhost:5432/aegisops"

    # ------------------------------------------------------------ observability endpoints
    prometheus_url: str = "http://prometheus-server.observability.svc.cluster.local"
    alertmanager_url: str = "http://prometheus-alertmanager.observability.svc.cluster.local:9093"
    loki_url: str = "http://loki.observability.svc.cluster.local:3100"
    tempo_url: str = "http://tempo.observability.svc.cluster.local:3200"
    loki_service_label: str = "service_name"

    # ------------------------------------------------------------ MCP servers
    mcp_diagnostics_url: str = "http://mcp-diagnostics.aegisops.svc.cluster.local:8080/mcp"
    mcp_knowledge_url: str = "http://mcp-knowledge.aegisops.svc.cluster.local:8080/mcp"
    mcp_mutations_url: str = "http://mcp-mutations.aegisops.svc.cluster.local:8080/mcp"
    mcp_transport: str = "http"  # http | inprocess

    # ------------------------------------------------------------ simulation harness
    sim_controller_url: str = "http://sim-controller.simulation.svc.cluster.local:8080"

    # ------------------------------------------------------------ auth
    users_file: Path = Path(".aegisops/users.json")  # {username: {password_hash, roles, display_name}}
    alert_webhook_token: SecretStr = SecretStr("")  # shared secret for Alertmanager -> intake

    # ------------------------------------------------------------ secrets (unprefixed)
    openai_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="OPENAI_API_KEY")

    def resolved_llm_mode(self) -> RunMode:
        if self.llm_mode == "auto":
            return RunMode.LIVE if self.openai_api_key.get_secret_value() else RunMode.DETERMINISTIC
        return RunMode(self.llm_mode)

    def table(self, name: str) -> str:
        return f"{self.table_prefix}-{name}"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def repo_root() -> Path:
    """Repository root (the directory containing `control-plane/`)."""
    env = os.environ.get("AEGIS_REPO_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]
