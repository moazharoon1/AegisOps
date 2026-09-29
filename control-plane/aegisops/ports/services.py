"""Service ports shared across workstreams. Each port names its implementing package."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from aegisops.domain.enums import (
    AgentRole,
    ApprovalDecision,
    AuditOutcome,
    FaultType,
    IncidentStatus,
    TimelineKind,
)
from aegisops.domain.models import (
    Approval,
    AuditEvent,
    Execution,
    Incident,
    MemoryRecord,
    PlanReview,
    RemediationPlan,
    TimelineEvent,
    User,
    VerificationResult,
)
from aegisops.domain.tools import (
    MemoryHit,
    PlanDraft,
    RunbookDocument,
    RunbookHit,
    RunbookSummary,
    ToolEnvelope,
    ToolSpec,
)


# --------------------------------------------------------------------------- clock
class Clock(Protocol):
    """Implemented by `aegisops.ports.clock.SystemClock` and the simulation's VirtualClock."""

    def now(self) -> datetime: ...
    async def sleep(self, seconds: float) -> None: ...


# --------------------------------------------------------------------------- MCP gateway
class ToolCallOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    envelope: ToolEnvelope
    evidence_id: str | None = None  # set when the result was recorded as Evidence


class ToolInvoker(Protocol):
    """Implemented by `aegisops.mcp.gateway`. Calls MCP tools *as* an agent identity (per-role
    service token); the server enforces permissions. Records non-mutating results as Evidence
    (redacted, bounded, content-hashed, large payloads stored as artifacts)."""

    def tools_for(self, role: AgentRole) -> list[ToolSpec]: ...

    async def invoke(
        self,
        role: AgentRole,
        tool: str,
        arguments: dict[str, Any],
        *,
        incident_id: str | None = None,
        record_evidence: bool = True,
    ) -> ToolCallOutcome: ...


# --------------------------------------------------------------------------- incidents & governance
class IncidentService(Protocol):
    """Implemented by `aegisops.incidents.service` (core). The single place where incident status
    changes: validates the lifecycle, writes conditionally, and emits timeline + audit events."""

    async def get(self, incident_id: str) -> Incident: ...

    async def transition(
        self, incident_id: str, target: IncidentStatus, *, actor: str, reason: str | None = None
    ) -> Incident: ...

    async def update_fields(self, incident_id: str, *, actor: str, **fields: Any) -> Incident:
        """Conditional update of non-status fields (metrics, diagnosis_id, current_plan_id, ...)."""
        ...

    async def add_timeline(
        self, incident_id: str, kind: TimelineKind, *, actor: str, title: str, detail: dict[str, Any] | None = None
    ) -> TimelineEvent: ...

    async def audit(
        self,
        *,
        actor: str,
        operation: str,
        outcome: AuditOutcome,
        incident_id: str | None = None,
        details: dict[str, Any] | None = None,
        evidence_refs: list[str] | None = None,
    ) -> AuditEvent: ...


class ApprovalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval: Approval
    authorization_token: str | None = None  # only for approved decisions; never logged


class GovernanceService(Protocol):
    """Implemented by `aegisops.governance.service` (core). Used by the API (humans) and by the
    knowledge MCP server's governance tools (agents)."""

    async def create_plan(
        self, incident_id: str, draft: PlanDraft, *, created_by: AgentRole, supersedes_plan_id: str | None = None
    ) -> RemediationPlan: ...

    async def submit_review(self, review: PlanReview) -> RemediationPlan: ...

    async def request_approval(self, incident_id: str, plan_id: str, *, requested_by: AgentRole) -> RemediationPlan: ...

    async def decide(
        self,
        user: User,
        incident_id: str,
        plan_id: str,
        plan_hash: str,
        decision: ApprovalDecision,
        comment: str | None,
    ) -> ApprovalResult:
        """Human decision. Requires the approver role and a matching plan hash. Approval creates
        the single execution id it authorizes and an EdDSA token (15 min TTL)."""
        ...

    async def cancel(self, user: User, incident_id: str, reason: str) -> Incident: ...


