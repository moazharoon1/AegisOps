"""Versioned domain objects: the durable business records of AegisOps.

Persistence stores `model_dump(mode="json")`; every record carries `schema_version`.
Approval and execution records are authoritative structured data and are never replaced by an
LLM summary (see compaction rules in docs/CONTRACTS.md).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aegisops.domain.common import canonical_json, content_hash, sha256_hex, utcnow
from aegisops.domain.enums import (
    ActionType,
    ActorType,
    AgentRole,
    AgentRunStatus,
    ApprovalDecision,
    AuditOutcome,
    Comparator,
    ExecutionStatus,
    FaultType,
    HypothesisStatus,
    IncidentSource,
    IncidentStatus,
    MemoryStatus,
    PlanStatus,
    ResourceKind,
    ReviewVerdict,
    RiskLevel,
    RunMode,
    Severity,
    StepStatus,
    TimelineKind,
    UserRole,
    VerificationSignal,
    VerificationStatus,
)
from aegisops.domain.resources import ResourceRef

SCHEMA_VERSION = 1


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = SCHEMA_VERSION


# --------------------------------------------------------------------------- Incidents


class AlertRef(BaseModel):
    """An alert (or manual report / health check) attached to an incident."""

    model_config = ConfigDict(extra="forbid")
    fingerprint: str
    name: str
    severity: str
    service: str | None = None
    namespace: str | None = None
    summary: str | None = None
    starts_at: datetime
    received_at: datetime
    labels: dict[str, str] = Field(default_factory=dict)


class IncidentMetrics(BaseModel):
    """Timing and cost facts used by the dashboard and evaluation (all optional until reached)."""

    model_config = ConfigDict(extra="forbid")
    detected_at: datetime | None = None  # first alert start
    received_at: datetime | None = None
    investigation_started_at: datetime | None = None
    diagnosed_at: datetime | None = None
    approval_requested_at: datetime | None = None
    approval_decided_at: datetime | None = None
    execution_started_at: datetime | None = None
    execution_finished_at: datetime | None = None
    verification_finished_at: datetime | None = None
    resolved_at: datetime | None = None
    investigation_passes: int = 0
    tool_calls: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    compactions: int = 0


class Incident(Record):
    incident_id: str  # INC-<n>
    title: str
    description: str | None = None
    source: IncidentSource
    services: list[str] = Field(default_factory=list)
    namespace: str | None = "production"
    severity: Severity
    status: IncidentStatus = IncidentStatus.RECEIVED
    status_reason: str | None = None  # why needs_attention / cancelled
    correlation_key: str
    alerts: list[AlertRef] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    resolved_at: datetime | None = None
    run_mode: RunMode | None = None
    current_plan_id: str | None = None
    diagnosis_id: str | None = None
    memory_matches: list[str] = Field(default_factory=list)  # memory ids retrieved for this incident
    metrics: IncidentMetrics = Field(default_factory=IncidentMetrics)
    created_by: str = "system:intake"
    version: int = 1  # optimistic concurrency; every successful update increments it


# --------------------------------------------------------------------------- Investigation


class Evidence(Record):
    evidence_id: str
    incident_id: str
    source: str  # tool name, e.g. "k8s_list_pods"
    collected_by: AgentRole
    observed_at: datetime
    query: dict[str, Any] = Field(default_factory=dict)  # tool arguments
    summary: str  # one-line human summary
    data: Any = None  # bounded, redacted result (what agents see)
    artifact_uri: str | None = None  # full redacted payload, e.g. artifact://incidents/INC-1/EV-...json
    content_hash: str  # hash of the full redacted payload
    status: str = "ok"  # ToolStatus value
    redactions: int = 0
    truncated: bool = False


class Finding(Record):
    finding_id: str
    incident_id: str
    agent: AgentRole
    hypothesis: str
    fault_type: FaultType | None = None
    supporting_evidence: list[str] = Field(default_factory=list)  # evidence ids
    contradicting_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    affected_resources: list[ResourceRef] = Field(default_factory=list)
    investigation_pass: int = 1
    created_at: datetime = Field(default_factory=utcnow)


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str
    fault_type: FaultType
    status: HypothesisStatus
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    explanation: str  # concise decision explanation (not private chain-of-thought)


class Diagnosis(Record):
    diagnosis_id: str
    incident_id: str
    fault_type: FaultType
    root_cause: str
    summary: str
    affected_resources: list[ResourceRef] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    cited_evidence: list[str] = Field(default_factory=list)
    runbook_refs: list[str] = Field(default_factory=list)  # e.g. RB-009
    similar_incidents: list[str] = Field(default_factory=list)  # incident ids
    memory_used: list[str] = Field(default_factory=list)  # memory ids consulted
    missing_information: list[str] = Field(default_factory=list)
    longer_term_recommendations: list[str] = Field(default_factory=list)
    investigation_pass: int = 1
    produced_by: AgentRole = AgentRole.ROOT_CAUSE_ANALYST
    model: str | None = None  # model id or "deterministic"
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- Remediation plans


class RolloutUndoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_revision: int = Field(ge=1)


class RolloutRestartParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScaleDeploymentParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    replicas: int = Field(ge=0, le=10)
    from_replicas: int = Field(ge=0, le=10)  # expected current desired replicas


class RestoreConfigMapKeyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=253)
    snapshot_id: str  # recorded snapshot holding the known-good value
    value: str = Field(max_length=4096)  # the value that will be restored (non-secret configuration)
    current_value: str | None = Field(default=None, max_length=4096)  # expected value before the change


class RestoreSecretVersionParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str  # version that becomes AWSCURRENT
    from_version_id: str  # expected current AWSCURRENT version


class SetQueueRedrivePolicyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_receive_count: int = Field(ge=1, le=10)
    dead_letter_queue: str


ACTION_PARAM_MODELS: dict[ActionType, type[BaseModel]] = {
    ActionType.ROLLOUT_UNDO: RolloutUndoParams,
    ActionType.ROLLOUT_RESTART: RolloutRestartParams,
    ActionType.SCALE_DEPLOYMENT: ScaleDeploymentParams,
    ActionType.RESTORE_CONFIGMAP_KEY: RestoreConfigMapKeyParams,
    ActionType.RESTORE_SECRET_VERSION: RestoreSecretVersionParams,
    ActionType.SET_QUEUE_REDRIVE_POLICY: SetQueueRedrivePolicyParams,
}

ACTION_TARGET_KINDS: dict[ActionType, ResourceKind] = {
    ActionType.ROLLOUT_UNDO: ResourceKind.DEPLOYMENT,
    ActionType.ROLLOUT_RESTART: ResourceKind.DEPLOYMENT,
    ActionType.SCALE_DEPLOYMENT: ResourceKind.DEPLOYMENT,
    ActionType.RESTORE_CONFIGMAP_KEY: ResourceKind.CONFIGMAP,
    ActionType.RESTORE_SECRET_VERSION: ResourceKind.SECRET,
    ActionType.SET_QUEUE_REDRIVE_POLICY: ResourceKind.QUEUE,
}


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")  # e.g. "step-1"
    action: ActionType
    target: ResourceRef
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    expected_outcome: str

    @model_validator(mode="after")
    def _validate_action(self) -> PlanStep:
        expected_kind = ACTION_TARGET_KINDS[self.action]
        if self.target.kind != expected_kind:
            raise ValueError(f"{self.action.value} targets {expected_kind.value}, not {self.target.kind.value}")
        if expected_kind in (ResourceKind.DEPLOYMENT, ResourceKind.CONFIGMAP) and not self.target.namespace:
            raise ValueError("Kubernetes targets require a namespace")
        validated = ACTION_PARAM_MODELS[self.action].model_validate(self.params)
        self.params = validated.model_dump(mode="json")
        return self

    def typed_params(self) -> BaseModel:
        return ACTION_PARAM_MODELS[self.action].model_validate(self.params)


class PrerequisiteKind(BaseModel):
    """Namespace for prerequisite kind constants (kept as plain strings for schema simplicity)."""

    DEPLOYMENT_REVISION: ClassVar[str] = "deployment_revision"  # expected: current revision number
    DEPLOYMENT_REPLICAS: ClassVar[str] = "deployment_replicas"  # expected: desired replicas
    DEPLOYMENT_TEMPLATE_HASH: ClassVar[str] = "deployment_template_hash"
    CONFIGMAP_KEY_VALUE: ClassVar[str] = "configmap_key_value"  # expected: "<key>=<value>"
    SECRET_CURRENT_VERSION: ClassVar[str] = "secret_current_version"  # expected: version id
    RESOURCE_EXISTS: ClassVar[str] = "resource_exists"  # expected: "true"


class Prerequisite(BaseModel):
    """A fact about the current environment that must still hold when a step executes."""

    model_config = ConfigDict(extra="forbid")
    prerequisite_id: str
    kind: str  # one of PrerequisiteKind constants
    target: ResourceRef
    expected: str
    description: str


class VerificationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check_id: str
    signal: VerificationSignal
    target: str  # service / deployment / queue / "service->peer" / database
    comparator: Comparator
    threshold: float
    description: str


class VerificationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checks: list[VerificationCheck] = Field(min_length=1)
    window_seconds: int = Field(default=600, ge=30, le=3600)
    sample_interval_seconds: int = Field(default=15, ge=1, le=120)
    min_samples: int = Field(default=10, ge=1)
    min_request_rate_rps: float = Field(default=0.2, ge=0.0)  # traffic sufficiency for rate-based checks


class PolicyCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str  # e.g. "allowed_action", "namespace_allowlist", "contraindication:scale_db_clients"
    passed: bool
    detail: str


class PlanReview(Record):
    review_id: str
    plan_id: str
    plan_hash: str
    reviewer: AgentRole = AgentRole.CHANGE_PLAN_REVIEWER
    verdict: ReviewVerdict
    policy_checks: list[PolicyCheckResult] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    rationale: str
    model: str | None = None
    reviewed_at: datetime = Field(default_factory=utcnow)


class RemediationPlan(Record):
    """An immutable plan revision. Any content change requires a new plan_id/revision, a new
    review, and a new human approval. `plan_hash` binds approvals to this exact content."""

    plan_id: str
    incident_id: str
    revision: int = Field(ge=1)
    supersedes_plan_id: str | None = None
    diagnosis_id: str
    fault_type: FaultType
    title: str
    summary: str
    steps: list[PlanStep] = Field(min_length=1, max_length=6)
    prerequisites: list[Prerequisite] = Field(default_factory=list)
    verification: VerificationSpec
    compensation: list[PlanStep] = Field(default_factory=list, max_length=3)  # pre-approved recovery
    risk: RiskLevel
    risk_rationale: str
    runbook_refs: list[str] = Field(default_factory=list)
    expected_recovery: str
    created_by: AgentRole = AgentRole.ROOT_CAUSE_ANALYST
    created_at: datetime = Field(default_factory=utcnow)
    status: PlanStatus = PlanStatus.PENDING_REVIEW
    review: PlanReview | None = None
    plan_hash: str = ""

    HASHED_FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "plan_id",
        "incident_id",
        "revision",
        "diagnosis_id",
        "fault_type",
        "steps",
        "prerequisites",
        "verification",
        "compensation",
        "risk",
    )

    @field_validator("steps")
    @classmethod
    def _unique_step_ids(cls, steps: list[PlanStep]) -> list[PlanStep]:
        ids = [s.step_id for s in steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique within a plan")
        return steps

    def compute_hash(self) -> str:
        payload = {name: getattr(self, name) for name in self.HASHED_FIELDS}
        return content_hash(payload)

    def sealed(self) -> RemediationPlan:
        """Return a copy with `plan_hash` computed. Call once when the revision is created."""
        return self.model_copy(update={"plan_hash": self.compute_hash()})

    def hash_is_valid(self) -> bool:
        return bool(self.plan_hash) and self.plan_hash == self.compute_hash()

    def find_step(self, step_id: str) -> PlanStep | None:
        for step in [*self.steps, *self.compensation]:
            if step.step_id == step_id:
                return step
        return None

    @property
    def blast_radius(self) -> list[ResourceRef]:
        seen: dict[str, ResourceRef] = {}
        for step in self.steps:
            seen.setdefault(step.target.key, step.target)
        return list(seen.values())


# --------------------------------------------------------------------------- Approval & execution


class Approval(Record):
    approval_id: str
    incident_id: str
    plan_id: str
    plan_hash: str
    decision: ApprovalDecision
    approver: str  # authenticated human username
    approver_roles: list[UserRole] = Field(default_factory=list)
    comment: str | None = None
    decided_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = None  # approved only: execution must start before this
    execution_id: str | None = None  # approved only: the single execution this approval authorizes
    token_id: str | None = None  # jti of the issued authorization token
    consumed_at: datetime | None = None  # when the execution started

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at

    @staticmethod
    def default_expiry(decided_at: datetime, ttl_seconds: int = 900) -> datetime:
        return decided_at + timedelta(seconds=ttl_seconds)


class ApprovalClaims(BaseModel):
    """Claims of the short-lived authorization token (EdDSA JWT) issued on approval."""

    model_config = ConfigDict(extra="forbid")
    iss: str = "aegisops-api"
    aud: str = "aegisops-mcp-mutations"
    sub: str  # "human:<username>"
    jti: str
    iat: int
    exp: int
    incident_id: str
    plan_id: str
    plan_hash: str
    approval_id: str
    execution_id: str


class StepExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    action: ActionType
    target: ResourceRef
    status: StepStatus = StepStatus.PENDING
    idempotency_key: str  # "<execution_id>:<step_id>"
    attempts: int = 0
    intent_recorded_at: datetime | None = None
    applied_at: datetime | None = None
    finished_at: datetime | None = None
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    outcome: str | None = None
    error: str | None = None
    audit_event_id: str | None = None


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check_id: str
    passed: bool | None = None  # None while running / inconclusive
    samples: int = 0
    first_value: float | None = None
    last_value: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    detail: str | None = None


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: VerificationStatus = VerificationStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    window_seconds: int = 600
    shortened_window: bool = False  # True when window < 600s (tests / quick demo) - always reported
    checks: list[CheckResult] = Field(default_factory=list)
    summary: str | None = None


class Execution(Record):
    execution_id: str
    incident_id: str
    plan_id: str
    plan_hash: str
    approval_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    steps: list[StepExecution] = Field(default_factory=list)
    compensation_steps: list[StepExecution] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancel_requested: bool = False
    cancel_reason: str | None = None
    verification: VerificationResult = Field(default_factory=VerificationResult)
    failure_explanation: str | None = None
    version: int = 1


# --------------------------------------------------------------------------- Memory & reports


class MemoryRecord(Record):
    """Long-term, validated, reusable knowledge. Written only from verified outcomes."""

    memory_id: str
    pattern: str  # e.g. "payment 401 spike after secret rotation"
    symptoms: list[str] = Field(default_factory=list)
    fault_type: FaultType
    validated_root_cause: str
    safe_remediation: str
    action_types: list[ActionType] = Field(default_factory=list)
    runbook_refs: list[str] = Field(default_factory=list)
    supporting_incidents: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    applicability: dict[str, str] = Field(default_factory=dict)  # environment, cluster, app version...
    confidence: float = Field(ge=0.0, le=1.0)
    status: MemoryStatus = MemoryStatus.ACTIVE
    invalidated_reason: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    last_validated_at: datetime = Field(default_factory=utcnow)
    times_reused: int = 0

    def embedding_text(self) -> str:
        return " | ".join(
            [self.pattern, *self.symptoms, self.validated_root_cause, self.safe_remediation, *self.services]
        )


class FollowUp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    priority: str = "medium"  # low | medium | high
    owner: str | None = None


class TimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    at: datetime
    event: str


class PostmortemReport(Record):
    report_id: str
    incident_id: str
    title: str
    outcome: IncidentStatus  # resolved | needs_attention | cancelled
    summary: str
    impact: str
    timeline: list[TimelineEntry] = Field(default_factory=list)
    root_cause: str
    contributing_factors: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    actions_taken: list[str] = Field(default_factory=list)
    verification_summary: str
    follow_ups: list[FollowUp] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    memory_candidate_id: str | None = None
    markdown: str
    artifact_uri: str | None = None
    produced_by: AgentRole = AgentRole.POSTMORTEM_WRITER
    model: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- Audit, timeline, runs


class AuditEvent(Record):
    event_id: str  # AUD-<ulid>, time-sortable
    incident_id: str | None = None
    actor: str  # "human:alice" | "agent:kubernetes_diagnostics" | "system:executor"
    actor_type: ActorType
    operation: str  # e.g. "tool.k8s_list_pods", "plan.approve", "mutation.k8s_rollout_undo"
    outcome: AuditOutcome
    timestamp: datetime = Field(default_factory=utcnow)
    details: dict[str, Any] = Field(default_factory=dict)  # redacted
    evidence_refs: list[str] = Field(default_factory=list)


class TimelineEvent(Record):
    """Dashboard-facing event. `event_id` is a ULID-based durable id used as the SSE event id."""

    event_id: str  # EVT-<ulid>; lexicographic order == chronological order
    incident_id: str
    kind: TimelineKind
    timestamp: datetime = Field(default_factory=utcnow)
    actor: str
    title: str
    detail: dict[str, Any] = Field(default_factory=dict)


class LlmUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calls: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0

    def add(self, other: LlmUsage) -> LlmUsage:
        return LlmUsage(
            calls=self.calls + other.calls,
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            estimated_cost_usd=round(self.estimated_cost_usd + other.estimated_cost_usd, 6),
        )


class AgentRun(Record):
    run_id: str
    incident_id: str
    agent: AgentRole
    status: AgentRunStatus = AgentRunStatus.PENDING
    investigation_pass: int = 1
    started_at: datetime | None = None
    finished_at: datetime | None = None
    tool_calls: int = 0
    evidence_ids: list[str] = Field(default_factory=list)
    summary: str | None = None
    error: str | None = None
    model: str | None = None
    run_mode: RunMode | None = None
    usage: LlmUsage = Field(default_factory=LlmUsage)


class OutboxMessage(Record):
    """Durable side-effect intent: published by the outbox relay, retried until acknowledged."""

    outbox_id: str
    topic: str  # "eventbridge.incident" | "sqs.workflow" | "s3.artifact_mirror" | "knowledge.index_memory"
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=utcnow)
    status: str = "pending"  # pending | sent | failed
    attempts: int = 0
    last_error: str | None = None
    sent_at: datetime | None = None
    dedup_key: str | None = None


class WorkflowMessage(BaseModel):
    """Body of messages on the `aegisops-workflow` SQS queue. Messages are notifications only:
    the worker re-reads durable state before acting."""

    model_config = ConfigDict(extra="forbid")
    kind: str  # "investigate" | "resume_after_decision" | "cancel" | "reconcile"
    incident_id: str
    approval_id: str | None = None
    reason: str | None = None
    sent_at: datetime = Field(default_factory=utcnow)


class User(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    display_name: str | None = None
    roles: list[UserRole]

    @property
    def is_approver(self) -> bool:
        return UserRole.APPROVER in self.roles


def fingerprint_text(text: str) -> str:
    """Short stable fingerprint for dedup keys (not for secrets)."""
    return sha256_hex(text)[:16]


__all__ = [
    "ACTION_PARAM_MODELS",
    "ACTION_TARGET_KINDS",
    "AgentRun",
    "AlertRef",
    "Approval",
    "ApprovalClaims",
    "AuditEvent",
    "CheckResult",
    "Diagnosis",
    "Evidence",
    "Execution",
    "Finding",
    "FollowUp",
    "Hypothesis",
    "Incident",
    "IncidentMetrics",
    "LlmUsage",
    "MemoryRecord",
    "OutboxMessage",
    "PlanReview",
    "PlanStep",
    "PolicyCheckResult",
    "PostmortemReport",
    "Prerequisite",
    "PrerequisiteKind",
    "RemediationPlan",
    "StepExecution",
    "TimelineEntry",
    "TimelineEvent",
    "User",
    "VerificationCheck",
    "VerificationResult",
    "VerificationSpec",
    "WorkflowMessage",
    "canonical_json",
    "fingerprint_text",
]
