"""Persistence ports. DynamoDB Local implementations live in `aegisops.storage.dynamodb`;
in-memory implementations with identical semantics live in `aegisops.storage.inmemory`.

Semantics every implementation must honour (covered by tests/storage/contract tests):
* `create*` methods are conditional: they raise `ConflictError` if the key already exists.
* `update*` methods with `expected_version` raise `ConflictError` on mismatch and store
  `version = expected_version + 1`.
* Listing methods return newest-first unless stated otherwise; timeline/audit lists are
  chronological (ascending ids) because ids are ULID-based.
* Returned models are copies: mutating them never changes stored state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from aegisops.domain.enums import ExecutionStatus, IncidentStatus, MemoryStatus, PlanStatus
from aegisops.domain.models import (
    AgentRun,
    Approval,
    AuditEvent,
    Diagnosis,
    Evidence,
    Execution,
    Finding,
    Incident,
    MemoryRecord,
    OutboxMessage,
    PlanReview,
    PostmortemReport,
    RemediationPlan,
    TimelineEvent,
)
from aegisops.domain.resources import ChangeRecord, ConfigSnapshot, ResourceRef


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


class IncidentRepository(Protocol):
    async def next_incident_number(self) -> int:
        """Atomic counter used for INC-<n> identifiers (starts at 1001)."""
        ...

    async def create(self, incident: Incident) -> Incident: ...
    async def get(self, incident_id: str) -> Incident | None: ...
    async def update(self, incident: Incident, expected_version: int) -> Incident: ...
    async def list(
        self, status: IncidentStatus | None = None, limit: int = 50, cursor: str | None = None
    ) -> Page[Incident]: ...
    async def list_active(self) -> list[Incident]: ...


class DedupRepository(Protocol):
    async def claim(self, key: str, incident_id: str, ttl_seconds: int) -> str | None:
        """Record `key -> incident_id` if absent (or expired). Returns the existing incident id
        when the key is already claimed, otherwise None (the caller owns the new claim)."""
        ...


class TimelineRepository(Protocol):
    async def append(self, event: TimelineEvent) -> TimelineEvent: ...
    async def list(
        self, incident_id: str, after_event_id: str | None = None, limit: int = 500
    ) -> list[TimelineEvent]: ...
    async def list_global(self, after_event_id: str | None = None, limit: int = 200) -> list[TimelineEvent]:
        """Events across all incidents, ascending by event id (drives the live incident list)."""
        ...


class EvidenceRepository(Protocol):
    async def put(self, evidence: Evidence) -> Evidence: ...
    async def get(self, incident_id: str, evidence_id: str) -> Evidence | None: ...
    async def list(self, incident_id: str) -> list[Evidence]: ...


class FindingRepository(Protocol):
    async def put(self, finding: Finding) -> Finding: ...
    async def list(self, incident_id: str) -> list[Finding]: ...


class DiagnosisRepository(Protocol):
    async def put(self, diagnosis: Diagnosis) -> Diagnosis: ...
    async def get(self, incident_id: str, diagnosis_id: str) -> Diagnosis | None: ...
    async def latest(self, incident_id: str) -> Diagnosis | None: ...
    async def list(self, incident_id: str) -> list[Diagnosis]: ...


class PlanRepository(Protocol):
    async def create(self, plan: RemediationPlan) -> RemediationPlan:
        """Plan revisions are immutable: content never changes after create (hash-checked)."""
        ...

    async def get(self, plan_id: str) -> RemediationPlan | None: ...
    async def list_for_incident(self, incident_id: str) -> list[RemediationPlan]: ...
    async def set_status(
        self, plan_id: str, status: PlanStatus, expected_status: PlanStatus | None = None
    ) -> RemediationPlan:
        """Only `status` (and `review` via attach_review) may change after creation."""
        ...

    async def attach_review(self, plan_id: str, review: PlanReview) -> RemediationPlan: ...


class ApprovalRepository(Protocol):
    async def create(self, approval: Approval) -> Approval: ...
    async def get(self, approval_id: str) -> Approval | None: ...
    async def list_for_plan(self, plan_id: str) -> list[Approval]: ...
    async def list_for_incident(self, incident_id: str) -> list[Approval]: ...
    async def mark_consumed(self, approval_id: str, execution_id: str, consumed_at: datetime) -> Approval:
        """Conditional: succeeds once per approval, and only for its bound execution id."""
        ...

    async def put_grant(self, approval_id: str, token: str, expires_at: datetime) -> None:
        """Store the short-lived authorization token for the executor (TTL = approval expiry).
        The token is never returned by the API or written to logs/timeline/audit."""
        ...

    async def get_grant(self, approval_id: str) -> str | None:
        """Returns the token if present and unexpired."""
        ...


class ExecutionRepository(Protocol):
    async def create(self, execution: Execution) -> Execution: ...
    async def get(self, execution_id: str) -> Execution | None: ...
    async def update(self, execution: Execution, expected_version: int) -> Execution: ...
    async def list_for_incident(self, incident_id: str) -> list[Execution]: ...
    async def list_by_status(self, status: ExecutionStatus) -> list[Execution]: ...


class AuditRepository(Protocol):
    async def append(self, event: AuditEvent) -> AuditEvent:
        """Must raise DependencyUnavailable if the event cannot be durably stored: mutations
        are blocked when audit storage is unavailable."""
        ...

    async def list(self, incident_id: str | None = None, limit: int = 500) -> list[AuditEvent]: ...


class MemoryRepository(Protocol):
    async def put(self, record: MemoryRecord) -> MemoryRecord: ...
    async def get(self, memory_id: str) -> MemoryRecord | None: ...
    async def list(self, status: MemoryStatus | None = MemoryStatus.ACTIVE) -> list[MemoryRecord]: ...
    async def invalidate(self, memory_id: str, reason: str) -> MemoryRecord: ...


class LockRepository(Protocol):
    async def acquire(self, resource_key: str, owner: str, ttl_seconds: int) -> bool:
        """True if acquired (or already held by `owner`); False if held by someone else and unexpired."""
        ...

    async def release(self, resource_key: str, owner: str) -> None: ...
    async def holder(self, resource_key: str) -> str | None: ...


class OutboxRepository(Protocol):
    async def add(self, message: OutboxMessage) -> OutboxMessage:
        """Idempotent on `dedup_key` when provided."""
        ...

    async def list_pending(self, limit: int = 50) -> list[OutboxMessage]: ...
    async def mark_sent(self, outbox_id: str) -> None: ...
    async def mark_failed(self, outbox_id: str, error: str) -> None: ...


class ChangeRepository(Protocol):
    async def record_change(self, change: ChangeRecord) -> ChangeRecord: ...
    async def list_changes(
        self, since: datetime, namespace: str | None = None, resource: ResourceRef | None = None
    ) -> list[ChangeRecord]: ...
    async def put_snapshot(self, snapshot: ConfigSnapshot) -> ConfigSnapshot: ...
    async def get_snapshot(self, snapshot_id: str) -> ConfigSnapshot | None: ...
    async def latest_snapshot(self, resource: ResourceRef, known_good_only: bool = False) -> ConfigSnapshot | None: ...
    async def list_snapshots(self, resource: ResourceRef, limit: int = 20) -> list[ConfigSnapshot]: ...


class MutationJournalEntry(BaseModel):
    """Server-side idempotency record kept by the mutation MCP server (the executor owns `Execution`)."""

    idempotency_key: str  # "<execution_id>:<step_id>"
    execution_id: str
    step_id: str
    action: str
    target_key: str
    status: str  # intent | applied | failed | denied
    before_state: dict | None = None
    after_state: dict | None = None
    message: str | None = None
    audit_event_id: str | None = None
    recorded_at: datetime
    updated_at: datetime


class MutationJournalRepository(Protocol):
    async def record_intent(self, entry: MutationJournalEntry) -> tuple[MutationJournalEntry, bool]:
        """Conditional insert. Returns (entry, created). If the key exists, returns the stored entry
        and False without overwriting it."""
        ...

    async def get(self, idempotency_key: str) -> MutationJournalEntry | None: ...

    async def complete(
        self,
        idempotency_key: str,
        status: str,
        *,
        after_state: dict | None,
        message: str,
        audit_event_id: str | None,
        updated_at: datetime,
    ) -> MutationJournalEntry: ...


class ReportRepository(Protocol):
    async def put(self, report: PostmortemReport) -> PostmortemReport: ...
    async def get(self, incident_id: str) -> PostmortemReport | None: ...
    async def list(self, limit: int = 50) -> list[PostmortemReport]: ...


class AgentRunRepository(Protocol):
    async def put(self, run: AgentRun) -> AgentRun: ...
    async def list(self, incident_id: str) -> list[AgentRun]: ...


class ArtifactStore(Protocol):
    """Durable local artifact storage (authoritative) mirrored to S3 via the outbox.
    URIs look like `artifact://incidents/INC-1042/EV-01J....json`."""

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> str: ...
    async def put_json(self, key: str, value: object) -> str: ...
    async def get_bytes(self, uri: str) -> bytes: ...
    async def exists(self, uri: str) -> bool: ...
    async def list_keys(self, prefix: str) -> list[str]: ...


class Repositories(Protocol):
    """Aggregate handed to services (dependency injection)."""

    incidents: IncidentRepository
    dedup: DedupRepository
    timeline: TimelineRepository
    evidence: EvidenceRepository
    findings: FindingRepository
    diagnoses: DiagnosisRepository
    plans: PlanRepository
    approvals: ApprovalRepository
    executions: ExecutionRepository
    audit: AuditRepository
    memory: MemoryRepository
    locks: LockRepository
    outbox: OutboxRepository
    changes: ChangeRepository
    reports: ReportRepository
    agent_runs: AgentRunRepository
    mutation_journal: MutationJournalRepository
    artifacts: ArtifactStore
