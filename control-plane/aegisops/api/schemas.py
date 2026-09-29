"""API request/response view models (the frontend's generated types come from these)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aegisops.domain.enums import (
    AgentRole,
    AgentRunStatus,
    EnvironmentKind,
    IncidentSource,
    IncidentStatus,
    RunMode,
    Severity,
)
from aegisops.domain.models import (
    Approval,
    Diagnosis,
    Execution,
    Incident,
    LlmUsage,
    RemediationPlan,
    User,
)
from aegisops.domain.tools import MemoryHit


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ----------------------------------------------------------------------------- auth & system
class LoginRequest(ApiModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(ApiModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: User


class DependencyHealth(ApiModel):
    name: str  # dynamodb | localstack | postgres | prometheus | loki | tempo | kubernetes | mcp-* | openai
    status: Literal["ok", "degraded", "down", "unknown"]
    detail: str | None = None


class BudgetStatus(ApiModel):
    per_incident_usd: float
    per_day_usd: float
    spent_today_usd: float


class SystemStatus(ApiModel):
    version: str
    environment: EnvironmentKind
    run_mode: RunMode  # always displayed: live AI vs replay vs deterministic
    models: dict[str, str]  # {"specialist": ..., "analyst": ..., "embedding": ...}
    simulation_enabled: bool
    dependencies: list[DependencyHealth]
    budget: BudgetStatus
    verification_window_seconds: int


class PermissionMatrix(ApiModel):
    roles: dict[str, list[str]]  # agent role -> tool names
    human_only_tools: list[str]
    mutation_tools: list[str]


# ----------------------------------------------------------------------------- incidents
class IncidentListItem(ApiModel):
    incident_id: str
    title: str
    severity: Severity
    status: IncidentStatus
    status_reason: str | None = None
    services: list[str]
    source: IncidentSource
    created_at: datetime
    updated_at: datetime
    awaiting_approval: bool
    current_plan_id: str | None = None
    run_mode: RunMode | None = None


class IncidentPage(ApiModel):
    items: list[IncidentListItem]
    next_cursor: str | None = None


class AgentProgress(ApiModel):
    agent: AgentRole
    display_name: str
    status: AgentRunStatus
    runs: int = 0
    tool_calls: int = 0
    last_summary: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    usage: LlmUsage = Field(default_factory=LlmUsage)


class IncidentDetail(ApiModel):
    incident: Incident
    diagnosis: Diagnosis | None = None
    current_plan: RemediationPlan | None = None
    approvals: list[Approval] = Field(default_factory=list)
    executions: list[Execution] = Field(default_factory=list)
    agents: list[AgentProgress] = Field(default_factory=list)
    evidence_count: int = 0
    finding_count: int = 0
    report_available: bool = False


class CreateIncidentRequest(ApiModel):
    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    services: list[str] = Field(default_factory=list, max_length=5)
    severity: Severity = Severity.SEV3


class DecisionRequest(ApiModel):
    plan_hash: str  # the hash the human reviewed; must match the stored plan exactly
    comment: str | None = Field(default=None, max_length=2000)


class RejectRequest(ApiModel):
    plan_hash: str
    reason: str = Field(min_length=3, max_length=2000)


class RevisionRequest(ApiModel):
    plan_hash: str
    feedback: str = Field(min_length=3, max_length=2000)


class CancelRequest(ApiModel):
    reason: str = Field(min_length=3, max_length=2000)


class ResolveRequest(ApiModel):
    note: str = Field(min_length=3, max_length=2000)  # manual resolution from needs_attention


class DecisionResponse(ApiModel):
    approval: Approval
    incident_status: IncidentStatus


# ----------------------------------------------------------------------------- alerts (Alertmanager webhook v4)
class AlertmanagerAlert(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Literal["firing", "resolved"]
    labels: dict[str, str]
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime
    endsAt: datetime | None = None
    generatorURL: str | None = None
    fingerprint: str


class AlertmanagerWebhook(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: str = "4"
    groupKey: str | None = None
    status: Literal["firing", "resolved"]
    receiver: str | None = None
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str | None = None
    alerts: list[AlertmanagerAlert]


class AlertIngestResponse(ApiModel):
    accepted: int
    deduplicated: int
    ignored_resolved: int
    incidents: list[str]  # incident ids created or updated


# ----------------------------------------------------------------------------- knowledge
class MemorySearchResponse(ApiModel):
    matches: list[MemoryHit]


class InvalidateMemoryRequest(ApiModel):
    reason: str = Field(min_length=3, max_length=1000)


# ----------------------------------------------------------------------------- scenarios
class ScenarioInjectRequest(ApiModel):
    variant: str = "canonical"


# ----------------------------------------------------------------------------- evaluations
class EvaluationRunSummary(ApiModel):
    run_id: str
    created_at: datetime
    environment: EnvironmentKind
    run_mode: RunMode
    models: dict[str, str] = Field(default_factory=dict)
    suite: str  # e.g. "positive", "negative", "compaction", "memory", "canonical-cluster"
    cases: int
    metrics: dict[str, float | None] = Field(default_factory=dict)
    shortened_verification: bool = False
    notes: str | None = None


class EvaluationRunDetail(ApiModel):
    summary: EvaluationRunSummary
    cases: list[dict[str, Any]]
    report_markdown: str | None = None
