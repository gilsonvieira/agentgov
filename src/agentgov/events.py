"""Generic, hash-chained event log entries.

Every governed call produces a stream of these. They are frozen, JSON-round-
trippable pydantic models in a discriminated union keyed on ``type``. The
``seq`` / ``prev_hash`` / ``event_hash`` fields form a tamper-evident chain:
each event's hash folds in the previous event's hash, so a reader can verify
the log was not edited after the fact. The writer (:mod:`agentgov.eventlog`)
assigns those three fields at append time; tool code never sets them.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

_CHAIN_FIELDS = ("seq", "prev_hash", "event_hash")


class _EventBase(BaseModel):
    """Shared frozen config + correlation + chain fields for every event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    session_id: str
    turn_id: str
    timestamp: datetime
    correlation_ids: tuple[str, ...] = ()
    # Chain fields — populated by the writer, not the caller.
    seq: int = -1
    prev_hash: str | None = None
    event_hash: str | None = None


class ToolRequestedEvent(_EventBase):
    """A tool body was invoked (before commit/reject is known)."""

    type: Literal["tool.requested"] = "tool.requested"
    tool_name: str
    layer: str
    args_hash: str


class ToolCommittedEvent(_EventBase):
    """A tool call passed all rails and its mutations were committed."""

    type: Literal["tool.committed"] = "tool.committed"
    tool_name: str
    layer: str
    args_hash: str
    result_hash: str
    duration_ms: float = Field(ge=0)


class ToolRejectedEvent(_EventBase):
    """A tool call failed validation or rails; state was rolled back."""

    type: Literal["tool.rejected"] = "tool.rejected"
    tool_name: str
    layer: str
    args_hash: str
    error_kind: str
    error_message: str
    duration_ms: float = Field(ge=0)


class RailViolatedEvent(_EventBase):
    """A hard rail rejected the candidate state."""

    type: Literal["rail.violated"] = "rail.violated"
    rail_id: str
    message: str
    tool_call_id: str | None = None


class StateMutationEvent(_EventBase):
    """One committed mutation. Replay folds these to rebuild state."""

    type: Literal["state.mutation"] = "state.mutation"
    tool_call_id: str
    op: str
    path: str
    value: Any = None


class CheckpointRequestedEvent(_EventBase):
    """A human checkpoint was raised and is awaiting a decision."""

    type: Literal["checkpoint.requested"] = "checkpoint.requested"
    checkpoint_id: str
    trigger: str
    proposal: str


class CheckpointDecidedEvent(_EventBase):
    """A human checkpoint was resolved."""

    type: Literal["checkpoint.decided"] = "checkpoint.decided"
    checkpoint_id: str
    decision: str
    reason: str | None = None
    actor: str


class FinalizeAttemptedEvent(_EventBase):
    """A finalize gate was attempted; ``outcome`` records pass/block."""

    type: Literal["finalize.attempted"] = "finalize.attempted"
    outcome: Literal["succeeded", "blocked"]
    blocking_rail_ids: tuple[str, ...] = ()


Event = Annotated[
    Union[  # noqa: UP007
        ToolRequestedEvent,
        ToolCommittedEvent,
        ToolRejectedEvent,
        RailViolatedEvent,
        StateMutationEvent,
        CheckpointRequestedEvent,
        CheckpointDecidedEvent,
        FinalizeAttemptedEvent,
    ],
    Field(discriminator="type"),
]

EVENT_TYPES: dict[str, type[_EventBase]] = {
    "tool.requested": ToolRequestedEvent,
    "tool.committed": ToolCommittedEvent,
    "tool.rejected": ToolRejectedEvent,
    "rail.violated": RailViolatedEvent,
    "state.mutation": StateMutationEvent,
    "checkpoint.requested": CheckpointRequestedEvent,
    "checkpoint.decided": CheckpointDecidedEvent,
    "finalize.attempted": FinalizeAttemptedEvent,
}


def chain_hash(prev_hash: str | None, payload: dict[str, Any]) -> str:
    """Fold ``prev_hash`` into a hash of the event payload (chain fields removed)."""
    body = {k: v for k, v in payload.items() if k not in _CHAIN_FIELDS}
    blob = json.dumps(
        {"prev": prev_hash, "body": body},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.blake2b(blob.encode("utf-8"), digest_size=16).hexdigest()


__all__ = [
    "EVENT_TYPES",
    "CheckpointDecidedEvent",
    "CheckpointRequestedEvent",
    "Event",
    "FinalizeAttemptedEvent",
    "RailViolatedEvent",
    "StateMutationEvent",
    "ToolCommittedEvent",
    "ToolRejectedEvent",
    "ToolRequestedEvent",
    "chain_hash",
]
