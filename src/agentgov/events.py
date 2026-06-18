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


class RunHaltedEvent(_EventBase):
    """A terminal record: an analyst halted the run at a checkpoint.

    Distinct from a step rejection. A rejected step rolls back and the agent
    re-plans; a *halt* stops the run — the bundle seals as ``terminal="halted"``
    and reads differently from a clean finalize.
    """

    type: Literal["run.halted"] = "run.halted"
    checkpoint_id: str
    trigger: str
    reason: str | None = None
    actor: str


class PlanProposedEvent(_EventBase):
    """A planner proposed a development plan (before it is gated)."""

    type: Literal["plan.proposed"] = "plan.proposed"
    plan: dict[str, Any]


class PlanAmendedEvent(_EventBase):
    """A human edited the proposed plan at the plan-review gate."""

    type: Literal["plan.amended"] = "plan.amended"
    actor: str
    reason: str | None = None
    plan: dict[str, Any]


class PlanApprovedEvent(_EventBase):
    """A human approved the (possibly amended) plan; execution may begin."""

    type: Literal["plan.approved"] = "plan.approved"
    actor: str
    reason: str | None = None
    plan: dict[str, Any]


class PlanRejectedEvent(_EventBase):
    """A human rejected the plan; the run does not execute."""

    type: Literal["plan.rejected"] = "plan.rejected"
    actor: str
    reason: str | None = None


class StageEnteredEvent(_EventBase):
    """A workflow stage was entered (its entry gate passed)."""

    type: Literal["stage.entered"] = "stage.entered"
    stage_id: str


class StageExitedEvent(_EventBase):
    """A workflow stage finished; ``status`` records how it ended."""

    type: Literal["stage.exited"] = "stage.exited"
    stage_id: str
    status: str
    reason: str | None = None


class DecisionEvent(_EventBase):
    """A decision node was resolved. ``kind`` records who decided it.

    ``kind`` is one of ``rule`` / ``search`` / ``judgment`` / ``human`` — the
    least-powerful-sufficient decider. For ``judgment``/``search`` the chosen
    args reach state only through a gated tool call (invariant I3).
    """

    type: Literal["decision.made"] = "decision.made"
    node: str
    kind: str
    provider: str
    tool: str | None = None
    chosen_args: dict[str, Any] = {}
    rationale: str | None = None


class CriticFindingEvent(_EventBase):
    """An adversarial critic reported a finding (advisory, surfaced to a human)."""

    type: Literal["critic.finding"] = "critic.finding"
    model_id: str
    severity: str
    category: str
    message: str


class FinalizeAttemptedEvent(_EventBase):
    """A finalize gate was attempted; ``outcome`` records pass/block/halt."""

    type: Literal["finalize.attempted"] = "finalize.attempted"
    outcome: Literal["succeeded", "blocked", "halted"]
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
        RunHaltedEvent,
        PlanProposedEvent,
        PlanAmendedEvent,
        PlanApprovedEvent,
        PlanRejectedEvent,
        StageEnteredEvent,
        StageExitedEvent,
        DecisionEvent,
        CriticFindingEvent,
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
    "run.halted": RunHaltedEvent,
    "plan.proposed": PlanProposedEvent,
    "plan.amended": PlanAmendedEvent,
    "plan.approved": PlanApprovedEvent,
    "plan.rejected": PlanRejectedEvent,
    "stage.entered": StageEnteredEvent,
    "stage.exited": StageExitedEvent,
    "decision.made": DecisionEvent,
    "critic.finding": CriticFindingEvent,
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
    "CriticFindingEvent",
    "DecisionEvent",
    "Event",
    "FinalizeAttemptedEvent",
    "PlanAmendedEvent",
    "PlanApprovedEvent",
    "PlanProposedEvent",
    "PlanRejectedEvent",
    "RailViolatedEvent",
    "RunHaltedEvent",
    "StageEnteredEvent",
    "StageExitedEvent",
    "StateMutationEvent",
    "ToolCommittedEvent",
    "ToolRejectedEvent",
    "ToolRequestedEvent",
    "chain_hash",
]
