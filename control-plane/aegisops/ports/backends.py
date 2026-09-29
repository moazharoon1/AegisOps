"""Backend ports behind the MCP tools, the change recorder and recovery verification.

Two families of implementations exist:
* real: `aegisops.mcp.backends.*` (Kubernetes API, Prometheus/Alertmanager, Loki, Tempo, LocalStack)
* simulated: `aegisops.sim.world` (deterministic in-process world driven by a virtual clock)

Backends return domain models and raise:
* `NotFound` for missing resources,
* `DependencyUnavailable` for transient outages / timeouts,
* `NotImplementedError` only for signals a backend genuinely cannot provide (tools map it to
  status "unsupported"; values are never fabricated).
Backends do not redact: the MCP layer redacts every result before it leaves the server.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from aegisops.domain.enums import VerificationSignal
from aegisops.domain.resources import (
    ActiveAlert,
    ConfigMapState,
    DbPoolStats,
    DependencyErrorsResult,
    DeploymentRevision,
    DeploymentStatus,
    ErrorRateResult,
    K8sEvent,
    LatencyResult,
    LogLine,
    MetricSeries,
    PodDetail,
    PodSummary,
    ProbeResult,
    QueueAttributes,
    QueueConsumerStats,
    SecretMetadataRaw,
    SeriesPoint,
    SignalSample,
    TraceResult,
    TraceSummary,
)


class KubernetesReader(Protocol):
    async def list_pods(self, namespace: str, label_selector: str | None = None) -> list[PodSummary]: ...
    async def describe_pod(self, namespace: str, name: str) -> PodDetail: ...
    async def get_pod_logs(
        self, namespace: str, pod: str, container: str | None, tail_lines: int, previous: bool
    ) -> list[str]: ...
    async def list_events(
        self, namespace: str, since: datetime, involved_object: str | None = None
    ) -> list[K8sEvent]: ...
    async def get_deployment(self, namespace: str, name: str) -> DeploymentStatus: ...
    async def list_deployments(self, namespace: str) -> list[DeploymentStatus]: ...
    async def get_deployment_revisions(self, namespace: str, name: str) -> list[DeploymentRevision]:
        """All retained revisions (from ReplicaSets), newest first, env redaction NOT applied."""
        ...

    async def get_configmap(self, namespace: str, name: str) -> ConfigMapState: ...
    async def list_configmaps(self, namespace: str) -> list[ConfigMapState]: ...
    async def probe_endpoint(self, host: str, port: int, timeout_s: float = 2.0) -> ProbeResult: ...


class KubernetesWriter(Protocol):
    """Raw mutations. Only the mutation MCP server holds an implementation, and only after the
    approval guard has passed. Each method returns the observed state after the change."""

    async def restart_deployment(self, namespace: str, name: str, marker: str) -> DeploymentStatus:
        """Set pod-template annotation aegisops.io/restartedAt=<marker>. Idempotent: if the
        annotation already equals `marker`, no new rollout is triggered."""
        ...

    async def rollback_deployment(self, namespace: str, name: str, to_revision: int) -> DeploymentStatus:
        """Copy the pod template of the ReplicaSet at `to_revision` (kubectl rollout undo semantics)."""
        ...

    async def scale_deployment(self, namespace: str, name: str, replicas: int) -> DeploymentStatus: ...
    async def set_configmap_key(self, namespace: str, name: str, key: str, value: str) -> ConfigMapState: ...


class ObservabilityBackend(Protocol):
    async def error_rate(self, service: str, window_minutes: int) -> ErrorRateResult: ...
    async def latency(self, service: str, window_minutes: int) -> LatencyResult: ...
    async def dependency_errors(self, service: str, window_minutes: int) -> DependencyErrorsResult: ...
    async def db_pool_stats(self, service: str) -> DbPoolStats: ...
    async def queue_consumer_stats(self, queue: str) -> QueueConsumerStats: ...
    async def queue_depth_series(self, queue: str, window_minutes: int) -> list[SeriesPoint]: ...
    async def aws_sdk_errors(self, service: str, window_minutes: int) -> list[dict[str, object]]: ...
    async def search_logs(
        self, service: str, query: str, level: str | None, since_minutes: int, limit: int
    ) -> tuple[list[LogLine], int]:
        """Returns (lines newest-first, total matched)."""
        ...

    async def search_traces(
        self, service: str, since_minutes: int, errors_only: bool, limit: int
    ) -> list[TraceSummary]: ...
    async def get_trace(self, trace_id: str) -> TraceResult: ...
    async def active_alerts(self) -> list[ActiveAlert]: ...
    async def query_range(self, promql: str, range_minutes: int, step_seconds: int) -> list[MetricSeries]: ...
    async def signal(self, signal: VerificationSignal, target: str) -> SignalSample: ...


class AwsBackend(Protocol):
    async def queue_attributes(self, queue: str) -> QueueAttributes: ...
    async def secret_metadata(self, name: str) -> SecretMetadataRaw: ...
    async def list_secrets(self, prefix: str = "") -> list[str]: ...
    async def restore_secret_version(self, name: str, version_id: str) -> SecretMetadataRaw:
        """Move AWSCURRENT to `version_id` (previous current becomes AWSPREVIOUS). Never reads values."""
        ...

    async def set_redrive_policy(
        self, queue: str, dead_letter_queue: str, max_receive_count: int
    ) -> QueueAttributes: ...
    async def put_object(self, bucket: str, key: str, body: bytes, content_type: str) -> str: ...
