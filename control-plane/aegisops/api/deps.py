"""FastAPI dependencies. The core workstream wires these to the service container on app.state."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from aegisops.domain.enums import UserRole
from aegisops.domain.models import User

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
) -> User:
    """Resolve the human user from the session bearer token (see security.tokens.KeyRing)."""
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "authentication not wired yet")


async def require_approver(user: User = Depends(get_current_user)) -> User:
    if UserRole.APPROVER not in user.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "approver role required")
    return user