# --------------------------------------------------------------------------- workflow
class IncidentWorkflow(Protocol):
    """Implemented by `aegisops.workflow` (LangGraph). Driven by the worker from queue messages.
    All methods are idempotent and re-read durable state (messages are only notifications)."""

    async def start(self, incident_id: str) -> None: ...
    async def resume_after_decision(self, incident_id: str, approval_id: str) -> None: ...
    async def cancel(self, incident_id: str, reason: str) -> None: ...
    async def reconcile(self, incident_id: str) -> None:
        """Called after restarts for every active incident: continue from the last checkpoint."""
        ...


ProgressCallback = Callable[[VerificationResult], Awaitable[None]]


class RemediationExecutor(Protocol):
    """Implemented by `aegisops.executor` - deterministic, never asks an LLM for commands."""

    async def execute(self, incident_id: str, approval_id: str, authorization_token: str) -> Execution: ...
    async def reconcile(self, execution_id: str) -> Execution:
        """Resolve ambiguous/in-flight steps by observing current state before any retry."""
        ...

    async def compensate(self, execution_id: str) -> Execution:
        """Run the plan's pre-approved `compensation` steps (and nothing else) after failed
        verification. A plan without compensation steps is a no-op."""
        ...


class RecoveryVerifier(Protocol):
    """Implemented by `aegisops.verification`."""

    async def verify(
        self, plan: RemediationPlan, execution: Execution, on_progress: ProgressCallback | None = None
    ) -> VerificationResult: ...


# --------------------------------------------------------------------------- knowledge
class KnowledgeService(Protocol):
    """Implemented by `aegisops.knowledge.service`. Retrieved content is untrusted data."""

    async def list_runbooks(self) -> list[RunbookSummary]: ...
    async def get_runbook(self, runbook_id: str) -> RunbookDocument | None: ...
    async def search_runbooks(
        self, query: str, *, service: str | None = None, fault_type: FaultType | None = None, top_k: int = 5
    ) -> tuple[list[RunbookHit], str]:
        """Returns (hits, retrieval mode: "hybrid" | "lexical")."""
        ...

    async def similar_incidents(self, query: str, *, service: str | None = None, top_k: int = 3) -> list[MemoryHit]: ...
    async def save_memory(self, record: MemoryRecord) -> tuple[MemoryRecord, str]:
        """Returns (record, "saved" | "updated_existing"). Merges with an equivalent active pattern."""
        ...

    async def invalidate_memory(self, memory_id: str, reason: str) -> MemoryRecord: ...
    async def rebuild_index(self) -> dict[str, Any]: ...


# --------------------------------------------------------------------------- simulation harness
class ScenarioInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str  # e.g. "crashloop-bad-deploy"
    title: str
    description: str  # human description of the injection (never shown to agents)
    variants: list[str] = Field(default_factory=list)
    default_variant: str = "canonical"


class ScenarioRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    scenario_id: str
    variant: str
    status: str  # injecting | active | resetting | reset | failed
    injected_at: datetime | None = None
    reset_at: datetime | None = None
    message: str | None = None


class ScenarioController(Protocol):
    """Implemented by `aegisops.sim.controller` (in-process world) and by an HTTP client for the
    in-cluster `sim-controller` (simulation namespace). Local-only; disabled unless
    AEGIS_ENABLE_SIMULATION=true. Expected answers never flow through this port."""

    async def list_scenarios(self) -> list[ScenarioInfo]: ...
    async def inject(self, scenario_id: str, variant: str = "canonical") -> ScenarioRun: ...
    async def reset(self) -> ScenarioRun | None: ...
    async def active(self) -> ScenarioRun | None: ...


# --------------------------------------------------------------------------- messaging
class WorkflowQueue(Protocol):
    """Implemented by `aegisops.intake.queue` (SQS via LocalStack; in-memory for tests)."""

    async def publish(self, message: dict[str, Any], *, dedup_key: str | None = None) -> None: ...
    async def receive(self, max_messages: int = 5, wait_seconds: int = 10) -> list[tuple[str, dict[str, Any]]]:
        """Returns (receipt_handle, body) pairs."""
        ...

    async def ack(self, receipt_handle: str) -> None: ...
