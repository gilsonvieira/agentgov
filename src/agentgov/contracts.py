"""Tool contracts: the typed inputs/outputs and structured errors.

A tool declares a pydantic ``args`` model and a ``result`` model. Its body
returns a :class:`Result` carrying the typed result plus the mutations it wants
applied. Everything the executor needs to validate the call lives in
:class:`ToolSpec`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from .rails import Violation
from .state import Mutation

if TYPE_CHECKING:
    from .context import ToolContext


@dataclass(frozen=True)
class Result[R: BaseModel]:
    """What a tool body returns: a typed result plus requested mutations."""

    value: R
    mutations: tuple[Mutation, ...] = ()

    def __init__(self, value: R, mutations: Any = ()) -> None:
        """Accept ``mutations`` as any iterable for ergonomics, store a tuple."""
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "mutations", tuple(mutations))


@dataclass(frozen=True)
class ToolSpec[A: BaseModel, R: BaseModel]:
    """Metadata about a registered tool."""

    name: str
    layer: str
    args_model: type[A]
    result_model: type[R]
    fn: Callable[[A, "ToolContext"], Result[R]]
    rails: tuple[str, ...] = field(default=())


class ToolError(Exception):
    """Base class for structured tool failures."""

    kind = "tool_error"


class PreconditionError(ToolError):
    """A tool refused to run because a precondition was not met."""

    kind = "precondition"

    def __init__(self, message: str, violations: tuple[Violation, ...] = ()) -> None:
        """Carry optional rail-style violations alongside the message."""
        super().__init__(message)
        self.violations = violations


class PostconditionError(ToolError):
    """A tool returned a value that did not match its declared result model."""

    kind = "postcondition"


class RailViolation(ToolError):
    """A hard rail rejected the candidate state."""

    kind = "rail_violation"

    def __init__(self, rail_id: str, message: str) -> None:
        """Record the rejecting rail id and message."""
        super().__init__(f"{rail_id}: {message}")
        self.rail_id = rail_id
        self.message = message


class CheckpointPending(ToolError):
    """A tool raised a human checkpoint that has not been decided."""

    kind = "checkpoint_pending"


class RunHalted(ToolError):
    """An analyst halted the whole run at a checkpoint.

    A *reject step* (``CheckpointPending`` / ``RailViolation``) rolls back and
    the agent re-plans. A *halt* is terminal: the harness records a
    ``run.halted`` event and the run stops. The triggering step still rolls
    back (its body never returned), but the outcome is the end of the run, not
    a retry. The harness reads these attributes to emit the terminal record.
    """

    kind = "run_halted"

    def __init__(
        self,
        *,
        checkpoint_id: str,
        trigger: str,
        actor: str,
        reason: str | None = None,
    ) -> None:
        """Carry the checkpoint identity and the analyst's decision metadata."""
        super().__init__(f"run halted at checkpoint {trigger!r} by {actor}")
        self.checkpoint_id = checkpoint_id
        self.trigger = trigger
        self.actor = actor
        self.reason = reason


__all__ = [
    "CheckpointPending",
    "PostconditionError",
    "PreconditionError",
    "RailViolation",
    "Result",
    "RunHalted",
    "ToolError",
    "ToolSpec",
]
