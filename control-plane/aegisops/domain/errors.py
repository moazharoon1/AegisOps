"""Domain exceptions. API handlers map them to HTTP status codes (see api/errors)."""

from __future__ import annotations


class AegisError(Exception):
    """Base class for expected, explainable failures."""


class NotFound(AegisError):  # 404
    pass


class ConflictError(AegisError):  # 409: conditional write / optimistic concurrency / duplicate
    pass


class AuthenticationFailed(AegisError):  # 401
    pass


class AuthorizationDenied(AegisError):  # 403: role, audience, approval binding, allowlist
    pass


class ValidationFailed(AegisError):  # 422
    pass


class PreconditionFailed(AegisError):  # 412: plan prerequisites / expiry / cancellation
    pass


class DependencyUnavailable(AegisError):  # 503: emulator, cluster, telemetry or storage unavailable
    pass


class BudgetExhausted(AegisError):  # model spending or tool-call budget reached
    pass
