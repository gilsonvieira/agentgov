"""The atomic transaction boundary.

This is the heart of the engine. It is fully domain-agnostic: the reducer is
the generic :func:`agentgov.state.apply`, and rails are passed in rather than
imported. The lifecycle is exact:

    validate args -> run body -> validate result -> apply mutations to a
    *candidate* -> run rails over the candidate -> commit + emit
    ``tool.committed`` on pass, or roll back + emit ``rail.violated`` +
    ``tool.rejected`` on fail.

Authoritative state (``ctx.state``) is never mutated by a tool body. In
``observe`` mode, rail rejections are logged but do not block the commit.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from .context import ToolContext
from .contracts import PostconditionError, Result, ToolError, ToolSpec
from .eventlog import InMemoryEventLog, JsonlEventLog
from .events import (
    RailViolatedEvent,
    StateMutationEvent,
    ToolCommittedEvent,
    ToolRejectedEvent,
    ToolRequestedEvent,
)
from .rails import Rail, Violation, run_rails
from .state import apply

Mode = Literal["enforce", "observe"]
EventLog = InMemoryEventLog | JsonlEventLog


@dataclass(frozen=True)
class ToolRunResult[R: BaseModel]:
    """Outcome of one atomic tool execution."""

    ok: bool
    result: R | None
    state: dict[str, Any]
    error: ToolError | None
    violations: tuple[Violation, ...]


def _hash_model(model: BaseModel) -> str:
    payload = json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=16).hexdigest()


def run_tool[A: BaseModel, R: BaseModel](
    spec: ToolSpec[A, R],
    args: A | dict[str, Any],
    ctx: ToolContext,
    *,
    rails: Sequence[Rail] = (),
    log: EventLog | None = None,
    mode: Mode = "enforce",
) -> ToolRunResult[R]:
    """Execute ``spec`` under the atomic governance contract."""
    validated: A = args if isinstance(args, spec.args_model) else spec.args_model.model_validate(args)
    args_hash = _hash_model(validated)
    tool_call_id = ctx.rng.uuid()
    start = time.perf_counter()

    def base() -> dict[str, Any]:
        return {
            "event_id": ctx.rng.uuid(),
            "session_id": ctx.session_id,
            "turn_id": ctx.turn_id,
            "timestamp": ctx.clock.now(),
        }

    def emit(event: Any) -> None:
        if log is not None:
            log.emit(event)

    emit(
        ToolRequestedEvent(
            **base(), tool_name=spec.name, layer=spec.layer, args_hash=args_hash
        )
    )

    def reject(error: ToolError, violations: tuple[Violation, ...] = ()) -> ToolRunResult[R]:
        duration = (time.perf_counter() - start) * 1000
        for v in violations:
            emit(RailViolatedEvent(**base(), rail_id=v.rail_id, message=v.message, tool_call_id=tool_call_id))
        emit(
            ToolRejectedEvent(
                **base(),
                tool_name=spec.name,
                layer=spec.layer,
                args_hash=args_hash,
                error_kind=error.kind,
                error_message=str(error),
                duration_ms=duration,
            )
        )
        return ToolRunResult(False, None, ctx.state, error, violations)

    try:
        output: Result[R] = spec.fn(validated, ctx)
    except ToolError as te:
        return reject(te, getattr(te, "violations", ()))

    if not isinstance(output.value, spec.result_model):
        err = PostconditionError(
            f"tool {spec.name!r} returned {type(output.value).__name__}, "
            f"expected {spec.result_model.__name__}"
        )
        return reject(err)

    candidate = copy.deepcopy(ctx.state)
    for mutation in output.mutations:
        apply(candidate, mutation)

    violations = tuple(run_rails(rails, candidate))
    if violations and mode == "enforce":
        from .contracts import RailViolation

        return reject(RailViolation(violations[0].rail_id, violations[0].message), violations)

    # Commit. In observe mode we commit even with violations, but still log them.
    if violations:  # observe mode
        for v in violations:
            emit(RailViolatedEvent(**base(), rail_id=v.rail_id, message=v.message, tool_call_id=tool_call_id))

    ctx.state = candidate
    for mutation in output.mutations:
        emit(
            StateMutationEvent(
                **base(),
                tool_call_id=tool_call_id,
                op=mutation.op,
                path=mutation.path,
                value=mutation.value,
            )
        )
    duration = (time.perf_counter() - start) * 1000
    emit(
        ToolCommittedEvent(
            **base(),
            tool_name=spec.name,
            layer=spec.layer,
            args_hash=args_hash,
            result_hash=_hash_model(output.value),
            duration_ms=duration,
        )
    )
    return ToolRunResult(True, output.value, candidate, None, violations)


__all__ = ["EventLog", "Mode", "ToolRunResult", "run_tool"]
