"""Hard rails: invariants checked against a candidate state before commit.

A rail is just an id plus a ``check(state) -> RailResult`` function. The runner
evaluates every rail over the post-mutation candidate and collects violations.
If any rail rejects, the executor rolls the candidate back and emits
``rail.violated`` — authoritative state is never touched.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .state import State


@dataclass(frozen=True)
class RailResult:
    """The verdict a rail returns for a candidate state."""

    ok: bool
    rail_id: str | None = None
    message: str = ""

    @classmethod
    def passed(cls) -> RailResult:
        """A clean pass."""
        return cls(ok=True)

    @classmethod
    def reject(cls, rail_id: str, message: str = "") -> RailResult:
        """A rejection attributed to ``rail_id``."""
        return cls(ok=False, rail_id=rail_id, message=message or rail_id)


@dataclass(frozen=True)
class Violation:
    """A flattened rail rejection, carried in events and results."""

    rail_id: str
    message: str


@dataclass(frozen=True)
class Rail:
    """A registered rail: a stable id bound to a check function."""

    rail_id: str
    check: Callable[[State], RailResult]
    finalize_only: bool = False


def run_rails(rails: Sequence[Rail], state: State) -> list[Violation]:
    """Run every non-finalize rail over ``state`` and collect violations."""
    return _run([r for r in rails if not r.finalize_only], state)


def run_finalize_rails(rails: Sequence[Rail], state: State) -> list[Violation]:
    """Run every rail (including finalize-only) over ``state``."""
    return _run(rails, state)


def _run(rails: Sequence[Rail], state: State) -> list[Violation]:
    violations: list[Violation] = []
    for rail in rails:
        result = rail.check(state)
        if not result.ok:
            violations.append(
                Violation(rail_id=result.rail_id or rail.rail_id, message=result.message),
            )
    return violations


__all__ = ["Rail", "RailResult", "Violation", "run_finalize_rails", "run_rails"]
