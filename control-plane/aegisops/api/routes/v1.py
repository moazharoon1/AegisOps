"""Versioned API surface (/api/v1). CONTRACT: paths, methods, request bodies and response models are
shared with the dashboard and CLI (generated TypeScript types). Handler bodies are implemented by
the core workstream; do not change signatures without updating docs/CONTRACTS.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import PlainTextResponse

from aegisops.api.deps import get_current_user, require_approver
from aegisops.api.schemas import (
    AlertIngestResponse,
    AlertmanagerWebhook,
    CancelRequest,
    CreateIncidentRequest,
    DecisionRequest,
    DecisionResponse,
    EvaluationRunDetail,
    EvaluationRunSummary,
    IncidentDetail,
    IncidentPage,
    InvalidateMemoryRequest,
    LoginRequest,
    LoginResponse,
    MemorySearchResponse,
    PermissionMatrix,
    RejectRequest,
    ResolveRequest,
    RevisionRequest,
    ScenarioInjectRequest,
    SystemStatus,
)
from aegisops.domain.enums import IncidentStatus
from aegisops.domain.models import (
    AgentRun,
    AuditEvent,
    Diagnosis,
    Evidence,
    Execution,
    Finding,
    Incident,
    MemoryRecord,
    PostmortemReport,
    RemediationPlan,
    TimelineEvent,
    User,
)
from aegisops.domain.tools import RunbookDocument, RunbookHit, RunbookSummary
from aegisops.ports.services import ScenarioInfo, ScenarioRun

router = APIRouter(prefix="/api/v1")


def _todo() -> None:
    raise NotImplementedError("implemented by the core workstream")


# =============================================================================== auth
@router.post("/auth/login", response_model=LoginResponse, tags=["auth"])
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    _todo()


@router.get("/auth/me", response_model=User, tags=["auth"])
async def me(user: User = Depends(get_current_user)) -> User:
    return user


# =============================================================================== system
@router.get("/system/status", response_model=SystemStatus, tags=["system"])
async def system_status(request: Request, user: User = Depends(get_current_user)) -> SystemStatus:
    _todo()


@router.get("/permissions", response_model=PermissionMatrix, tags=["system"])
async def permissions(user: User = Depends(get_current_user)) -> PermissionMatrix:
    _todo()


# =============================================================================== alert intake
@router.post("/alerts/alertmanager", response_model=AlertIngestResponse, tags=["intake"])
async def ingest_alertmanager(
    body: AlertmanagerWebhook,
    request: Request,
    authorization: str | None = Header(default=None),
) -> AlertIngestResponse:
    """Alertmanager webhook (bearer = AEGIS_ALERT_WEBHOOK_TOKEN). Each accepted alert is persisted
    before the response; duplicates (same fingerprint + startsAt) are acknowledged, not re-created."""
    _todo()


# =============================================================================== incidents
@router.get("/incidents", response_model=IncidentPage, tags=["incidents"])
async def list_incidents(
    request: Request,
    status: IncidentStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    user: User = Depends(get_current_user),
) -> IncidentPage:
    _todo()


@router.post("/incidents", response_model=Incident, status_code=201, tags=["incidents"])
async def create_incident(
    body: CreateIncidentRequest, request: Request, user: User = Depends(require_approver)
) -> Incident:
    """Manual incident report (approver role)."""
    _todo()


@router.get("/incidents/{incident_id}", response_model=IncidentDetail, tags=["incidents"])
async def get_incident(incident_id: str, request: Request, user: User = Depends(get_current_user)) -> IncidentDetail:
    _todo()


@router.get("/incidents/{incident_id}/timeline", response_model=list[TimelineEvent], tags=["incidents"])
async def get_timeline(
    incident_id: str,
    request: Request,
    after: str | None = Query(default=None, description="return events with event_id > after"),
    user: User = Depends(get_current_user),
) -> list[TimelineEvent]:
    _todo()


@router.get("/incidents/{incident_id}/evidence", response_model=list[Evidence], tags=["incidents"])
async def list_evidence(incident_id: str, request: Request, user: User = Depends(get_current_user)) -> list[Evidence]:
    _todo()


@router.get("/incidents/{incident_id}/evidence/{evidence_id}", response_model=Evidence, tags=["incidents"])
async def get_evidence(
    incident_id: str, evidence_id: str, request: Request, user: User = Depends(get_current_user)
) -> Evidence:
    """Includes the full redacted artifact payload in `data` when stored as an artifact."""
    _todo()


@router.get("/incidents/{incident_id}/findings", response_model=list[Finding], tags=["incidents"])
async def list_findings(incident_id: str, request: Request, user: User = Depends(get_current_user)) -> list[Finding]:
    _todo()


@router.get("/incidents/{incident_id}/diagnoses", response_model=list[Diagnosis], tags=["incidents"])
async def list_diagnoses(incident_id: str, request: Request, user: User = Depends(get_current_user)) -> list[Diagnosis]:
    _todo()


@router.get("/incidents/{incident_id}/agents", response_model=list[AgentRun], tags=["incidents"])
async def list_agent_runs(incident_id: str, request: Request, user: User = Depends(get_current_user)) -> list[AgentRun]:
    _todo()


@router.get("/incidents/{incident_id}/plans", response_model=list[RemediationPlan], tags=["plans"])
async def list_plans(
    incident_id: str, request: Request, user: User = Depends(get_current_user)
) -> list[RemediationPlan]:
    _todo()


@router.get("/incidents/{incident_id}/plans/{plan_id}", response_model=RemediationPlan, tags=["plans"])
async def get_plan(
    incident_id: str, plan_id: str, request: Request, user: User = Depends(get_current_user)
) -> RemediationPlan:
    _todo()


@router.post("/incidents/{incident_id}/plans/{plan_id}/approve", response_model=DecisionResponse, tags=["plans"])
async def approve_plan(
    incident_id: str, plan_id: str, body: DecisionRequest, request: Request, user: User = Depends(require_approver)
) -> DecisionResponse:
    """Approver role only. `plan_hash` must equal the stored plan hash (what the human reviewed)."""
    _todo()


@router.post("/incidents/{incident_id}/plans/{plan_id}/reject", response_model=DecisionResponse, tags=["plans"])
async def reject_plan(
    incident_id: str, plan_id: str, body: RejectRequest, request: Request, user: User = Depends(require_approver)
) -> DecisionResponse:
    _todo()


@router.post(
    "/incidents/{incident_id}/plans/{plan_id}/request-revision", response_model=DecisionResponse, tags=["plans"]
)
async def request_revision(
    incident_id: str, plan_id: str, body: RevisionRequest, request: Request, user: User = Depends(require_approver)
) -> DecisionResponse:
    _todo()


@router.get("/incidents/{incident_id}/executions", response_model=list[Execution], tags=["executions"])
async def list_executions(
    incident_id: str, request: Request, user: User = Depends(get_current_user)
) -> list[Execution]:
    _todo()


@router.post("/incidents/{incident_id}/cancel", response_model=Incident, tags=["incidents"])
async def cancel_incident(
    incident_id: str, body: CancelRequest, request: Request, user: User = Depends(require_approver)
) -> Incident:
    """Cancels pending work; a running execution stops before its next step."""
    _todo()


@router.post("/incidents/{incident_id}/resolve", response_model=Incident, tags=["incidents"])
async def resolve_incident(
    incident_id: str, body: ResolveRequest, request: Request, user: User = Depends(require_approver)
) -> Incident:
    """Manual resolution of a needs_attention incident (recorded with the human's note)."""
    _todo()


@router.post("/incidents/{incident_id}/reinvestigate", response_model=Incident, tags=["incidents"])
async def reinvestigate_incident(
    incident_id: str, request: Request, user: User = Depends(require_approver)
) -> Incident:
    _todo()


@router.get("/incidents/{incident_id}/report", response_model=PostmortemReport, tags=["reports"])
async def get_report(incident_id: str, request: Request, user: User = Depends(get_current_user)) -> PostmortemReport:
    _todo()


@router.get("/incidents/{incident_id}/report.md", response_class=PlainTextResponse, tags=["reports"])
async def export_report_markdown(incident_id: str, request: Request, user: User = Depends(get_current_user)) -> str:
    _todo()


@router.get("/incidents/{incident_id}/audit", response_model=list[AuditEvent], tags=["incidents"])
async def list_audit(incident_id: str, request: Request, user: User = Depends(get_current_user)) -> list[AuditEvent]:
    _todo()


@router.get("/reports", response_model=list[PostmortemReport], tags=["reports"])
async def list_reports(request: Request, user: User = Depends(get_current_user)) -> list[PostmortemReport]:
    _todo()


# =============================================================================== knowledge
@router.get("/runbooks", response_model=list[RunbookSummary], tags=["knowledge"])
async def list_runbooks(request: Request, user: User = Depends(get_current_user)) -> list[RunbookSummary]:
    _todo()


@router.get("/runbooks/search", response_model=list[RunbookHit], tags=["knowledge"])
async def search_runbooks(
    request: Request,
    q: str = Query(min_length=2, max_length=500),
    service: str | None = None,
    top_k: int = Query(default=5, ge=1, le=8),
    user: User = Depends(get_current_user),
) -> list[RunbookHit]:
    _todo()


@router.get("/runbooks/{runbook_id}", response_model=RunbookDocument, tags=["knowledge"])
async def get_runbook(runbook_id: str, request: Request, user: User = Depends(get_current_user)) -> RunbookDocument:
    _todo()


@router.get("/memory", response_model=list[MemoryRecord], tags=["knowledge"])
async def list_memory(
    request: Request, include_invalidated: bool = False, user: User = Depends(get_current_user)
) -> list[MemoryRecord]:
    _todo()


@router.get("/memory/search", response_model=MemorySearchResponse, tags=["knowledge"])
async def search_memory(
    request: Request,
    q: str = Query(min_length=2, max_length=1000),
    service: str | None = None,
    user: User = Depends(get_current_user),
) -> MemorySearchResponse:
    _todo()


@router.post("/memory/{memory_id}/invalidate", response_model=MemoryRecord, tags=["knowledge"])
async def invalidate_memory(
    memory_id: str, body: InvalidateMemoryRequest, request: Request, user: User = Depends(require_approver)
) -> MemoryRecord:
    _todo()


# =============================================================================== scenarios (local only)
@router.get("/scenarios", response_model=list[ScenarioInfo], tags=["scenarios"])
async def list_scenarios(request: Request, user: User = Depends(get_current_user)) -> list[ScenarioInfo]:
    """404 unless AEGIS_ENABLE_SIMULATION=true."""
    _todo()


@router.get("/scenarios/active", response_model=ScenarioRun | None, tags=["scenarios"])
async def active_scenario(request: Request, user: User = Depends(get_current_user)) -> ScenarioRun | None:
    _todo()


@router.post("/scenarios/{scenario_id}/inject", response_model=ScenarioRun, tags=["scenarios"])
async def inject_scenario(
    scenario_id: str, body: ScenarioInjectRequest, request: Request, user: User = Depends(require_approver)
) -> ScenarioRun:
    _todo()


@router.post("/scenarios/reset", response_model=ScenarioRun | None, tags=["scenarios"])
async def reset_scenario(request: Request, user: User = Depends(require_approver)) -> ScenarioRun | None:
    _todo()


# =============================================================================== evaluations
@router.get("/evaluations", response_model=list[EvaluationRunSummary], tags=["evaluations"])
async def list_evaluations(request: Request, user: User = Depends(get_current_user)) -> list[EvaluationRunSummary]:
    """Reads evaluation/results/*/summary.json produced by the evaluation harness."""
    _todo()


@router.get("/evaluations/{run_id}", response_model=EvaluationRunDetail, tags=["evaluations"])
async def get_evaluation(run_id: str, request: Request, user: User = Depends(get_current_user)) -> EvaluationRunDetail:
    _todo()


# =============================================================================== live updates
@router.get("/events/stream", tags=["events"])
async def stream_events(
    request: Request,
    incident_id: str | None = None,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    token: str | None = Query(default=None, description="session token (EventSource cannot send headers)"),
):
    """Server-Sent Events. `id:` = TimelineEvent.event_id, `event:` = TimelineEvent.kind,
    `data:` = TimelineEvent JSON. Reconnects resume after Last-Event-ID without losing entries.
    Without incident_id the stream carries all incidents' events. Sends a `ping` comment every 15s."""
    _todo()
