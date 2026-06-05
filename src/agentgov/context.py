"""Per-call context handed to every tool body.

``state`` is a read-only view for the tool (it returns mutations rather than
writing). ``clock`` and ``rng`` are the host ports — tools must pull time and
randomness from here, never from the stdlib directly, so runs stay replayable.
``artifacts`` is ephemeral scratch space that never enters the event log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .hosts import Clock, DefaultRng, Rng, SystemClock
from .state import State


@dataclass
class ToolContext:
    """Context passed as the second argument to every tool body ``(args, ctx)``."""

    state: State
    clock: Clock = field(default_factory=SystemClock)
    rng: Rng = field(default_factory=DefaultRng)
    artifacts: dict[str, Any] = field(default_factory=dict)
    session_id: str = "session-anon"
    turn_id: str = "turn-anon"

    def checkpoint(self, *, trigger: str, proposal: str) -> Any:
        """Raise a human checkpoint. Bound by the harness at call time.

        Unbound (the default) it raises, so a tool that needs a checkpoint
        fails loudly outside a harness rather than silently skipping the gate.
        """
        raise RuntimeError(
            "ctx.checkpoint() is only available inside Harness.call()",
        )


__all__ = ["ToolContext"]
