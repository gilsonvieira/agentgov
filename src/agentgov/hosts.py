"""Host-capability ports + deterministic fakes.

The engine never reads the wall clock or a global RNG directly. Both come
through these ports so that a recorded run can be replayed bit-exact: inject
``FixedClock`` / ``SeededRng`` and the same event log reproduces the same
``state_hash``. Storage is provided for artifact/blob needs; the core loop only
requires the clock and RNG.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """UTC wall clock. Stub it for deterministic replay."""

    def now(self) -> datetime:
        """Return the current UTC datetime."""


@runtime_checkable
class Rng(Protocol):
    """Seedable randomness + id minting, routed through the host."""

    def uniform(self) -> float:
        """Return a float in ``[0.0, 1.0)``."""

    def uuid(self) -> str:
        """Return a fresh id string."""


@runtime_checkable
class Storage(Protocol):
    """Content-addressable blob storage for artifacts."""

    def put(self, key: str, blob: bytes) -> None:
        """Persist ``blob`` under ``key``."""

    def get(self, key: str) -> bytes:
        """Fetch the blob at ``key`` or raise ``KeyError``."""

    def exists(self, key: str) -> bool:
        """Return True iff a blob is stored under ``key``."""


# --------------------------------------------------------------------------- real


class SystemClock:
    """Default production clock."""

    def now(self) -> datetime:
        """Return the current UTC datetime."""
        return datetime.now(tz=UTC)


class DefaultRng:
    """Default production RNG backed by :mod:`random` + uuid4."""

    def __init__(self) -> None:
        """Seed from system entropy."""
        self._r = random.Random()

    def uniform(self) -> float:
        """Return a float in ``[0.0, 1.0)``."""
        return self._r.random()

    def uuid(self) -> str:
        """Return a fresh uuid4 string."""
        return str(uuid.uuid4())


# --------------------------------------------------------------------------- fakes


class FixedClock:
    """Deterministic clock that advances a fixed step on every read.

    Replay determinism (R5/R10) depends on event timestamps being a pure
    function of call order, not real time. Each ``now()`` returns ``start``
    plus ``step`` times the number of prior reads.
    """

    def __init__(
        self,
        start: datetime | None = None,
        *,
        step: timedelta = timedelta(seconds=1),
    ) -> None:
        """Start at ``start`` (default 2025-01-01T00:00:00Z), advancing ``step`` per read."""
        self._t = start or datetime(2025, 1, 1, tzinfo=UTC)
        self._step = step

    def now(self) -> datetime:
        """Return the current time, then advance by ``step``."""
        t = self._t
        self._t = self._t + self._step
        return t


class SeededRng:
    """Deterministic RNG. ``uuid()`` yields a reproducible uuid5 sequence."""

    _NAMESPACE = uuid.UUID("00000000-0000-0000-0000-00000000a9c0")

    def __init__(self, seed: int = 0) -> None:
        """Seed both the float stream and the id counter."""
        self._r = random.Random(seed)
        self._seed = seed
        self._n = 0

    def uniform(self) -> float:
        """Return the next deterministic float in ``[0.0, 1.0)``."""
        return self._r.random()

    def uuid(self) -> str:
        """Return the next deterministic id (uuid5 over seed + counter)."""
        u = uuid.uuid5(self._NAMESPACE, f"{self._seed}:{self._n}")
        self._n += 1
        return str(u)


class InMemoryStorage:
    """Dict-backed blob store; good enough for tests and local runs."""

    def __init__(self) -> None:
        """Initialise an empty store."""
        self._blobs: dict[str, bytes] = {}

    def put(self, key: str, blob: bytes) -> None:
        """Persist ``blob`` under ``key``."""
        self._blobs[key] = blob

    def get(self, key: str) -> bytes:
        """Fetch the blob at ``key`` or raise ``KeyError``."""
        return self._blobs[key]

    def exists(self, key: str) -> bool:
        """Return True iff a blob is stored under ``key``."""
        return key in self._blobs


__all__ = [
    "Clock",
    "DefaultRng",
    "FixedClock",
    "InMemoryStorage",
    "Rng",
    "SeededRng",
    "Storage",
    "SystemClock",
]
