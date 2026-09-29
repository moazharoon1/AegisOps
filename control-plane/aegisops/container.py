"""Composition root. Every workstream exposes one factory with the signature
`build_<thing>(settings: Settings, c: Container) -> <Port>`; this module calls them in dependency
order. Processes (API, worker, MCP servers, evaluation) build only what they need.

Build order: repositories -> keyring -> incident service -> governance -> knowledge -> backends ->
tool invoker -> change recorder / verifier / executor -> agent runner -> workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aegisops.config import Settings
from aegisops.ports.clock import SystemClock
from aegisops.ports.repositories import Repositories
from aegisops.ports.services import (
    Clock,
    GovernanceService,
    IncidentService,
    IncidentWorkflow,
    KnowledgeService,
    RecoveryVerifier,
    RemediationExecutor,
    ScenarioController,
    ToolInvoker,
    WorkflowQueue,
)
from aegisops.security.tokens import KeyRing


@dataclass
class Backends:
    """Real (cluster) or simulated backends behind the MCP servers."""

    k8s_reader: Any = None  # ports.backends.KubernetesReader
    k8s_writer: Any = None  # ports.backends.KubernetesWriter (mutation server only)
    observability: Any = None  # ports.backends.ObservabilityBackend
    aws: Any = None  # ports.backends.AwsBackend


@dataclass
class Container:
    settings: Settings
    clock: Clock = field(default_factory=SystemClock)
    repos: Repositories | None = None
    keyring: KeyRing | None = None
    incidents: IncidentService | None = None
    governance: GovernanceService | None = None
    knowledge: KnowledgeService | None = None
    backends: Backends = field(default_factory=Backends)
    tools: ToolInvoker | None = None
    workflow_queue: WorkflowQueue | None = None
    change_recorder: Any = None  # aegisops.changes.recorder.ChangeRecorder
    verifier: RecoveryVerifier | None = None
    executor: RemediationExecutor | None = None
    agents: Any = None  # ports.agents.AgentRunner
    workflow: IncidentWorkflow | None = None
    scenarios: ScenarioController | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def build_core(settings: Settings, c: Container) -> Container:
    """Repositories, keys, incident + governance services, queue (API and worker need these)."""
    from aegisops.governance.factory import build_governance_service
    from aegisops.incidents.factory import build_incident_service
    from aegisops.messaging.factory import build_workflow_queue
    from aegisops.storage.factory import build_repositories

    c.repos = build_repositories(settings, c)
    c.keyring = KeyRing(settings.keys_dir)
    c.incidents = build_incident_service(settings, c)
    c.governance = build_governance_service(settings, c)
    c.workflow_queue = build_workflow_queue(settings, c)
    return c


def build_worker_container(settings: Settings, c: Container | None = None) -> Container:
    """Everything the worker needs to run investigations, execution and verification."""
    from aegisops.agents.factory import build_agent_runner
    from aegisops.changes.factory import build_change_recorder
    from aegisops.executor.factory import build_executor
    from aegisops.knowledge.factory import build_knowledge_service
    from aegisops.mcp.factory import build_backends, build_tool_invoker
    from aegisops.verification.factory import build_verifier
    from aegisops.workflow.factory import build_workflow

    c = c or Container(settings=settings)
    if c.repos is None:
        build_core(settings, c)
    c.knowledge = c.knowledge or build_knowledge_service(settings, c)
    if c.backends.observability is None:
        c.backends = build_backends(settings, c)
    c.tools = c.tools or build_tool_invoker(settings, c)
    c.change_recorder = c.change_recorder or build_change_recorder(settings, c)
    c.verifier = c.verifier or build_verifier(settings, c)
    c.executor = c.executor or build_executor(settings, c)
    c.agents = c.agents or build_agent_runner(settings, c)
    c.workflow = c.workflow or build_workflow(settings, c)
    return c
