"""Clock implementations. Production code takes a `Clock` so simulations can run on virtual time."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from aegisops.domain.common import utcnow


class SystemClock:
    def now(self) -> datetime:
        return utcnow()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class VirtualClock:
    """Deterministic clock: `sleep` advances time instantly. Used by the simulated world, tests,
    and fast evaluation runs (results produced this way are labelled as simulated)."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or utcnow()
        self._listeners: list = []

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)
        for listener in list(self._listeners):
            listener(self._now)

    def on_advance(self, listener) -> None:  # listener(now: datetime) -> None
        self._listeners.append(listener)

    async def sleep(self, seconds: float) -> None:
        self.advance(seconds)
        await asyncio.sleep(0)
