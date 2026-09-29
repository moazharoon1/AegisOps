from __future__ import annotations

import pytest
from pydantic import ValidationError

from aegisops.domain.common import new_id
from aegisops.domain.enums import (
    ActionType,
    AgentRole,
    Comparator,
    FaultType,
    IncidentStatus,
    McpServerName,
    ResourceKind,
    RiskLevel,
    UserRole,
    VerificationSignal,
)
from aegisops.domain.errors import AuthenticationFailed
from aegisops.domain.lifecycle import InvalidTransition, assert_transition, can_transition
from aegisops.domain.models import PlanStep, RemediationPlan, VerificationCheck, VerificationSpec
from aegisops.domain.permissions import HUMAN_ONLY_TOOLS, is_tool_allowed, tools_for_role
from aegisops.domain.resources import ResourceRef
from aegisops.domain.tools import TOOL_CATALOG
from aegisops.security.redaction import contains_canary, redact


def make_plan(**overrides) -> RemediationPlan:
    step = PlanStep(
        step_id="step-1",
        action=ActionType.ROLLOUT_UNDO,
        target=ResourceRef(kind=ResourceKind.DEPLOYMENT, name="checkout-service", namespace="production"),
        params={"to_revision": 3},
        rationale="revision 4 crashes on startup",
        expected_outcome="ready replicas return to 2",
    )
    verification = VerificationSpec(
        checks=[
            VerificationCheck(
                check_id="c1",
                signal=VerificationSignal.ERROR_RATE,
                target="checkout-service",
                comparator=Comparator.LT,
                threshold=0.02,
                description="errors < 2%",
            )
        ]
    )
    data = dict(
        plan_id=new_id("PLAN"),
        incident_id="INC-1001",
        revision=1,
        diagnosis_id="DX-1",
        fault_type=FaultType.BAD_DEPLOYMENT,
        title="Roll back checkout",
        summary="s",
        steps=[step],
        verification=verification,
        risk=RiskLevel.MEDIUM,
        risk_rationale="r",
        expected_recovery="e",
    )
    data.update(overrides)
    return RemediationPlan(**data).sealed()


def test_plan_hash_detects_tampering():
    plan = make_plan()
    assert plan.hash_is_valid()
    tampered = plan.model_copy(deep=True)
    tampered.steps[0].params["to_revision"] = 1
    assert not tampered.hash_is_valid()
    # status/review changes do not alter the approved content hash
    assert plan.model_copy(update={"status": "approved"}).hash_is_valid()


def test_plan_step_validates_target_kind_and_params():
    with pytest.raises(ValidationError):
        PlanStep(
            step_id="step-1",
            action=ActionType.ROLLOUT_UNDO,
            target=ResourceRef(kind=ResourceKind.CONFIGMAP, name="x", namespace="production"),
            params={"to_revision": 1},
            rationale="r",
            expected_outcome="e",
        )
    with pytest.raises(ValidationError):
        PlanStep(
            step_id="step-1",
            action=ActionType.SCALE_DEPLOYMENT,
            target=ResourceRef(kind=ResourceKind.DEPLOYMENT, name="x", namespace="production"),
            params={"replicas": 50, "from_replicas": 2},
            rationale="r",
            expected_outcome="e",
        )


def test_lifecycle():
    assert can_transition(IncidentStatus.RECEIVED, IncidentStatus.INVESTIGATING)
    assert not can_transition(IncidentStatus.RESOLVED, IncidentStatus.INVESTIGATING)
    with pytest.raises(InvalidTransition):
        assert_transition(IncidentStatus.INVESTIGATING, IncidentStatus.RESOLVED)


def test_permissions_least_privilege():
    mutations = {n for n, s in TOOL_CATALOG.items() if s.mutating}
    for role in AgentRole:
        held = set(tools_for_role(role)) & mutations
        assert not held or role is AgentRole.REMEDIATION_EXECUTOR
    assert not any(is_tool_allowed(role, t) for role in AgentRole for t in HUMAN_ONLY_TOOLS)
    assert not is_tool_allowed(AgentRole.KUBERNETES_DIAGNOSTICS, "k8s_rollout_undo")
    assert is_tool_allowed(AgentRole.KUBERNETES_DIAGNOSTICS, "k8s_list_pods")


def test_tokens_roundtrip_and_audience(keyring):
    token = keyring.issue_service_token(AgentRole.KUBERNETES_DIAGNOSTICS, McpServerName.DIAGNOSTICS)
    assert keyring.verify_service_token(token, McpServerName.DIAGNOSTICS) is AgentRole.KUBERNETES_DIAGNOSTICS
    with pytest.raises(AuthenticationFailed):
        keyring.verify_service_token(token, McpServerName.MUTATIONS)
    approval, claims = keyring.issue_approval_token(
        approver="alice",
        incident_id="INC-1",
        plan_id="PLAN-1",
        plan_hash="sha256:x",
        approval_id="APR-1",
        execution_id="EXE-1",
    )
    assert keyring.verify_approval_token(approval).execution_id == "EXE-1"
    session, _ = keyring.issue_session("alice", [UserRole.APPROVER])
    with pytest.raises(AuthenticationFailed):  # a session token is not an approval
        keyring.verify_approval_token(session)


def test_redaction_removes_canary_and_credentials():
    payload = {
        "msg": "auth failed for key sk_canary_ABC123def",
        "api_key": "abc",
        "secret_id": "shop/payment-api-key",
        "url": "postgresql://shop:hunter2@shop-db:5432/shop",
        "n": 3,
    }
    red, count = redact(payload)
    assert not contains_canary(str(red))
    assert red["api_key"] == "[REDACTED]" and red["secret_id"] == "shop/payment-api-key"
    assert "hunter2" not in red["url"] and red["n"] == 3 and count >= 3
