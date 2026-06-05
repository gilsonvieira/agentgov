"""Checkpoints gate commits and emit requested/decided events."""

from __future__ import annotations

from agentgov import (
    ApproveAll,
    DenyAll,
    FixedClock,
    Harness,
    InMemoryEventLog,
    Mutation,
    Registry,
    Result,
    SeededRng,
)
from pydantic import BaseModel


class A(BaseModel):
    amount: float


def _harness(responder):
    log = InMemoryEventLog()
    hz = Harness(
        app="t",
        registry=Registry(),
        log=log,
        clock=FixedClock(),
        rng=SeededRng(),
        responder=responder,
        session_id="s",
    )

    @hz.tool(args=A, result=A, layer="action")
    def big(args, ctx) -> Result[A]:
        ctx.checkpoint(trigger="big", proposal=f"spend {args.amount}")
        rid = ctx.rng.uuid()
        return Result(A(amount=args.amount), mutations=[Mutation.set(f"x.{rid}", args.amount)])

    return hz, log


def test_approved_checkpoint_commits():
    hz, log = _harness(ApproveAll())
    r = hz.call("big", {"amount": 5})
    assert r.ok
    types = [e.type for e in log.events()]
    assert "checkpoint.requested" in types
    assert "checkpoint.decided" in types
    assert "tool.committed" in types


def test_denied_checkpoint_blocks_and_rolls_back():
    hz, log = _harness(DenyAll())
    r = hz.call("big", {"amount": 5})
    assert not r.ok
    assert r.error.kind == "checkpoint_pending"
    assert hz.state == {}
    types = [e.type for e in log.events()]
    assert "checkpoint.requested" in types
    assert "tool.rejected" in types


def test_no_responder_blocks():
    hz, log = _harness(None)
    r = hz.call("big", {"amount": 5})
    assert not r.ok
    assert r.error.kind == "checkpoint_pending"
    assert hz.state == {}
