"""Shared fixtures. Workstream-specific fixtures live in tests/<area>/conftest.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from aegisops.ports.clock import VirtualClock
from aegisops.security.tokens import KeyRing, generate_keys
from aegisops.storage.inmemory import InMemoryRepositories


@pytest.fixture
def clock() -> VirtualClock:
    return VirtualClock()


@pytest.fixture
def repos(clock: VirtualClock) -> InMemoryRepositories:
    return InMemoryRepositories(clock=clock)


@pytest.fixture
def keyring(tmp_path: Path) -> KeyRing:
    generate_keys(tmp_path / "keys")
    return KeyRing(tmp_path / "keys")
