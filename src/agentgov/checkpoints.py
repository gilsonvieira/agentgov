"""Human-in-the-loop checkpoints.

A tool calls ``ctx.checkpoint(trigger=..., proposal=...)`` to pause for a human
(or a scripted stand-in) before doing something consequential. The harness
emits a ``checkpoint.requested`` event, asks the responder, and emits
``checkpoint.decided``. If there is no responder or the decision is to block,
the tool call is rejected and its mutations roll back — the gate holds.

A decision can also *halt* the run (``decision`` of ``"halt"``/``"stop"``/
``"abort"``): the step still rolls back, but instead of letting the agent
re-plan, the harness records a terminal ``run.halted`` event and stops. See
:attr:`CheckpointDecision.halt`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CheckpointDecision:
    """A responder's verdict on a checkpoint."""

    decision: str
    actor: str
    reason: str | None = None

    @property
    def approved(self) -> bool:
        """True iff the decision green-lights the proposed action."""
        return self.decision.lower() in {"approve", "approved", "allow", "yes"}

    @property
    def halt(self) -> bool:
        """True iff the analyst chose to halt the whole run (not just reject the step)."""
        return self.decision.lower() in {"halt", "stop", "abort"}


@runtime_checkable
class CheckpointResponder(Protocol):
    """Maps a checkpoint (trigger + proposal) to a decision."""

    def respond(self, *, checkpoint_id: str, trigger: str, proposal: str) -> CheckpointDecision:
        """Return the decision a human (or stand-in) made."""


def checkpoint_id(trigger: str, proposal: str) -> str:
    """Deterministic id derived from the checkpoint's trigger + proposal."""
    h = hashlib.blake2b(digest_size=16)
    for part in ("checkpoint", trigger, proposal):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class ApproveAll:
    """Test/demo responder that approves every checkpoint."""

    def __init__(self, actor: str = "auto") -> None:
        """Record the actor name stamped on each decision."""
        self._actor = actor

    def respond(self, *, checkpoint_id: str, trigger: str, proposal: str) -> CheckpointDecision:
        """Approve unconditionally."""
        return CheckpointDecision(decision="approve", actor=self._actor, reason="auto-approved")


class DenyAll:
    """Test/demo responder that blocks every checkpoint."""

    def __init__(self, actor: str = "auto") -> None:
        """Record the actor name stamped on each decision."""
        self._actor = actor

    def respond(self, *, checkpoint_id: str, trigger: str, proposal: str) -> CheckpointDecision:
        """Deny unconditionally."""
        return CheckpointDecision(decision="deny", actor=self._actor, reason="auto-denied")


__all__ = [
    "ApproveAll",
    "CheckpointDecision",
    "CheckpointResponder",
    "DenyAll",
    "checkpoint_id",
]
