"""EdDSA (Ed25519) JWTs for the three trust relationships in AegisOps.

| Token          | Signed by (private key)  | Verified by (public key)   | Audience                    | TTL    |
|----------------|--------------------------|----------------------------|-----------------------------|--------|
| session        | API                      | API                        | aegisops-api                | 8 h    |
| service        | worker (agent identities)| MCP servers                | aegisops-mcp-<server>       | 5 min  |
| approval       | API (on human approval)  | mutation MCP server        | aegisops-mcp-mutations      | 15 min |

Verifiers hold only public keys, so a compromised MCP server cannot mint approvals or identities.
Keys live in AEGIS_KEYS_DIR as `<purpose>.pem` (private) and `<purpose>.pub.pem` (public).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from aegisops.domain.common import new_id
from aegisops.domain.enums import AgentRole, McpServerName, UserRole
from aegisops.domain.errors import AuthenticationFailed, AuthorizationDenied
from aegisops.domain.models import ApprovalClaims

Purpose = Literal["session", "service", "approval"]
PURPOSES: tuple[Purpose, ...] = ("session", "service", "approval")
ALGORITHM = "EdDSA"
LEEWAY_SECONDS = 5

SESSION_AUDIENCE = "aegisops-api"
SESSION_TTL_SECONDS = 8 * 3600
SERVICE_TTL_SECONDS = 300
APPROVAL_TTL_SECONDS = 900


def generate_keys(directory: Path, purposes: tuple[Purpose, ...] = PURPOSES, overwrite: bool = False) -> None:
    """Create Ed25519 key pairs (used by `make up` bootstrap and by tests)."""
    directory.mkdir(parents=True, exist_ok=True)
    for purpose in purposes:
        private_path = directory / f"{purpose}.pem"
        public_path = directory / f"{purpose}.pub.pem"
        if private_path.exists() and not overwrite:
            continue
        key = Ed25519PrivateKey.generate()
        private_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        private_path.chmod(0o600)
        public_path.write_bytes(
            key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        )


@dataclass
class KeyRing:
    """Loads whichever keys are present. Components are deployed with only the keys they need."""

    directory: Path

    def _private(self, purpose: Purpose) -> Ed25519PrivateKey:
        path = self.directory / f"{purpose}.pem"
        if not path.exists():
            raise AuthorizationDenied(f"signing key for '{purpose}' is not available to this component")
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        assert isinstance(key, Ed25519PrivateKey)
        return key

    def _public(self, purpose: Purpose) -> Ed25519PublicKey:
        path = self.directory / f"{purpose}.pub.pem"
        if not path.exists():
            raise AuthenticationFailed(f"verification key for '{purpose}' is not available to this component")
        key = serialization.load_pem_public_key(path.read_bytes())
        assert isinstance(key, Ed25519PublicKey)
        return key

    # ----------------------------------------------------------------- generic
    def sign(self, purpose: Purpose, claims: dict[str, Any]) -> str:
        return jwt.encode(claims, self._private(purpose), algorithm=ALGORITHM)

    def verify(self, purpose: Purpose, token: str, audience: str, issuer: str | None = None) -> dict[str, Any]:
        try:
            return jwt.decode(
                token,
                self._public(purpose),
                algorithms=[ALGORITHM],
                audience=audience,
                issuer=issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "aud", "sub", "jti"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationFailed("token expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise AuthenticationFailed("token audience mismatch") from exc
        except jwt.PyJWTError as exc:
            raise AuthenticationFailed(f"invalid token: {exc.__class__.__name__}") from exc

    # ----------------------------------------------------------------- sessions (humans)
    def issue_session(self, username: str, roles: list[UserRole], ttl: int = SESSION_TTL_SECONDS) -> tuple[str, int]:
        now = int(time.time())
        exp = now + ttl
        token = self.sign(
            "session",
            {
                "iss": "aegisops-api",
                "aud": SESSION_AUDIENCE,
                "sub": f"human:{username}",
                "roles": [r.value for r in roles],
                "iat": now,
                "exp": exp,
                "jti": new_id("SES"),
            },
        )
        return token, exp

    def verify_session(self, token: str) -> dict[str, Any]:
        claims = self.verify("session", token, SESSION_AUDIENCE, issuer="aegisops-api")
        if not str(claims.get("sub", "")).startswith("human:"):
            raise AuthenticationFailed("session subject must be a human")
        return claims

    # ----------------------------------------------------------------- service identities (agents)
    def issue_service_token(self, role: AgentRole, server: McpServerName, ttl: int = SERVICE_TTL_SECONDS) -> str:
        now = int(time.time())
        return self.sign(
            "service",
            {
                "iss": "aegisops-worker",
                "aud": server.audience,
                "sub": f"agent:{role.value}",
                "role": role.value,
                "iat": now,
                "exp": now + ttl,
                "jti": new_id("SVC"),
            },
        )

    def verify_service_token(self, token: str, server: McpServerName) -> AgentRole:
        claims = self.verify("service", token, server.audience, issuer="aegisops-worker")
        sub = str(claims.get("sub", ""))
        role_value = str(claims.get("role", ""))
        if sub != f"agent:{role_value}":
            raise AuthenticationFailed("service token subject/role mismatch")
        try:
            return AgentRole(role_value)
        except ValueError as exc:
            raise AuthenticationFailed("unknown agent role") from exc

    # ----------------------------------------------------------------- approvals
    def issue_approval_token(
        self,
        *,
        approver: str,
        incident_id: str,
        plan_id: str,
        plan_hash: str,
        approval_id: str,
        execution_id: str,
        ttl: int = APPROVAL_TTL_SECONDS,
    ) -> tuple[str, ApprovalClaims]:
        now = int(time.time())
        claims = ApprovalClaims(
            sub=f"human:{approver}",
            jti=new_id("JTI"),
            iat=now,
            exp=now + ttl,
            incident_id=incident_id,
            plan_id=plan_id,
            plan_hash=plan_hash,
            approval_id=approval_id,
            execution_id=execution_id,
        )
        return self.sign("approval", claims.model_dump()), claims

    def verify_approval_token(self, token: str) -> ApprovalClaims:
        audience = McpServerName.MUTATIONS.audience
        claims = self.verify("approval", token, audience, issuer="aegisops-api")
        if not str(claims.get("sub", "")).startswith("human:"):
            raise AuthorizationDenied("approval tokens must be issued for a human approver")
        return ApprovalClaims.model_validate(claims)
