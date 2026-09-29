"""Contract between the agent layer (`aegisops.agents` + `aegisops.llm`) and the LangGraph workflow
(`aegisops.workflow`).

The workflow owns orchestration, persistence, status transitions and checkpoints; the agent layer
owns prompts, model/tool loops, deterministic reasoning, output validation and context compaction.
Agents record their own evidence through the `ToolInvoker`; the workflow persists everything else
(findings, diagnoses, reviews, reports, agent runs) from the returned results.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from aegisops.domain.enums import AgentRole, Severity
from aegisops.domain.models import (
    AgentRun,
    AlertRef,
    Approval,
    Diagnosis,
    Execution,
    Finding,
    PlanReview,
    PostmortemReport,
    RemediationPlan,
)
from aegisops.domain.tools import MemoryCandidate, MemoryHit, PlanDraft, RunbookHit


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- working context
class IncidentFacts(Strict):
    """Exact facts that compaction never summarises."""

    incident_id: str
    title: str
    description: str | None = None
    services: list[str]
    namespace: str | None = "production"
    severity: Severity
    status: str
    created_at: datetime
    alerts: list[AlertRef] = Field(default_factory=list)


class EvidenceDigest(Strict):
    evidence_id: str
    source: str  # tool name
    collected_by: AgentRole
    observed_at: datetime
    summary: str
    data: Any = None  # bounded payload; dropped by compaction (artifact_uri/content_hash keep provenance)
    artifact_uri: str | None = None
    content_hash: str
    status: str = "ok"
    compacted: bool = False


class WorkingContext(Strict):
    """Layer 1 memory: what agents see. Rebuilt from durable records after restarts."""

    incident: IncidentFacts
    investigation_pass: int = 1
    evidence: list[EvidenceDigest] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    runbooks: list[RunbookHit] = Field(default_factory=list)
    memory_matches: list[MemoryHit] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)  # summaries of older discussion
    diagnosis: Diagnosis | None = None
    plan: RemediationPlan | None = None
    approvals: list[Approval] = Field(default_factory=list)  # authoritative, never summarised
    executions: list[Execution] = Field(default_factory=list)  # authoritative, never summarised
    pending_tasks: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)  # from the analyst for a second pass
    human_feedback: list[str] = Field(default_factory=list)  # revision requests
    reviewer_concerns: list[str] = Field(default_factory=list)
    compactions: int = 0
    token_estimate: int = 0


class CompactionReport(Strict):
    before_tokens: int
    after_tokens: int
    evidence_compacted: int
    duplicates_merged: int
    preserved_ids: list[str]  # evidence/finding/plan/approval/execution ids kept verbatim


# --------------------------------------------------------------------------- results
class TriageResult(Strict):
    summary: str
    severity: Severity | None = None  # suggested; the workflow decides whether to apply
    suspected_services: list[str] = Field(default_factory=list)
    focus_areas: list[str] = Field(default_factory=list)
    specialists: list[AgentRole] = Field(default_factory=list)  # subset of INVESTIGATION_SPECIALISTS
    memory_matches: list[MemoryHit] = Field(default_factory=list)


class SpecialistResult(Strict):
    role: AgentRole
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class KnowledgeResult(Strict):
    summary: str
    runbook_hits: list[RunbookHit] = Field(default_factory=list)
    memory_matches: list[MemoryHit] = Field(default_factory=list)
    recommended_runbooks: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class AnalysisResult(Strict):
    diagnosis: Diagnosis
    plan_draft: PlanDraft | None = None  # None for no_fault / unknown / insufficient evidence
    needs_more_investigation: bool = False
    follow_up_questions: list[str] = Field(default_factory=list)


class ReviewResult(Strict):
    review: PlanReview


class PostmortemResult(Strict):
    report: PostmortemReport
    memory_candidate: MemoryCandidate | None = None  # only for verified resolutions


AgentResult = TriageResult | SpecialistResult | KnowledgeResult | AnalysisResult | ReviewResult | PostmortemResult


class AgentOutcome(Strict):
    run: AgentRun  # status, timings, tool_calls, usage, model, run_mode (persisted by the workflow)
    result: AgentResult | None = None  # None when the run failed (see run.error)


class AgentRunner(Protocol):
    """Implemented by `aegisops.agents.runner` (factory `aegisops.agents.factory.build_agent_runner`)."""

    async def triage(self, context: WorkingContext) -> AgentOutcome: ...

    async def investigate(self, role: AgentRole, context: WorkingContext, focus: list[str]) -> AgentOutcome:
        """role in INVESTIGATION_SPECIALISTS; returns SpecialistResult or KnowledgeResult."""
        ...

    async def analyse(self, context: WorkingContext) -> AgentOutcome:
        """Root Cause Analyst -> AnalysisResult (uses human_feedback / reviewer_concerns when present)."""
        ...

    async def review(self, context: WorkingContext, plan: RemediationPlan) -> AgentOutcome:
        """Change-Plan Reviewer -> ReviewResult. Deterministic policy checks always run and a failed
        policy check forces verdict=reject regardless of the model's opinion."""
        ...

    async def write_postmortem(self, context: WorkingContext) -> AgentOutcome: ...

    def estimate_tokens(self, context: WorkingContext) -> int: ...

    async def compact(self, context: WorkingContext, target_tokens: int) -> tuple[WorkingContext, CompactionReport]: ...
