"""Identifiers, time, canonical JSON and hashing helpers shared by all components."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from ulid import ULID


def utcnow() -> datetime:
    """Timezone-aware UTC now. Components that need a controllable clock use `ports.clock.Clock`."""
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    """Sortable unique identifier, e.g. `EV-01J9Z3...`. ULIDs sort by creation time."""
    return f"{prefix}-{ULID()}"


# Identifier prefixes (incidents use a human-friendly counter: INC-1042).
ID_PREFIX = {
    "incident": "INC",
    "evidence": "EV",
    "finding": "FND",
    "diagnosis": "DX",
    "plan": "PLAN",
    "review": "REV",
    "approval": "APR",
    "execution": "EXE",
    "memory": "MEM",
    "audit": "AUD",
    "timeline": "EVT",
    "change": "CHG",
    "snapshot": "SNAP",
    "report": "RPT",
    "outbox": "OBX",
    "agent_run": "RUN",
    "alert": "ALR",
}


def format_incident_id(number: int) -> str:
    return f"INC-{number}"


def _default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):  # enums
        return value.value
    raise TypeError(f"not JSON serialisable: {type(value)!r}")


def canonical_json(value: Any) -> str:
    """Deterministic JSON (sorted keys, no whitespace) used for hashing and signatures."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default)


def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def content_hash(value: Any) -> str:
    """`sha256:<hex>` over the canonical JSON form of `value`."""
    return "sha256:" + sha256_hex(canonical_json(value))
