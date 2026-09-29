"""Enumerations shared by every AegisOps component.

These values are persisted and exposed through the API, so treat renames as schema changes.
"""

from __future__ import annotations

from enum import StrEnum


class AgentRole(StrEnum):
    INCIDENT_COMMANDER = "incident_commander"
    SIGNAL_CORRELATION = "signal_correlation"
    KUBERNETES_DIAGNOSTICS = "kubernetes_diagnostics"
    CLOUD_RESOURCE = "cloud_resource"
    RUNBOOK_INTELLIGENCE = "runbook_intelligence"
    ROOT_CAUSE_ANALYST = "root_cause_analyst"
    CHANGE_PLAN_REVIEWER = "change_plan_reviewer"
    REMEDIATION_EXECUTOR = "remediation_executor"
    POSTMORTEM_WRITER = "postmortem_writer"

    @property
    def display_name(self) -> str:
        return AGENT_DISPLAY_NAMES[self]


AGENT_DISPLAY_NAMES: dict[AgentRole, str] = {
    AgentRole.INCIDENT_COMMANDER: "Incident Commander",
    AgentRole.SIGNAL_CORRELATION: "Signal Correlation Agent",
    AgentRole.KUBERNETES_DIAGNOSTICS: "Kubernetes Diagnostics Agent",
    AgentRole.CLOUD_RESOURCE: "Cloud Resource Agent",
    AgentRole.RUNBOOK_INTELLIGENCE: "Runbook Intelligence Agent",
    AgentRole.ROOT_CAUSE_ANALYST: "Root Cause Analyst",
    AgentRole.CHANGE_PLAN_REVIEWER: "Change-Plan Reviewer",
    AgentRole.REMEDIATION_EXECUTOR: "Remediation Executor",
    AgentRole.POSTMORTEM_WRITER: "Postmortem Writer",
}

# Specialists dispatched in parallel by the Incident Commander.
INVESTIGATION_SPECIALISTS: tuple[AgentRole, ...] = (
    AgentRole.SIGNAL_CORRELATION,
    AgentRole.KUBERNETES_DIAGNOSTICS,
    AgentRole.CLOUD_RESOURCE,
    AgentRole.RUNBOOK_INTELLIGENCE,
)


class IncidentStatus(StrEnum):
    RECEIVED = "received"
    INVESTIGATING = "investigating"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    NEEDS_ATTENTION = "needs_attention"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (IncidentStatus.RESOLVED, IncidentStatus.CANCELLED)

    @property
    def is_active(self) -> bool:
        return not self.is_terminal


class Severity(StrEnum):
    SEV1 = "SEV-1"
    SEV2 = "SEV-2"
    SEV3 = "SEV-3"
    SEV4 = "SEV-4"


class IncidentSource(StrEnum):
    ALERTMANAGER = "alertmanager"
    MANUAL = "manual"
    HEALTH_CHECK = "health_check"


class FaultType(StrEnum):
    """Diagnosis categories. Agents choose one; evaluation compares against the hidden expected value."""

    BAD_DEPLOYMENT = "bad_deployment"  # new revision crashes (CrashLoopBackOff)
    IMAGE_PULL_FAILURE = "image_pull_failure"  # new revision cannot pull its image
    QUEUE_CONSUMER_CAPACITY = "queue_consumer_capacity"  # healthy consumers cannot keep up
    QUEUE_CONSUMER_DOWN = "queue_consumer_down"  # consumers absent or crashing
    POISON_MESSAGES = "poison_messages"  # specific messages fail repeatedly
    INVALID_SECRET = "invalid_secret"  # active credential version is invalid
    DB_CONNECTION_EXHAUSTION = "db_connection_exhaustion"  # pool demand exceeds DB connection budget
    BAD_CONFIGURATION = "bad_configuration"  # ConfigMap change broke the service
    NO_FAULT = "no_fault"  # healthy / transient / misleading signal; no action warranted
    UNKNOWN = "unknown"  # insufficient evidence


class ActionType(StrEnum):
    """Every mutation AegisOps can ever perform. Anything else is impossible by construction."""

    ROLLOUT_UNDO = "k8s_rollout_undo"
    ROLLOUT_RESTART = "k8s_rollout_restart"
    SCALE_DEPLOYMENT = "k8s_scale_deployment"
    RESTORE_CONFIGMAP_KEY = "k8s_restore_configmap_key"
    RESTORE_SECRET_VERSION = "aws_restore_secret_version"
    SET_QUEUE_REDRIVE_POLICY = "aws_set_queue_redrive_policy"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PlanStatus(StrEnum):
    PENDING_REVIEW = "pending_review"  # proposed by the Root Cause Analyst
    REJECTED_BY_REVIEWER = "rejected_by_reviewer"  # Change-Plan Reviewer or policy refused it
    AWAITING_APPROVAL = "awaiting_approval"  # reviewed; waiting for a human
    APPROVED = "approved"  # human approved; execution may start before the approval expires
    REJECTED = "rejected"  # human rejected
    REVISION_REQUESTED = "revision_requested"  # human asked for a new revision
    SUPERSEDED = "superseded"  # a newer revision replaced it
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"  # approval window lapsed or prerequisites invalidated
    CANCELLED = "cancelled"


class ReviewVerdict(StrEnum):
    RECOMMEND = "recommend"  # plan may be shown to a human for approval
    REJECT = "reject"  # unsupported, excessive, or poorly verified


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"  # all steps applied (verification tracked separately)
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_RECONCILIATION = "needs_reconciliation"  # an outcome was ambiguous; observe before retrying


