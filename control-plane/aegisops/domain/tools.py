"""MCP tool catalog: names, typed inputs/outputs, bounds, and server placement.

Every tool returns a `ToolEnvelope` whose `data` validates against the tool's output model.
Tool names use `<group>_<verb>` so they are valid OpenAI function names (^[a-zA-Z0-9_-]{1,64}$).
Diagnostic and mutation tools live on different servers with different credentials.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aegisops.domain.enums import (
    ActionType,
    AgentRole,
    ApprovalDecision,
    ChangeKind,
    FaultType,
    McpServerName,
    ReviewVerdict,
    RiskLevel,
    StepStatus,
    ToolGroup,
    ToolStatus,
    VerificationSignal,
)
from aegisops.domain.models import (
    PlanStep,
    PolicyCheckResult,
    Prerequisite,
    VerificationSpec,
)
from aegisops.domain.resources import (
    ActiveAlert,
    ChangeRecord,
    DbPoolStats,
    DependencyErrorsResult,
    DeploymentRevision,
    DeploymentStatus,
    ErrorRateResult,
    FieldChange,
    K8sEvent,
    LatencyResult,
    LogLine,
    MetricSeries,
    PodDetail,
    PodSummary,
    ProbeResult,
    QueueAttributes,
    QueueConsumerStats,
    ResourceRef,
    RevisionDiff,
    SecretMetadataRaw,
    SeriesPoint,
    SignalSample,
    TraceResult,
    TraceSummary,
)


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolEnvelope(BaseModel):
    """Uniform result wrapper returned by every MCP tool (as structured content)."""

    model_config = ConfigDict(extra="forbid")
    tool: str
    status: ToolStatus
    data: dict[str, Any] | None = None  # output model, dumped in JSON mode
    message: str | None = None  # explanation for non-ok statuses
    observed_at: datetime
    source: str  # "kubernetes-api" | "prometheus" | "loki" | "tempo" | "alertmanager" | "localstack" |
    #               "change-recorder" | "knowledge" | "governance" | "simulation"
    truncated: bool = False
    redactions: int = 0
    duration_ms: float | None = None


Namespace = Field(default="production", max_length=63, pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
K8sName = Field(max_length=253, pattern=r"^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$")
ServiceName = Field(max_length=63, pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


# =========================================================================== Kubernetes (read)


class ListPodsInput(ToolInput):
    namespace: str = Namespace
    label_selector: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=50, ge=1, le=100)


class PodListOutput(ToolOutput):
    namespace: str
    pods: list[PodSummary]


class DescribePodInput(ToolInput):
    namespace: str = Namespace
    name: str = K8sName


class PodLogsInput(ToolInput):
    namespace: str = Namespace
    pod: str = K8sName
    container: str | None = Field(default=None, max_length=63)
    tail_lines: int = Field(default=100, ge=1, le=300)
    previous: bool = False  # logs of the previous (crashed) container instance


class PodLogsOutput(ToolOutput):
    pod: str
    container: str | None
    previous: bool
    lines: list[str]


class GetEventsInput(ToolInput):
    namespace: str = Namespace
    involved_object: str | None = Field(default=None, max_length=253)
    since_minutes: int = Field(default=30, ge=1, le=240)
    limit: int = Field(default=50, ge=1, le=100)


class EventsOutput(ToolOutput):
    events: list[K8sEvent]


class GetDeploymentInput(ToolInput):
    namespace: str = Namespace
    name: str = K8sName


class DeploymentHistoryInput(ToolInput):
    namespace: str = Namespace
    name: str = K8sName
    limit: int = Field(default=5, ge=1, le=10)


class DeploymentHistoryOutput(ToolOutput):
    name: str
    namespace: str
    current_revision: int
    revisions: list[DeploymentRevision]  # newest first
    diffs: list[RevisionDiff]  # consecutive revision diffs, newest first
    last_known_good_revision: int | None = None  # from recorded healthy windows


class ConfigMapDiffInput(ToolInput):
    namespace: str = Namespace
    name: str = K8sName
    baseline: Literal["last_known_good", "previous"] = "last_known_good"


class ConfigMapDiffOutput(ToolOutput):
    name: str
    namespace: str
    current_resource_version: str
    baseline_snapshot_id: str | None
    baseline_captured_at: datetime | None
    baseline_known_good: bool
    changed: list[FieldChange]
    added: list[str]
    removed: list[str]
    unchanged_keys: int
    last_changed_at: datetime | None = None


class ProbeEndpointInput(ToolInput):
    # Only in-cluster service addresses are probed (DNS resolution + TCP connect, 2s timeout).
    url: str = Field(max_length=300, pattern=r"^https?://[a-z0-9.-]+(:\d{1,5})?(/.*)?$")


# =========================================================================== Observability


class ServiceWindowInput(ToolInput):
    service: str = ServiceName
    window_minutes: int = Field(default=15, ge=1, le=120)


class DbPoolInput(ToolInput):
    service: str = ServiceName


class SearchLogsInput(ToolInput):
    service: str = ServiceName
    query: str = Field(default="", max_length=200)  # case-insensitive substring; "" = all
    level: Literal["error", "warning", "info"] | None = None
    since_minutes: int = Field(default=15, ge=1, le=120)
    limit: int = Field(default=50, ge=1, le=100)


class LogSearchOutput(ToolOutput):
    service: str
    lines: list[LogLine]
    total_matched: int


class SearchTracesInput(ToolInput):
    service: str = ServiceName
    since_minutes: int = Field(default=15, ge=1, le=120)
    errors_only: bool = True
    limit: int = Field(default=5, ge=1, le=10)


class TraceSearchOutput(ToolOutput):
    traces: list[TraceSummary]


class GetTraceInput(ToolInput):
    trace_id: str = Field(pattern=r"^[0-9a-f]{16,32}$")


class RecentChangesInput(ToolInput):
    namespace: str | None = Field(default="production", max_length=63)
    since_minutes: int = Field(default=120, ge=1, le=1440)
    kinds: list[ChangeKind] | None = None


class RecentChangesOutput(ToolOutput):
    window_start: datetime
    window_end: datetime
    changes: list[ChangeRecord]  # newest first


class ActiveAlertsInput(ToolInput):
    service: str | None = Field(default=None, max_length=63)


class AlertsOutput(ToolOutput):
    alerts: list[ActiveAlert]


class QueryMetricsInput(ToolInput):
    promql: str = Field(max_length=500)
    range_minutes: int = Field(default=15, ge=1, le=120)
    step_seconds: int = Field(default=30, ge=15, le=600)


class MetricQueryOutput(ToolOutput):
    query: str
    series: list[MetricSeries]  # at most 10 series x 60 points


class GetSignalInput(ToolInput):
    signal: VerificationSignal
    target: str = Field(max_length=130)


# =========================================================================== AWS (read)


class QueueInput(ToolInput):
    queue: str = Field(max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


class QueueMetricsOutput(ToolOutput):
    attributes: QueueAttributes
    consumer: QueueConsumerStats
    dlq_visible_messages: int | None = None
    depth_series: list[SeriesPoint] = Field(default_factory=list)
    depth_trend_per_min: float | None = None  # positive = growing
    unsupported: list[str] = Field(default_factory=list)  # signals the emulator cannot provide


class DlqInspectionOutput(ToolOutput):
    source_queue: str
    dead_letter_queue: str | None
    visible_messages: int | None
    in_flight_messages: int | None
    max_receive_count: int | None
    failure_reasons: dict[str, float] = Field(default_factory=dict)  # consumer-reported, per second
    note: str = "Messages are not received: inspection uses queue attributes and consumer telemetry only."


class SecretInput(ToolInput):
    name: str = Field(max_length=200, pattern=r"^[A-Za-z0-9/_+=.@-]+$")


class SecretMetadataOutput(ToolOutput):
    metadata: SecretMetadataRaw
    known_good_version_id: str | None = None  # AWSCURRENT during the last recorded healthy window
    known_good_since: datetime | None = None
    consumers: list[str] = Field(default_factory=list)  # deployments that load the secret
    rotation_history: list[ChangeRecord] = Field(default_factory=list)
    value_exposed: Literal[False] = False


class DynamoDbTableInput(ToolInput):
    table: str = Field(max_length=255)


class CloudErrorsOutput(ToolOutput):
    service: str
    window_minutes: int
    errors: list[dict[str, Any]]  # {aws_service, operation, error_code, rate_per_s}


# =========================================================================== Knowledge


class RunbookHit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runbook_id: str  # RB-001 ...
    version: str
    title: str
    section: str
    content: str  # chunk text (untrusted data)
    score: float
    content_hash: str
    source_path: str


class RunbookSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runbook_id: str
    version: str
    title: str
    services: list[str]
    fault_types: list[FaultType]
    content_hash: str
    source_path: str


class RunbookDocument(RunbookSummary):
    content: str  # markdown
    sections: list[str]


class SearchRunbooksInput(ToolInput):
    query: str = Field(min_length=2, max_length=500)
    service: str | None = Field(default=None, max_length=63)
    fault_type: FaultType | None = None
    top_k: int = Field(default=5, ge=1, le=8)


class RunbookSearchOutput(ToolOutput):
    hits: list[RunbookHit]
    retrieval: str = "hybrid"  # "hybrid" | "lexical" (vector index unavailable)


class GetRunbookInput(ToolInput):
    runbook_id: str = Field(pattern=r"^RB-\d{3}$")


class SimilarIncidentsInput(ToolInput):
    query: str = Field(min_length=2, max_length=1000)
    service: str | None = Field(default=None, max_length=63)
    top_k: int = Field(default=3, ge=1, le=5)


class MemoryHit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memory_id: str
    pattern: str
    fault_type: FaultType
    validated_root_cause: str
    safe_remediation: str
    runbook_refs: list[str]
    supporting_incidents: list[str]
    confidence: float
    score: float
    match_reasons: list[str] = Field(default_factory=list)


class SimilarIncidentsOutput(ToolOutput):
    matches: list[MemoryHit]


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pattern: str = Field(max_length=300)
    symptoms: list[str] = Field(max_length=10)
    fault_type: FaultType
    validated_root_cause: str = Field(max_length=1000)
    safe_remediation: str = Field(max_length=1000)
    action_types: list[ActionType]
    runbook_refs: list[str]
    services: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


class SaveMemoryInput(ToolInput):
    incident_id: str = Field(pattern=r"^INC-\d+$")
    candidate: MemoryCandidate


class SaveMemoryOutput(ToolOutput):
    memory_id: str
    status: str  # "saved" | "updated_existing"


class StoreArtifactInput(ToolInput):
    incident_id: str = Field(pattern=r"^INC-\d+$")
    name: str = Field(max_length=120, pattern=r"^[A-Za-z0-9._-]+$")
    content_type: Literal["text/markdown", "application/json", "text/plain"] = "text/markdown"
    content: str = Field(max_length=262_144)


class StoreArtifactOutput(ToolOutput):
    uri: str
    content_hash: str


# =========================================================================== Governance


class PlanDraft(BaseModel):
    """What the Root Cause Analyst proposes. Governance assigns ids, revision and hash."""

    model_config = ConfigDict(extra="forbid")
    diagnosis_id: str
    fault_type: FaultType
    title: str = Field(max_length=200)
    summary: str = Field(max_length=2000)
    steps: list[PlanStep] = Field(min_length=1, max_length=6)
    prerequisites: list[Prerequisite] = Field(default_factory=list)
    verification: VerificationSpec
    compensation: list[PlanStep] = Field(default_factory=list, max_length=3)
    risk: RiskLevel
    risk_rationale: str = Field(max_length=1000)
    runbook_refs: list[str] = Field(default_factory=list)
    expected_recovery: str = Field(max_length=1000)


class CreatePlanInput(ToolInput):
    incident_id: str = Field(pattern=r"^INC-\d+$")
    draft: PlanDraft
    supersedes_plan_id: str | None = None


class CreatePlanOutput(ToolOutput):
    plan_id: str
    revision: int
    plan_hash: str
    status: str


class SubmitReviewInput(ToolInput):
    plan_id: str
    plan_hash: str
    verdict: ReviewVerdict
    policy_checks: list[PolicyCheckResult] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list, max_length=10)
    rationale: str = Field(max_length=2000)


class SubmitReviewOutput(ToolOutput):
    review_id: str
    plan_status: str


class RequestApprovalInput(ToolInput):
    incident_id: str = Field(pattern=r"^INC-\d+$")
    plan_id: str


class RequestApprovalOutput(ToolOutput):
    plan_id: str
    plan_status: str
    incident_status: str


class RecordApprovalInput(ToolInput):
    plan_id: str
    plan_hash: str
    decision: ApprovalDecision
    comment: str | None = Field(default=None, max_length=1000)


class RecordApprovalOutput(ToolOutput):
    approval_id: str
    decision: ApprovalDecision


class PermissionsInput(ToolInput):
    role: AgentRole | None = None


class PermissionsOutput(ToolOutput):
    matrix: dict[str, list[str]]  # role -> tool names


# =========================================================================== Mutations


class MutationAuth(BaseModel):
    """Binds a mutation to one approved plan step. Verified server-side on every call."""

    model_config = ConfigDict(extra="forbid")
    execution_id: str
    step_id: str
    approval_token: str = Field(max_length=4096)  # EdDSA JWT issued on human approval


class RolloutRestartInput(ToolInput):
    namespace: str = Namespace
    name: str = K8sName
    auth: MutationAuth


class RolloutUndoInput(ToolInput):
    namespace: str = Namespace
    name: str = K8sName
    to_revision: int = Field(ge=1)
    auth: MutationAuth


class ScaleDeploymentInput(ToolInput):
    namespace: str = Namespace
    name: str = K8sName
    replicas: int = Field(ge=0, le=10)
    auth: MutationAuth


class RestoreConfigMapKeyInput(ToolInput):
    namespace: str = Namespace
    name: str = K8sName
    key: str = Field(max_length=253)
    snapshot_id: str
    auth: MutationAuth


class RestoreSecretVersionInput(ToolInput):
    name: str = Field(max_length=200, pattern=r"^[A-Za-z0-9/_+=.@-]+$")
    version_id: str = Field(max_length=100)
    auth: MutationAuth


class SetQueueRedrivePolicyInput(ToolInput):
    queue: str = Field(max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    max_receive_count: int = Field(ge=1, le=10)
    auth: MutationAuth


class MutationOutput(ToolOutput):
    execution_id: str
    step_id: str
    action: ActionType
    target: ResourceRef
    status: StepStatus  # applied | already_applied | denied | failed | ambiguous
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    message: str
    audit_event_id: str | None = None


# =========================================================================== Catalog


class ToolSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    name: str
    group: ToolGroup
    server: McpServerName
    mutating: bool
    description: str
    input_model: type[ToolInput]
    output_model: type[BaseModel]


def _spec(
    name: str,
    group: ToolGroup,
    server: McpServerName,
    description: str,
    input_model: type[ToolInput],
    output_model: type[BaseModel],
    mutating: bool = False,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        group=group,
        server=server,
        mutating=mutating,
        description=description,
        input_model=input_model,
        output_model=output_model,
    )


K, OB, A, KB, G = (
    ToolGroup.KUBERNETES,
    ToolGroup.OBSERVABILITY,
    ToolGroup.AWS,
    ToolGroup.KNOWLEDGE,
    ToolGroup.GOVERNANCE,
)
DIAG, KNOW, MUT = McpServerName.DIAGNOSTICS, McpServerName.KNOWLEDGE, McpServerName.MUTATIONS

TOOL_CATALOG: dict[str, ToolSpec] = {
    s.name: s
    for s in [
        # ---- kubernetes (read) ----
        _spec(
            "k8s_list_pods",
            K,
            DIAG,
            "List pods with readiness, restarts and waiting reasons.",
            ListPodsInput,
            PodListOutput,
        ),
        _spec(
            "k8s_describe_pod",
            K,
            DIAG,
            "Container states, conditions, redacted env and recent events for one pod.",
            DescribePodInput,
            PodDetail,
        ),
        _spec(
            "k8s_get_pod_logs",
            K,
            DIAG,
            "Bounded, redacted container logs; previous=true reads the crashed instance.",
            PodLogsInput,
            PodLogsOutput,
        ),
        _spec(
            "k8s_get_events",
            K,
            DIAG,
            "Recent Kubernetes events in a namespace, optionally for one object.",
            GetEventsInput,
            EventsOutput,
        ),
        _spec(
            "k8s_get_deployment",
            K,
            DIAG,
            "Deployment replicas, revision, conditions, images and redacted env.",
            GetDeploymentInput,
            DeploymentStatus,
        ),
        _spec(
            "k8s_get_deployment_history",
            K,
            DIAG,
            "Rollout revisions with diffs and the last known-good revision.",
            DeploymentHistoryInput,
            DeploymentHistoryOutput,
        ),
        _spec(
            "k8s_get_configmap_diff",
            K,
            DIAG,
            "Diff a ConfigMap against its last known-good (or previous) recorded snapshot.",
            ConfigMapDiffInput,
            ConfigMapDiffOutput,
        ),
        _spec(
            "k8s_probe_endpoint",
            K,
            DIAG,
            "Predefined connectivity probe: DNS resolution and TCP connect to an in-cluster URL.",
            ProbeEndpointInput,
            ProbeResult,
        ),
        # ---- observability ----
        _spec(
            "obs_get_error_rate",
            OB,
            DIAG,
            "HTTP 5xx ratio, request rate and status breakdown for a service.",
            ServiceWindowInput,
            ErrorRateResult,
        ),
        _spec(
            "obs_get_latency_percentiles",
            OB,
            DIAG,
            "p50/p95/p99 latency for a service with a baseline.",
            ServiceWindowInput,
            LatencyResult,
        ),
        _spec(
            "obs_get_dependency_errors",
            OB,
            DIAG,
            "Outbound call errors by dependency and error type (401, DNS, refused, timeout...).",
            ServiceWindowInput,
            DependencyErrorsResult,
        ),
        _spec(
            "obs_get_db_pool_stats",
            OB,
            DIAG,
            "Connection pool usage, waits and errors plus database connection utilisation.",
            DbPoolInput,
            DbPoolStats,
        ),
        _spec(
            "obs_search_logs",
            OB,
            DIAG,
            "Search a service's structured logs (substring match), redacted and bounded.",
            SearchLogsInput,
            LogSearchOutput,
        ),
        _spec(
            "obs_search_traces",
            OB,
            DIAG,
            "Find recent (error) traces for a service.",
            SearchTracesInput,
            TraceSearchOutput,
        ),
        _spec(
            "obs_get_trace",
            OB,
            DIAG,
            "Spans of one trace with errors and attributes (redacted).",
            GetTraceInput,
            TraceResult,
        ),
        _spec(
            "obs_get_recent_changes",
            OB,
            DIAG,
            "Recorded deployment, ConfigMap, scale and secret-rotation changes.",
            RecentChangesInput,
            RecentChangesOutput,
        ),
        _spec(
            "obs_get_active_alerts",
            OB,
            DIAG,
            "Currently firing alerts from Alertmanager.",
            ActiveAlertsInput,
            AlertsOutput,
        ),
        _spec(
            "obs_query_metrics", OB, DIAG, "Read-only bounded PromQL range query.", QueryMetricsInput, MetricQueryOutput
        ),
        _spec(
            "obs_get_signal", OB, DIAG, "Current value of a named verification signal.", GetSignalInput, SignalSample
        ),
        # ---- aws (read) ----
        _spec(
            "aws_get_queue_metrics",
            A,
            DIAG,
            "SQS depth, in-flight, DLQ depth, redrive policy and consumer throughput/age.",
            QueueInput,
            QueueMetricsOutput,
        ),
        _spec(
            "aws_inspect_dlq",
            A,
            DIAG,
            "Dead-letter queue depth and consumer failure reasons without receiving messages.",
            QueueInput,
            DlqInspectionOutput,
        ),
        _spec(
            "aws_get_secret_metadata",
            A,
            DIAG,
            "Secret versions, stages, rotation history and consumers. Never returns values.",
            SecretInput,
            SecretMetadataOutput,
        ),
        _spec(
            "aws_get_dynamodb_throttling",
            A,
            DIAG,
            "DynamoDB throttling metrics (unsupported by the local emulator; never fabricated).",
            DynamoDbTableInput,
            ToolOutput,
        ),
        _spec(
            "aws_get_cloud_errors",
            A,
            DIAG,
            "AWS SDK errors reported by a service, by AWS service/operation/code.",
            ServiceWindowInput,
            CloudErrorsOutput,
        ),
        # ---- knowledge ----
        _spec(
            "kb_search_runbooks",
            KB,
            KNOW,
            "Hybrid (full-text + vector) runbook search with service/fault filters.",
            SearchRunbooksInput,
            RunbookSearchOutput,
        ),
        _spec("kb_get_runbook", KB, KNOW, "Full versioned runbook by id.", GetRunbookInput, RunbookDocument),
        _spec(
            "kb_retrieve_similar_incidents",
            KB,
            KNOW,
            "Validated long-term memories similar to the current symptoms.",
            SimilarIncidentsInput,
            SimilarIncidentsOutput,
        ),
        _spec(
            "kb_save_incident_memory",
            KB,
            KNOW,
            "Store validated memory from a verified, resolved incident.",
            SaveMemoryInput,
            SaveMemoryOutput,
        ),
        _spec(
            "aws_store_incident_artifact",
            A,
            KNOW,
            "Store a redacted incident artifact (local store, mirrored to S3).",
            StoreArtifactInput,
            StoreArtifactOutput,
        ),
        # ---- governance ----
        _spec(
            "gov_create_remediation_plan",
            G,
            KNOW,
            "Create an immutable, hashed remediation plan revision.",
            CreatePlanInput,
            CreatePlanOutput,
        ),
        _spec(
            "gov_submit_plan_review",
            G,
            KNOW,
            "Record the Change-Plan Reviewer's verdict for an exact plan hash.",
            SubmitReviewInput,
            SubmitReviewOutput,
        ),
        _spec(
            "gov_request_approval",
            G,
            KNOW,
            "Move a reviewed plan to awaiting human approval.",
            RequestApprovalInput,
            RequestApprovalOutput,
        ),
        _spec(
            "gov_record_approval",
            G,
            KNOW,
            "Record a human decision. Always denied for agent identities.",
            RecordApprovalInput,
            RecordApprovalOutput,
        ),
        _spec(
            "gov_get_agent_permissions",
            G,
            KNOW,
            "Permission matrix: which role may call which tool.",
            PermissionsInput,
            PermissionsOutput,
        ),
        # ---- mutations (approval-protected) ----
        _spec(
            "k8s_rollout_restart",
            K,
            MUT,
            "Rolling restart with a stable execution marker (idempotent).",
            RolloutRestartInput,
            MutationOutput,
            True,
        ),
        _spec(
            "k8s_rollout_undo",
            K,
            MUT,
            "Roll a Deployment back to an exact recorded revision.",
            RolloutUndoInput,
            MutationOutput,
            True,
        ),
        _spec(
            "k8s_scale_deployment",
            K,
            MUT,
            "Set Deployment replicas within policy bounds.",
            ScaleDeploymentInput,
            MutationOutput,
            True,
        ),
        _spec(
            "k8s_restore_configmap_key",
            K,
            MUT,
            "Restore exactly one ConfigMap key from a recorded snapshot.",
            RestoreConfigMapKeyInput,
            MutationOutput,
            True,
        ),
        _spec(
            "aws_restore_secret_version",
            A,
            MUT,
            "Move AWSCURRENT back to a recorded version (values never read).",
            RestoreSecretVersionInput,
            MutationOutput,
            True,
        ),
        _spec(
            "aws_set_queue_redrive_policy",
            A,
            MUT,
            "Set a bounded SQS redrive maxReceiveCount to the configured DLQ.",
            SetQueueRedrivePolicyInput,
            MutationOutput,
            True,
        ),
    ]
}

MUTATION_TOOL_FOR_ACTION: dict[ActionType, str] = {
    ActionType.ROLLOUT_RESTART: "k8s_rollout_restart",
    ActionType.ROLLOUT_UNDO: "k8s_rollout_undo",
    ActionType.SCALE_DEPLOYMENT: "k8s_scale_deployment",
    ActionType.RESTORE_CONFIGMAP_KEY: "k8s_restore_configmap_key",
    ActionType.RESTORE_SECRET_VERSION: "aws_restore_secret_version",
    ActionType.SET_QUEUE_REDRIVE_POLICY: "aws_set_queue_redrive_policy",
}


def tools_on_server(server: McpServerName) -> list[ToolSpec]:
    return [spec for spec in TOOL_CATALOG.values() if spec.server == server]
