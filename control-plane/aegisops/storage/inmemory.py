"""In-memory repositories with the same semantics as the DynamoDB implementations.

Used by unit tests, the in-process simulation, and fast evaluation. Every read returns a deep
copy so callers cannot mutate stored state; conditional writes raise `ConflictError`.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from aegisops.domain.enums import ExecutionStatus, IncidentStatus, MemoryStatus, PlanStatus
from aegisops.domain.errors import ConflictError, DependencyUnavailable, NotFound
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
from aegisops.ports.clock import SystemClock
from aegisops.ports.repositories import MutationJournalEntry, Page
from aegisops.ports.services import Clock


def _copy[M](model: M) -> M:
    return model.model_copy(deep=True)  # type: ignore[attr-defined]


class InMemoryIncidentRepository:
    def __init__(self) -> None:
        self._items: dict[str, Incident] = {}
        self._counter = 1000
        self._lock = asyncio.Lock()

    async def next_incident_number(self) -> int:
        async with self._lock:
            self._counter += 1
            return self._counter

    async def create(self, incident: Incident) -> Incident:
        if incident.incident_id in self._items:
            raise ConflictError(f"incident {incident.incident_id} already exists")
        self._items[incident.incident_id] = _copy(incident)
        return _copy(incident)

    async def get(self, incident_id: str) -> Incident | None:
        item = self._items.get(incident_id)
        return _copy(item) if item else None

    async def update(self, incident: Incident, expected_version: int) -> Incident:
        current = self._items.get(incident.incident_id)
        if current is None:
            raise NotFound(incident.incident_id)
        if current.version != expected_version:
            raise ConflictError(
                f"incident {incident.incident_id} version {current.version} != expected {expected_version}"
            )
        stored = incident.model_copy(deep=True, update={"version": expected_version + 1})
        self._items[incident.incident_id] = stored
        return _copy(stored)

    async def list(
        self, status: IncidentStatus | None = None, limit: int = 50, cursor: str | None = None
    ) -> Page[Incident]:
        items = sorted(self._items.values(), key=lambda i: i.created_at, reverse=True)
        if status is not None:
            items = [i for i in items if i.status == status]
        start = int(cursor) if cursor else 0
        chunk = items[start : start + limit]
        next_cursor = str(start + limit) if start + limit < len(items) else None
        return Page[Incident](items=[_copy(i) for i in chunk], next_cursor=next_cursor)

    async def list_active(self) -> list[Incident]:
        return [_copy(i) for i in self._items.values() if i.status.is_active]


class InMemoryDedupRepository:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._items: dict[str, tuple[str, datetime]] = {}

    async def claim(self, key: str, incident_id: str, ttl_seconds: int) -> str | None:
        now = self._clock.now()
        existing = self._items.get(key)
        if existing and existing[1] > now:
            return existing[0]
        self._items[key] = (incident_id, now + timedelta(seconds=ttl_seconds))
        return None


class InMemoryTimelineRepository:
    def __init__(self) -> None:
        self._by_incident: dict[str, list[TimelineEvent]] = {}
        self._global: list[TimelineEvent] = []

    async def append(self, event: TimelineEvent) -> TimelineEvent:
        events = self._by_incident.setdefault(event.incident_id, [])
        if any(e.event_id == event.event_id for e in events):
            raise ConflictError(f"timeline event {event.event_id} exists")
        events.append(_copy(event))
        events.sort(key=lambda e: e.event_id)
        self._global.append(_copy(event))
        self._global.sort(key=lambda e: e.event_id)
        return _copy(event)

    async def list(self, incident_id: str, after_event_id: str | None = None, limit: int = 500) -> list[TimelineEvent]:
        events = self._by_incident.get(incident_id, [])
        if after_event_id:
            events = [e for e in events if e.event_id > after_event_id]
        return [_copy(e) for e in events[:limit]]

    async def list_global(self, after_event_id: str | None = None, limit: int = 200) -> list[TimelineEvent]:
        events = self._global
        if after_event_id:
            events = [e for e in events if e.event_id > after_event_id]
        return [_copy(e) for e in events[:limit]]


class _ByIncident[M]:
    def __init__(self, id_attr: str) -> None:
        self._id_attr = id_attr
        self._items: dict[str, dict[str, M]] = {}

    def put(self, incident_id: str, item: M) -> M:
        self._items.setdefault(incident_id, {})[getattr(item, self._id_attr)] = _copy(item)
        return _copy(item)

    def get(self, incident_id: str, item_id: str) -> M | None:
        item = self._items.get(incident_id, {}).get(item_id)
        return _copy(item) if item else None

    def list(self, incident_id: str) -> list[M]:
        return [_copy(i) for i in self._items.get(incident_id, {}).values()]


class InMemoryEvidenceRepository:
    def __init__(self) -> None:
        self._store: _ByIncident[Evidence] = _ByIncident("evidence_id")

    async def put(self, evidence: Evidence) -> Evidence:
        return self._store.put(evidence.incident_id, evidence)

    async def get(self, incident_id: str, evidence_id: str) -> Evidence | None:
        return self._store.get(incident_id, evidence_id)

    async def list(self, incident_id: str) -> list[Evidence]:
        return sorted(self._store.list(incident_id), key=lambda e: e.evidence_id)


class InMemoryFindingRepository:
    def __init__(self) -> None:
        self._store: _ByIncident[Finding] = _ByIncident("finding_id")

    async def put(self, finding: Finding) -> Finding:
        return self._store.put(finding.incident_id, finding)

    async def list(self, incident_id: str) -> list[Finding]:
        return sorted(self._store.list(incident_id), key=lambda f: f.finding_id)


class InMemoryDiagnosisRepository:
    def __init__(self) -> None:
        self._store: _ByIncident[Diagnosis] = _ByIncident("diagnosis_id")

    async def put(self, diagnosis: Diagnosis) -> Diagnosis:
        return self._store.put(diagnosis.incident_id, diagnosis)

    async def get(self, incident_id: str, diagnosis_id: str) -> Diagnosis | None:
        return self._store.get(incident_id, diagnosis_id)

    async def latest(self, incident_id: str) -> Diagnosis | None:
        items = await self.list(incident_id)
        return items[0] if items else None

    async def list(self, incident_id: str) -> list[Diagnosis]:
        return sorted(self._store.list(incident_id), key=lambda d: d.diagnosis_id, reverse=True)


class InMemoryPlanRepository:
    def __init__(self) -> None:
        self._items: dict[str, RemediationPlan] = {}

    async def create(self, plan: RemediationPlan) -> RemediationPlan:
        if plan.plan_id in self._items:
            raise ConflictError(f"plan {plan.plan_id} exists")
        if not plan.hash_is_valid():
            raise ConflictError("plan must be sealed (valid plan_hash) before it is stored")
        self._items[plan.plan_id] = _copy(plan)
        return _copy(plan)

    async def get(self, plan_id: str) -> RemediationPlan | None:
        item = self._items.get(plan_id)
        return _copy(item) if item else None

    async def list_for_incident(self, incident_id: str) -> list[RemediationPlan]:
        plans = [p for p in self._items.values() if p.incident_id == incident_id]
        return [_copy(p) for p in sorted(plans, key=lambda p: p.revision, reverse=True)]

    async def set_status(
        self, plan_id: str, status: PlanStatus, expected_status: PlanStatus | None = None
    ) -> RemediationPlan:
        plan = self._items.get(plan_id)
        if plan is None:
            raise NotFound(plan_id)
        if expected_status is not None and plan.status != expected_status:
            raise ConflictError(f"plan {plan_id} is {plan.status.value}, expected {expected_status.value}")
        plan.status = status
        return _copy(plan)

    async def attach_review(self, plan_id: str, review: PlanReview) -> RemediationPlan:
        plan = self._items.get(plan_id)
        if plan is None:
            raise NotFound(plan_id)
        if review.plan_hash != plan.plan_hash:
            raise ConflictError("review is for a different plan hash")
        plan.review = _copy(review)
        return _copy(plan)


class InMemoryApprovalRepository:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._items: dict[str, Approval] = {}
        self._grants: dict[str, tuple[str, datetime]] = {}

    async def create(self, approval: Approval) -> Approval:
        if approval.approval_id in self._items:
            raise ConflictError(f"approval {approval.approval_id} exists")
        self._items[approval.approval_id] = _copy(approval)
        return _copy(approval)

    async def get(self, approval_id: str) -> Approval | None:
        item = self._items.get(approval_id)
        return _copy(item) if item else None

    async def list_for_plan(self, plan_id: str) -> list[Approval]:
        items = [a for a in self._items.values() if a.plan_id == plan_id]
        return [_copy(a) for a in sorted(items, key=lambda a: a.decided_at, reverse=True)]

    async def list_for_incident(self, incident_id: str) -> list[Approval]:
        items = [a for a in self._items.values() if a.incident_id == incident_id]
        return [_copy(a) for a in sorted(items, key=lambda a: a.decided_at, reverse=True)]

    async def mark_consumed(self, approval_id: str, execution_id: str, consumed_at: datetime) -> Approval:
        approval = self._items.get(approval_id)
        if approval is None:
            raise NotFound(approval_id)
        if approval.execution_id != execution_id:
            raise ConflictError("approval is bound to a different execution")
        if approval.consumed_at is not None:
            raise ConflictError("approval already consumed")
        approval.consumed_at = consumed_at
        return _copy(approval)

    async def put_grant(self, approval_id: str, token: str, expires_at: datetime) -> None:
        self._grants[approval_id] = (token, expires_at)

    async def get_grant(self, approval_id: str) -> str | None:
        grant = self._grants.get(approval_id)
        if grant is None or grant[1] <= self._clock.now():
            return None
        return grant[0]


class InMemoryExecutionRepository:
    def __init__(self) -> None:
        self._items: dict[str, Execution] = {}

    async def create(self, execution: Execution) -> Execution:
        if execution.execution_id in self._items:
            raise ConflictError(f"execution {execution.execution_id} exists")
        self._items[execution.execution_id] = _copy(execution)
        return _copy(execution)

    async def get(self, execution_id: str) -> Execution | None:
        item = self._items.get(execution_id)
        return _copy(item) if item else None

    async def update(self, execution: Execution, expected_version: int) -> Execution:
        current = self._items.get(execution.execution_id)
        if current is None:
            raise NotFound(execution.execution_id)
        if current.version != expected_version:
            raise ConflictError(f"execution version {current.version} != expected {expected_version}")
        stored = execution.model_copy(deep=True, update={"version": expected_version + 1})
        self._items[execution.execution_id] = stored
        return _copy(stored)

    async def list_for_incident(self, incident_id: str) -> list[Execution]:
        items = [e for e in self._items.values() if e.incident_id == incident_id]
        return [_copy(e) for e in sorted(items, key=lambda e: e.execution_id, reverse=True)]

    async def list_by_status(self, status: ExecutionStatus) -> list[Execution]:
        return [_copy(e) for e in self._items.values() if e.status == status]


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self._items: list[AuditEvent] = []
        self.available = True  # tests flip this to prove mutations are blocked without audit storage

    async def append(self, event: AuditEvent) -> AuditEvent:
        if not self.available:
            raise DependencyUnavailable("audit storage unavailable")
        self._items.append(_copy(event))
        return _copy(event)

    async def list(self, incident_id: str | None = None, limit: int = 500) -> list[AuditEvent]:
        items = [e for e in self._items if incident_id is None or e.incident_id == incident_id]
        items.sort(key=lambda e: e.event_id)
        return [_copy(e) for e in items[-limit:]]


class InMemoryMemoryRepository:
    def __init__(self) -> None:
        self._items: dict[str, MemoryRecord] = {}

    async def put(self, record: MemoryRecord) -> MemoryRecord:
        self._items[record.memory_id] = _copy(record)
        return _copy(record)

    async def get(self, memory_id: str) -> MemoryRecord | None:
        item = self._items.get(memory_id)
        return _copy(item) if item else None

    async def list(self, status: MemoryStatus | None = MemoryStatus.ACTIVE) -> list[MemoryRecord]:
        items = [m for m in self._items.values() if status is None or m.status == status]
        return [_copy(m) for m in sorted(items, key=lambda m: m.created_at, reverse=True)]

    async def invalidate(self, memory_id: str, reason: str) -> MemoryRecord:
        record = self._items.get(memory_id)
        if record is None:
            raise NotFound(memory_id)
        record.status = MemoryStatus.INVALIDATED
        record.invalidated_reason = reason
        return _copy(record)


class InMemoryLockRepository:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._items: dict[str, tuple[str, datetime]] = {}

    async def acquire(self, resource_key: str, owner: str, ttl_seconds: int) -> bool:
        now = self._clock.now()
        held = self._items.get(resource_key)
        if held and held[0] != owner and held[1] > now:
            return False
        self._items[resource_key] = (owner, now + timedelta(seconds=ttl_seconds))
        return True

    async def release(self, resource_key: str, owner: str) -> None:
        held = self._items.get(resource_key)
        if held and held[0] == owner:
            del self._items[resource_key]

    async def holder(self, resource_key: str) -> str | None:
        held = self._items.get(resource_key)
        if held and held[1] > self._clock.now():
            return held[0]
        return None


class InMemoryOutboxRepository:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._items: dict[str, OutboxMessage] = {}

    async def add(self, message: OutboxMessage) -> OutboxMessage:
        if message.dedup_key:
            for existing in self._items.values():
                if existing.dedup_key == message.dedup_key:
                    return _copy(existing)
        self._items[message.outbox_id] = _copy(message)
        return _copy(message)

    async def list_pending(self, limit: int = 50) -> list[OutboxMessage]:
        items = [m for m in self._items.values() if m.status in ("pending", "failed")]
        items.sort(key=lambda m: m.outbox_id)
        return [_copy(m) for m in items[:limit]]

    async def mark_sent(self, outbox_id: str) -> None:
        message = self._items[outbox_id]
        message.status = "sent"
        message.sent_at = self._clock.now()

    async def mark_failed(self, outbox_id: str, error: str) -> None:
        message = self._items[outbox_id]
        message.status = "failed"
        message.attempts += 1
        message.last_error = error[:500]


class InMemoryChangeRepository:
    def __init__(self) -> None:
        self._changes: list[ChangeRecord] = []
        self._snapshots: dict[str, ConfigSnapshot] = {}

    async def record_change(self, change: ChangeRecord) -> ChangeRecord:
        self._changes.append(_copy(change))
        return _copy(change)

    async def list_changes(
        self, since: datetime, namespace: str | None = None, resource: ResourceRef | None = None
    ) -> list[ChangeRecord]:
        items = [c for c in self._changes if c.observed_at >= since]
        if namespace is not None:
            items = [c for c in items if c.resource.namespace in (namespace, None)]
        if resource is not None:
            items = [c for c in items if c.resource.key == resource.key]
        return [_copy(c) for c in sorted(items, key=lambda c: c.observed_at, reverse=True)]

    async def put_snapshot(self, snapshot: ConfigSnapshot) -> ConfigSnapshot:
        self._snapshots[snapshot.snapshot_id] = _copy(snapshot)
        return _copy(snapshot)

    async def get_snapshot(self, snapshot_id: str) -> ConfigSnapshot | None:
        item = self._snapshots.get(snapshot_id)
        return _copy(item) if item else None

    async def latest_snapshot(self, resource: ResourceRef, known_good_only: bool = False) -> ConfigSnapshot | None:
        items = await self.list_snapshots(resource, limit=1000)
        if known_good_only:
            items = [s for s in items if s.known_good]
        return items[0] if items else None

    async def list_snapshots(self, resource: ResourceRef, limit: int = 20) -> list[ConfigSnapshot]:
        items = [s for s in self._snapshots.values() if s.resource.key == resource.key]
        items.sort(key=lambda s: s.captured_at, reverse=True)
        return [_copy(s) for s in items[:limit]]


class InMemoryReportRepository:
    def __init__(self) -> None:
        self._items: dict[str, PostmortemReport] = {}

    async def put(self, report: PostmortemReport) -> PostmortemReport:
        self._items[report.incident_id] = _copy(report)
        return _copy(report)

    async def get(self, incident_id: str) -> PostmortemReport | None:
        item = self._items.get(incident_id)
        return _copy(item) if item else None

    async def list(self, limit: int = 50) -> list[PostmortemReport]:
        items = sorted(self._items.values(), key=lambda r: r.created_at, reverse=True)
        return [_copy(r) for r in items[:limit]]


class InMemoryAgentRunRepository:
    def __init__(self) -> None:
        self._items: dict[str, AgentRun] = {}

    async def put(self, run: AgentRun) -> AgentRun:
        self._items[run.run_id] = _copy(run)
        return _copy(run)

    async def list(self, incident_id: str) -> list[AgentRun]:
        items = [r for r in self._items.values() if r.incident_id == incident_id]
        return [_copy(r) for r in sorted(items, key=lambda r: r.run_id)]


class InMemoryMutationJournalRepository:
    def __init__(self) -> None:
        self._items: dict[str, MutationJournalEntry] = {}

    async def record_intent(self, entry: MutationJournalEntry) -> tuple[MutationJournalEntry, bool]:
        existing = self._items.get(entry.idempotency_key)
        if existing is not None:
            return _copy(existing), False
        self._items[entry.idempotency_key] = _copy(entry)
        return _copy(entry), True

    async def get(self, idempotency_key: str) -> MutationJournalEntry | None:
        item = self._items.get(idempotency_key)
        return _copy(item) if item else None

    async def complete(
        self,
        idempotency_key: str,
        status: str,
        *,
        after_state: dict | None,
        message: str,
        audit_event_id: str | None,
        updated_at: datetime,
    ) -> MutationJournalEntry:
        entry = self._items.get(idempotency_key)
        if entry is None:
            raise NotFound(idempotency_key)
        entry.status = status
        entry.after_state = after_state
        entry.message = message
        entry.audit_event_id = audit_event_id
        entry.updated_at = updated_at
        return _copy(entry)


class InMemoryArtifactStore:
    PREFIX = "artifact://"

    def __init__(self) -> None:
        self._items: dict[str, tuple[bytes, str]] = {}

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self._items[key] = (data, content_type)
        return self.PREFIX + key

    async def put_json(self, key: str, value: object) -> str:
        payload = json.dumps(value, default=str, sort_keys=True).encode()
        return await self.put_bytes(key, payload, "application/json")

    async def get_bytes(self, uri: str) -> bytes:
        key = uri.removeprefix(self.PREFIX)
        if key not in self._items:
            raise NotFound(uri)
        return self._items[key][0]

    async def exists(self, uri: str) -> bool:
        return uri.removeprefix(self.PREFIX) in self._items

    async def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self._items if k.startswith(prefix))


@dataclass
class InMemoryRepositories:
    clock: Clock = field(default_factory=SystemClock)

    def __post_init__(self) -> None:
        self.incidents = InMemoryIncidentRepository()
        self.dedup = InMemoryDedupRepository(self.clock)
        self.timeline = InMemoryTimelineRepository()
        self.evidence = InMemoryEvidenceRepository()
        self.findings = InMemoryFindingRepository()
        self.diagnoses = InMemoryDiagnosisRepository()
        self.plans = InMemoryPlanRepository()
        self.approvals = InMemoryApprovalRepository(self.clock)
        self.executions = InMemoryExecutionRepository()
        self.audit = InMemoryAuditRepository()
        self.memory = InMemoryMemoryRepository()
        self.locks = InMemoryLockRepository(self.clock)
        self.outbox = InMemoryOutboxRepository(self.clock)
        self.changes = InMemoryChangeRepository()
        self.reports = InMemoryReportRepository()
        self.agent_runs = InMemoryAgentRunRepository()
        self.mutation_journal = InMemoryMutationJournalRepository()
        self.artifacts = InMemoryArtifactStore()
