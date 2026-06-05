"""Shared fixtures: a deterministic harness builder."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from agentgov import (
    FixedClock,
    Harness,
    InMemoryEventLog,
    Mutation,
    RailResult,
    Registry,
    Result,
    SeededRng,
)


class Args(BaseModel):
    """Test tool args."""

    amount: float = Field(gt=0)


class Out(BaseModel):
    """Test tool result."""

    id: str


class WrongOut(BaseModel):
    """A result type the executor should reject as a postcondition failure."""

    nope: bool = True


@pytest.fixture
def make_harness():
    """Return a factory for deterministic, isolated harnesses."""

    def _make(*, mode="enforce", responder=None, cap=1000.0):
        hz = Harness(
            app="test",
            mode=mode,
            registry=Registry(),
            log=InMemoryEventLog(),
            clock=FixedClock(),
            rng=SeededRng(seed=7),
            responder=responder,
            session_id="sess-1",
        )

        @hz.tool(args=Args, result=Out, layer="action")
        def add(args: Args, ctx) -> Result[Out]:
            rid = ctx.rng.uuid()
            return Result(Out(id=rid), mutations=[Mutation.set(f"items.{rid}", args.amount)])

        @hz.tool(args=Args, result=Out, layer="action")
        def bad_result(args: Args, ctx) -> Result[Out]:
            return Result(WrongOut())  # type: ignore[arg-type]

        @hz.rail(id="cap")
        def cap_rail(state) -> RailResult:
            total = sum(state.get("items", {}).values())
            return RailResult.reject("cap", "over cap") if total > cap else RailResult.passed()

        return hz

    return _make
