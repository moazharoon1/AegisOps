"""Role -> tool permission matrix, enforced server-side by every MCP server.

Principles:
* Investigators read; they never mutate.
* Only the Remediation Executor calls mutation tools, and each call also needs an approval token
  bound to the exact plan hash, execution and step (checked by the mutation server).
* No agent can record an approval. `gov_record_approval` exists only to demonstrate the denial;
  humans approve through the authenticated API.
"""

from __future__ import annotations

from aegisops.domain.enums import AgentRole
from aegisops.domain.tools import TOOL_CATALOG

R = AgentRole

_K8S_READ = {
    "k8s_list_pods",
    "k8s_describe_pod",
    "k8s_get_pod_logs",
    "k8s_get_events",
    "k8s_get_deployment",
    "k8s_get_deployment_history",
    "k8s_get_configmap_diff",
    "k8s_probe_endpoint",
}
_OBS_READ = {
    "obs_get_error_rate",
    "obs_get_latency_percentiles",
    "obs_get_dependency_errors",
    "obs_get_db_pool_stats",
    "obs_search_logs",
    "obs_search_traces",
    "obs_get_trace",
    "obs_get_recent_changes",
    "obs_get_active_alerts",
    "obs_query_metrics",
}
_AWS_READ = {
    "aws_get_queue_metrics",
    "aws_inspect_dlq",
    "aws_get_secret_metadata",
    "aws_get_dynamodb_throttling",
    "aws_get_cloud_errors",
}
_MUTATIONS = {
    "k8s_rollout_restart",
    "k8s_rollout_undo",
    "k8s_scale_deployment",
    "k8s_restore_configmap_key",
    "aws_restore_secret_version",
    "aws_set_queue_redrive_policy",
}

ROLE_TOOL_PERMISSIONS: dict[AgentRole, frozenset[str]] = {
    R.INCIDENT_COMMANDER: frozenset(
        {
            "obs_get_active_alerts",
            "obs_get_recent_changes",
            "obs_get_error_rate",
            "kb_retrieve_similar_incidents",
            "gov_request_approval",
            "gov_get_agent_permissions",
            "aws_store_incident_artifact",
        }
    ),
    R.SIGNAL_CORRELATION: frozenset(_OBS_READ),
    R.KUBERNETES_DIAGNOSTICS: frozenset(_K8S_READ | {"obs_get_recent_changes", "obs_search_logs"}),
    R.CLOUD_RESOURCE: frozenset(
        _AWS_READ | {"obs_get_dependency_errors", "obs_get_db_pool_stats", "obs_get_recent_changes"}
    ),
    R.RUNBOOK_INTELLIGENCE: frozenset({"kb_search_runbooks", "kb_get_runbook", "kb_retrieve_similar_incidents"}),
    R.ROOT_CAUSE_ANALYST: frozenset({"kb_get_runbook", "gov_create_remediation_plan"}),
    R.CHANGE_PLAN_REVIEWER: frozenset(
        {
            "kb_get_runbook",
            "gov_submit_plan_review",
            "gov_get_agent_permissions",
            "k8s_get_deployment",
            "k8s_get_deployment_history",
            "k8s_get_configmap_diff",
            "aws_get_secret_metadata",
        }
    ),
    R.REMEDIATION_EXECUTOR: frozenset(
        _MUTATIONS
        | {
            "k8s_get_deployment",
            "k8s_get_configmap_diff",
            "aws_get_secret_metadata",
            "aws_get_queue_metrics",
            "obs_get_signal",
            "obs_get_error_rate",
        }
    ),
    R.POSTMORTEM_WRITER: frozenset(
        {"aws_store_incident_artifact", "kb_save_incident_memory", "kb_retrieve_similar_incidents", "kb_get_runbook"}
    ),
}

# Tools that no agent identity may ever call.
HUMAN_ONLY_TOOLS: frozenset[str] = frozenset({"gov_record_approval"})


def is_tool_allowed(role: AgentRole, tool: str) -> bool:
    if tool in HUMAN_ONLY_TOOLS or tool not in TOOL_CATALOG:
        return False
    return tool in ROLE_TOOL_PERMISSIONS.get(role, frozenset())


def tools_for_role(role: AgentRole) -> list[str]:
    return sorted(ROLE_TOOL_PERMISSIONS.get(role, frozenset()))


def permission_matrix() -> dict[str, list[str]]:
    return {role.value: tools_for_role(role) for role in AgentRole}


def _self_check() -> None:
    for role, tools in ROLE_TOOL_PERMISSIONS.items():
        unknown = tools - TOOL_CATALOG.keys()
        if unknown:
            raise RuntimeError(f"{role}: unknown tools {sorted(unknown)}")
        mutating = {t for t in tools if TOOL_CATALOG[t].mutating}
        if mutating and role is not AgentRole.REMEDIATION_EXECUTOR:
            raise RuntimeError(f"{role} must not hold mutation tools: {sorted(mutating)}")


_self_check()
