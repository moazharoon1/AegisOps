"""Incident lifecycle: received -> investigating -> awaiting_approval -> executing -> verifying -> resolved.

Uncertainty, rejected plans, unavailable dependencies or failed recovery lead to `needs_attention`.
Cancellation is explicit. Alert clearance alone never resolves an incident.
"""

from __future__ import annotations

from aegisops.domain.enums import IncidentStatus as S

ALLOWED_TRANSITIONS: dict[S, frozenset[S]] = {
    S.RECEIVED: frozenset({S.INVESTIGATING, S.NEEDS_ATTENTION, S.CANCELLED}),
    # investigating -> investigating is a second investigation pass
    S.INVESTIGATING: frozenset({S.INVESTIGATING, S.AWAITING_APPROVAL, S.NEEDS_ATTENTION, S.CANCELLED}),
    # awaiting_approval -> investigating when a human requests a plan revision
    S.AWAITING_APPROVAL: frozenset({S.EXECUTING, S.INVESTIGATING, S.NEEDS_ATTENTION, S.CANCELLED}),
    S.EXECUTING: frozenset({S.VERIFYING, S.NEEDS_ATTENTION, S.CANCELLED}),
    S.VERIFYING: frozenset({S.RESOLVED, S.NEEDS_ATTENTION}),
    # a human may re-open investigation, cancel, or close with an explicit manual resolution
    S.NEEDS_ATTENTION: frozenset({S.INVESTIGATING, S.RESOLVED, S.CANCELLED}),
    S.RESOLVED: frozenset(),
    S.CANCELLED: frozenset(),
}


class InvalidTransition(ValueError):
    def __init__(self, current: S, target: S) -> None:
        super().__init__(f"illegal incident transition {current.value} -> {target.value}")
        self.current = current
        self.target = target


def can_transition(current: S, target: S) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def assert_transition(current: S, target: S) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(current, target)
