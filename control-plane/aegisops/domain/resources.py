"""Operational data shapes returned by backends and exposed (bounded, redacted) through MCP tools.

Both the real backends (Kubernetes API, Prometheus, Loki, Tempo, Alertmanager, LocalStack) and the
in-process simulated world produce exactly these models, so agents see identical evidence shapes in
both environments. Secret *values* have no field anywhere in this module by design.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aegisops.domain.enums import ChangeKind, ResourceKind


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, use_enum_values=False)


class ResourceRef(Model):
    kind: ResourceKind
    name: str
    namespace: str | None = None  # Kubernetes namespace; None for AWS resources

    @property
    def key(self) -> str:
        return f"{self.kind.value}/{self.namespace or '-'}/{self.name}"

    def __str__(self) -> str:
        return self.key


# --------------------------------------------------------------------------- Kubernetes


class PodSummary(Model):
    name: str
    namespace: str
    app: str | None = None  # value of the `app` label
    phase: str  # Pending | Running | Succeeded | Failed | Unknown
    ready: bool
    ready_containers: str  # e.g. "1/1"
    restarts: int = 0
    waiting_reason: str | None = None  # e.g. CrashLoopBackOff, ImagePullBackOff, ErrImagePull
    last_termination_reason: str | None = None  # e.g. Error, OOMKilled
    last_exit_code: int | None = None
    image: str | None = None
    pod_template_hash: str | None = None
    node: str | None = None
    started_at: datetime | None = None


class ContainerStatus(Model):
    name: str
    image: str
    ready: bool
    restart_count: int = 0
    state: str  # running | waiting | terminated
    state_reason: str | None = None
    state_message: str | None = None
    last_state_reason: str | None = None
    last_exit_code: int | None = None
    last_finished_at: datetime | None = None


class K8sCondition(Model):
    type: str
    status: str
    reason: str | None = None
    message: str | None = None
    last_transition_at: datetime | None = None


class K8sEvent(Model):
    type: str  # Normal | Warning
    reason: str
    message: str
    object_kind: str
    object_name: str
    count: int = 1
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class PodDetail(Model):
    summary: PodSummary
    containers: list[ContainerStatus] = Field(default_factory=list)
    conditions: list[K8sCondition] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)  # literal env values (redacted); refs shown as <ref:...>
    env_from: list[str] = Field(default_factory=list)  # ConfigMap names
    resources: dict[str, dict[str, str]] = Field(default_factory=dict)  # requests/limits
    events: list[K8sEvent] = Field(default_factory=list)


class DeploymentStatus(Model):
    name: str
    namespace: str
    revision: int
    replicas: int  # desired
    ready_replicas: int = 0
    available_replicas: int = 0
    unavailable_replicas: int = 0
    updated_replicas: int = 0
    images: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)  # redacted literal env of the pod template
    env_from: list[str] = Field(default_factory=list)
    annotations: dict[str, str] = Field(default_factory=dict)  # only aegisops.io/* and change-cause
    conditions: list[K8sCondition] = Field(default_factory=list)
    strategy: str = "RollingUpdate"
    generation: int | None = None
    observed_generation: int | None = None
    template_hash: str | None = None  # content hash of the pod template (for prerequisites)


class DeploymentRevision(Model):
    revision: int
    replicaset: str
    created_at: datetime | None = None
    images: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)  # redacted
    change_cause: str | None = None
    pod_template_hash: str | None = None
    is_current: bool = False


class FieldChange(Model):
    field: str  # e.g. "env.PAYMENT_RETRY_POLICY", "image[checkout]", "data.PAYMENT_SERVICE_URL"
    before: str | None = None
    after: str | None = None


class RevisionDiff(Model):
    from_revision: int
    to_revision: int
    changes: list[FieldChange] = Field(default_factory=list)


class ConfigMapState(Model):
    name: str
    namespace: str
    resource_version: str
    data: dict[str, str] = Field(default_factory=dict)
    last_modified: datetime | None = None


class ProbeResult(Model):
    host: str
    port: int
    dns_resolved: bool
    addresses: list[str] = Field(default_factory=list)
    dns_error: str | None = None
    tcp_connected: bool = False
    tcp_error: str | None = None  # e.g. "connection refused", "timeout"
    latency_ms: float | None = None
    probed_at: datetime | None = None


# --------------------------------------------------------------------------- Observability


class SeriesPoint(Model):
    ts: datetime
    value: float


class ErrorRateResult(Model):
    service: str
    window_minutes: int
    request_rate_rps: float
    error_rate: float  # 5xx ratio 0..1
    by_status: dict[str, float] = Field(default_factory=dict)  # status code -> rps
    baseline_error_rate: float | None = None  # same-length window immediately before
    series: list[SeriesPoint] = Field(default_factory=list)  # error ratio over time (<=30 points)


class LatencyResult(Model):
    service: str
    window_minutes: int
    p50_ms: float | None = None
    p95_ms: float | None = None
    p99_ms: float | None = None
    baseline_p95_ms: float | None = None
    series: list[SeriesPoint] = Field(default_factory=list)  # p95 over time


class DependencyStats(Model):
    peer: str  # downstream service or external dependency name
    request_rate_rps: float
    error_rate: float  # ratio 0..1
    errors_by_type: dict[str, float] = Field(default_factory=dict)  # error_type -> errors/s (see contracts)


class DependencyErrorsResult(Model):
    service: str
    window_minutes: int
    dependencies: list[DependencyStats] = Field(default_factory=list)


class DbPoolStats(Model):
    service: str
    pods: int
    pool_max_per_pod: int | None = None
    pool_in_use: float | None = None  # summed across pods
    pool_open: float | None = None
    acquire_wait_p95_ms: float | None = None
    connection_errors_per_s: float = 0.0
    errors_by_kind: dict[str, float] = Field(default_factory=dict)  # too_many_connections | timeout | other
    db_connections_used: float | None = None  # from postgres_exporter
    db_max_connections: float | None = None
    db_utilization: float | None = None  # used / max


class QueueConsumerStats(Model):
    queue: str
    consumer_service: str | None = None
    throughput_per_s: float | None = None  # successfully processed messages / s
    failure_rate_per_s: float | None = None
    publish_rate_per_s: float | None = None
    busy_ratio: float | None = None  # in-flight handlers / concurrency (0..1)
    concurrency_per_pod: float | None = None
    processing_p95_s: float | None = None
    message_age_p95_s: float | None = None  # age at receipt, observed by consumers
    failure_reasons: dict[str, float] = Field(default_factory=dict)  # reason -> failures/s


class LogLine(Model):
    ts: datetime
    level: str
    service: str
    pod: str | None = None
    message: str
    event: str | None = None
    trace_id: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)


class TraceSpan(Model):
    span_id: str
    parent_span_id: str | None = None
    service: str
    name: str
    start: datetime | None = None
    duration_ms: float
    status: str  # ok | error | unset
    error_message: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)


class TraceResult(Model):
    trace_id: str
    root_service: str | None = None
    duration_ms: float | None = None
    spans: list[TraceSpan] = Field(default_factory=list)


class TraceSummary(Model):
    trace_id: str
    root_service: str
    root_name: str
    start: datetime
    duration_ms: float
    error: bool
    error_message: str | None = None


class ActiveAlert(Model):
    name: str
    severity: str  # critical | warning | info
    service: str | None = None
    namespace: str | None = None
    summary: str | None = None
    starts_at: datetime
    labels: dict[str, str] = Field(default_factory=dict)
    fingerprint: str


class MetricSeries(Model):
    labels: dict[str, str]
    points: list[SeriesPoint]


class SignalSample(Model):
    """One observation of a named verification signal."""

    signal: str
    target: str
    value: float | None  # None = no data (stale / missing telemetry)
    observed_at: datetime
    request_rate_rps: float | None = None  # traffic context for sufficiency checks


# --------------------------------------------------------------------------- AWS (emulated)


class QueueAttributes(Model):
    queue: str
    url: str | None = None
    arn: str | None = None
    visible_messages: int
    in_flight_messages: int
    delayed_messages: int = 0
    visibility_timeout_s: int | None = None
    redrive_max_receive_count: int | None = None
    dead_letter_queue: str | None = None
    created_at: datetime | None = None


class SecretVersionInfo(Model):
    version_id: str
    stages: list[str] = Field(default_factory=list)  # AWSCURRENT, AWSPREVIOUS, ...
    created_at: datetime | None = None


class SecretMetadataRaw(Model):
    """Everything about a secret except its value. There is intentionally no value field."""

    name: str
    arn: str | None = None
    description: str | None = None
    current_version_id: str | None = None
    previous_version_id: str | None = None
    versions: list[SecretVersionInfo] = Field(default_factory=list)
    last_changed_at: datetime | None = None
    rotation_enabled: bool = False


# --------------------------------------------------------------------------- Change history


class ChangeRecord(Model):
    change_id: str
    kind: ChangeKind
    resource: ResourceRef
    observed_at: datetime
    from_version: str | None = None  # revision / resourceVersion / secret version id
    to_version: str | None = None
    summary: str
    changes: list[FieldChange] = Field(default_factory=list)  # secret values never appear
    actor: str | None = None


class ConfigSnapshot(Model):
    """Recorded state of a resource. Deployment snapshots hold a template summary; secret
    snapshots hold only version stages. `known_good` is set after a healthy window."""

    snapshot_id: str
    resource: ResourceRef
    captured_at: datetime
    version: str
    data: dict[str, str] = Field(default_factory=dict)
    content_hash: str
    known_good: bool = False
    known_good_since: datetime | None = None
