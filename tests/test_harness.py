"""Harness-level behavior: artifacts persist across calls, state does not leak."""

from __future__ import annotations

from agentgov import (
    FixedClock,
    Harness,
    Mutation,
    Registry,
    Result,
    SeededRng,
)
from pydantic import BaseModel


class A(BaseModel):
    key: str


def _harness() -> Harness:
    return Harness(
        app="t",
        registry=Registry(),
        clock=FixedClock(),
        rng=SeededRng(),
        session_id="s",
    )


def test_artifacts_persist_across_calls():
    hz = _harness()

    @hz.tool(args=A, result=A, layer="action")
    def stash(args, ctx) -> Result[A]:
        # A non-serializable runtime object that must survive to the next call.
        ctx.artifacts[args.key] = object()
        return Result(A(key=args.key), mutations=[Mutation.set(f"seen.{args.key}", True)])

    @hz.tool(args=A, result=A, layer="action")
    def read(args, ctx) -> Result[A]:
        assert args.key in ctx.artifacts  # set by the previous call
        return Result(A(key=args.key))

    assert hz.call("stash", {"key": "model"}).ok
    assert hz.call("read", {"key": "model"}).ok
    assert "model" in hz.artifacts