class StepStatus(StrEnum):
    PENDING = "pending"
    INTENT_RECORDED = "intent_recorded"
    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"  # idempotent replay found the change in place
    FAILED = "failed"
    DENIED = "denied"  # authorization or prerequisite check refused it
    AMBIGUOUS = "ambiguous"  # request sent, outcome unknown
    SKIPPED = "skipped"


class VerificationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"  # e.g. insufficient traffic or stale telemetry


class RunMode(StrEnum):
    """How agent reasoning is produced. Always shown in the UI and recorded with every result."""

    LIVE = "live"  # OpenAI Responses API
    RECORD = "record"  # live, and responses are saved as replay fixtures
    REPLAY = "replay"  # strict playback of recorded fixtures; unexpected requests fail
    DETERMINISTIC = "deterministic"  # offline rule-based reasoning; no model calls


class EnvironmentKind(StrEnum):
    CLUSTER = "cluster"  # real Kind cluster + emulators
    SIMULATION = "simulation"  # in-process simulated world (tests and fast evaluation)


class UserRole(StrEnum):
    VIEWER = "viewer"
    APPROVER = "approver"


class ActorType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILED = "failed"


class ToolGroup(StrEnum):
    KUBERNETES = "kubernetes"
    OBSERVABILITY = "observability"
    AWS = "aws"
    KNOWLEDGE = "knowledge"
    GOVERNANCE = "governance"


class McpServerName(StrEnum):
    """Separate deployments with separate credentials and Kubernetes service accounts."""

    DIAGNOSTICS = "diagnostics"  # read-only kubernetes / observability / aws metadata
    KNOWLEDGE = "knowledge"  # runbooks, memory, plans, reviews, artifacts (control-plane data)
    MUTATIONS = "mutations"  # approval-protected changes to the application environment

    @property
    def audience(self) -> str:
        return f"aegisops-mcp-{self.value}"


class ToolStatus(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"  # dependency down / timeout (transient)
    UNSUPPORTED = "unsupported"  # emulator cannot provide this signal; never fabricated
    DENIED = "denied"  # caller lacks permission or authorization failed
    INVALID = "invalid"  # arguments failed validation or bounds
    NOT_FOUND = "not_found"
    ERROR = "error"


class ResourceKind(StrEnum):
    DEPLOYMENT = "Deployment"
    CONFIGMAP = "ConfigMap"
    POD = "Pod"
    SERVICE = "Service"
    SECRET = "AwsSecret"  # AWS Secrets Manager secret (never a Kubernetes Secret)
    QUEUE = "SqsQueue"
    DATABASE = "Database"


class ChangeKind(StrEnum):
    DEPLOYMENT_ROLLOUT = "deployment_rollout"  # pod template changed (new revision)
    DEPLOYMENT_SCALE = "deployment_scale"
    CONFIGMAP_UPDATE = "configmap_update"
    SECRET_ROTATION = "secret_rotation"  # AWSCURRENT moved to another version
    ENVIRONMENT_RECREATED = "environment_recreated"  # emulator / cluster state was rebuilt


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    INVALIDATED = "invalidated"


class HypothesisStatus(StrEnum):
    SUPPORTED = "supported"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


class AgentRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class VerificationSignal(StrEnum):
    """Named, bounded recovery signals. Targets are service, deployment, or queue names."""

    ERROR_RATE = "error_rate"  # ratio 0..1 of 5xx responses (service)
    P95_LATENCY_MS = "p95_latency_ms"  # service
    READY_REPLICAS = "ready_replicas"  # deployment
    UNAVAILABLE_REPLICAS = "unavailable_replicas"  # deployment
    QUEUE_DEPTH = "queue_depth"  # queue visible messages
    MESSAGE_AGE_P95_S = "message_age_p95_s"  # queue
    DEPENDENCY_ERROR_RATE = "dependency_error_rate"  # target "service->peer"; ratio 0..1
    DB_CONNECTION_ERROR_RATE = "db_connection_error_rate"  # errors/s (service)
    DB_CONNECTION_UTILIZATION = "db_connection_utilization"  # used/max ratio 0..1 (database)
    REQUEST_RATE = "request_rate"  # rps (service) - traffic sufficiency


class Comparator(StrEnum):
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    DECREASING = "decreasing"  # first-to-last trend must fall by at least `threshold` fraction


class TimelineKind(StrEnum):
    INCIDENT_CREATED = "incident.created"
    INCIDENT_STATUS_CHANGED = "incident.status_changed"
    ALERT_ATTACHED = "incident.alert_attached"
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    TOOL_CALLED = "tool.called"
    EVIDENCE_RECORDED = "evidence.recorded"
    FINDING_RECORDED = "finding.recorded"
    MEMORY_MATCHED = "memory.matched"
    RUNBOOK_MATCHED = "runbook.matched"
    DIAGNOSIS_COMPLETED = "diagnosis.completed"
    PLAN_PROPOSED = "plan.proposed"
    PLAN_REVIEWED = "plan.reviewed"
    PLAN_SUPERSEDED = "plan.superseded"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DECIDED = "approval.decided"
    EXECUTION_STARTED = "execution.started"
    EXECUTION_STEP = "execution.step"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
    EXECUTION_CANCELLED = "execution.cancelled"
    VERIFICATION_STARTED = "verification.started"
    VERIFICATION_PROGRESS = "verification.progress"
    VERIFICATION_COMPLETED = "verification.completed"
    COMPACTION_PERFORMED = "compaction.performed"
    BUDGET_EXHAUSTED = "budget.exhausted"
    REPORT_PUBLISHED = "report.published"
    MEMORY_SAVED = "memory.saved"
    NOTE = "note"
