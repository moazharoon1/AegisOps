"""Static knowledge about the demonstration environment and the policy boundary around it.

This is configuration, not a hint about any particular incident: it describes which resources
exist, how services depend on each other, and what AegisOps is ever allowed to change.
"""

from __future__ import annotations

from aegisops.domain.enums import ActionType, FaultType

APP_NAMESPACE = "production"
CONTROL_PLANE_NAMESPACE = "aegisops"
OBSERVABILITY_NAMESPACE = "observability"
CLOUD_SIM_NAMESPACE = "cloud-sim"
SIMULATION_NAMESPACE = "simulation"

SERVICES: tuple[str, ...] = (
    "storefront",
    "checkout-service",
    "payment-service",
    "inventory-service",
    "notification-worker",
)

# caller -> callees (HTTP) ; queue edges are listed in QUEUE_EDGES
SERVICE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "storefront": ("checkout-service", "inventory-service"),
    "checkout-service": ("inventory-service", "payment-service"),
    "payment-service": (),
    "inventory-service": ("shop-db",),
    "notification-worker": (),
}

# queue -> (producer, consumer deployment)
QUEUE_EDGES: dict[str, tuple[str, str]] = {
    "payment-events": ("checkout-service", "notification-worker"),
}
DEAD_LETTER_QUEUES: dict[str, str] = {"payment-events": "payment-events-dlq"}

# ConfigMap consumed by each deployment (envFrom)
SERVICE_CONFIGMAPS: dict[str, str] = {
    "storefront": "storefront-config",
    "checkout-service": "checkout-config",
    "payment-service": "payment-config",
    "inventory-service": "inventory-config",
    "notification-worker": "notification-config",
}

# AWS Secrets Manager secrets and the deployments that load them. The authoritative source at
# runtime is the Deployment annotation `aegisops.io/aws-secrets` (comma-separated secret names).
SECRET_CONSUMERS: dict[str, tuple[str, ...]] = {
    "shop/payment-api-key": ("checkout-service",),
}
SECRET_CONSUMERS_ANNOTATION = "aegisops.io/aws-secrets"
RESTART_ANNOTATION = "aegisops.io/restartedAt"  # value = stable execution marker

# ---------------------------------------------------------------------------- mutation allowlist
# The mutation MCP server refuses any target outside these sets (cross-namespace protection).
MUTABLE_DEPLOYMENTS: frozenset[str] = frozenset(SERVICES)
MUTABLE_CONFIGMAPS: frozenset[str] = frozenset(SERVICE_CONFIGMAPS.values())
MUTABLE_SECRETS: frozenset[str] = frozenset(SECRET_CONSUMERS)
MUTABLE_QUEUES: frozenset[str] = frozenset(QUEUE_EDGES)
MAX_REPLICAS = 10
MAX_SCALE_FACTOR = 3.0  # a scale step may at most triple desired replicas

# ---------------------------------------------------------------------------- remediation policy
# Which actions are acceptable for each diagnosed fault. The Change-Plan Reviewer enforces this
# deterministically in addition to its own assessment; humans still approve every plan.
ALLOWED_ACTIONS_BY_FAULT: dict[FaultType, frozenset[ActionType]] = {
    FaultType.BAD_DEPLOYMENT: frozenset({ActionType.ROLLOUT_UNDO}),
    FaultType.IMAGE_PULL_FAILURE: frozenset({ActionType.ROLLOUT_UNDO}),
    FaultType.QUEUE_CONSUMER_CAPACITY: frozenset({ActionType.SCALE_DEPLOYMENT}),
    FaultType.QUEUE_CONSUMER_DOWN: frozenset(
        {ActionType.SCALE_DEPLOYMENT, ActionType.ROLLOUT_UNDO, ActionType.ROLLOUT_RESTART}
    ),
    FaultType.POISON_MESSAGES: frozenset({ActionType.SET_QUEUE_REDRIVE_POLICY}),
    FaultType.INVALID_SECRET: frozenset({ActionType.RESTORE_SECRET_VERSION, ActionType.ROLLOUT_RESTART}),
    FaultType.DB_CONNECTION_EXHAUSTION: frozenset({ActionType.RESTORE_CONFIGMAP_KEY, ActionType.ROLLOUT_RESTART}),
    FaultType.BAD_CONFIGURATION: frozenset({ActionType.RESTORE_CONFIGMAP_KEY, ActionType.ROLLOUT_RESTART}),
    FaultType.NO_FAULT: frozenset(),
    FaultType.UNKNOWN: frozenset(),
}

# Explicit contraindications with explanations (surfaced in reviews and runbooks).
CONTRAINDICATIONS: dict[FaultType, dict[ActionType, str]] = {
    FaultType.DB_CONNECTION_EXHAUSTION: {
        ActionType.SCALE_DEPLOYMENT: (
            "Scaling database clients multiplies pool demand and worsens connection exhaustion."
        ),
    },
    FaultType.INVALID_SECRET: {
        ActionType.ROLLOUT_UNDO: "The deployment did not change; rolling back cannot fix an invalid credential.",
    },
    FaultType.BAD_CONFIGURATION: {
        ActionType.ROLLOUT_UNDO: (
            "A Deployment rollback does not restore an independently changed ConfigMap; restore the key."
        ),
    },
}


def neighbours(service: str) -> set[str]:
    """Services one hop away (callers, callees, and queue producer/consumer pairs)."""
    result: set[str] = set(SERVICE_DEPENDENCIES.get(service, ()))
    for caller, callees in SERVICE_DEPENDENCIES.items():
        if service in callees:
            result.add(caller)
    for producer, consumer in QUEUE_EDGES.values():
        if service == producer:
            result.add(consumer)
        if service == consumer:
            result.add(producer)
    result.discard(service)
    return result


def queue_consumer(queue: str) -> str | None:
    edge = QUEUE_EDGES.get(queue)
    return edge[1] if edge else None
