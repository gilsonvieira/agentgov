"""Halting a run at a checkpoint is terminal — distinct from rejecting a step.

A *reject step* rolls back and lets the agent re-plan (see test_checkpoints).
A *halt* stops the run: a terminal ``run.halted`` event is logged, further
calls are refused, and the bundle seals with ``terminal="halted"``.
"""

from __future__ import annotations

from agentgov import (
    CheckpointDecision,
    FixedClock,
    Harness,
    InMemoryEventLog,
    Mutation,
    Registry,
    Result,
    SeededRng,
    verify_bundle,
)
from pydantic import BaseModel


class A(BaseModel):
    amount: float


class HaltAll:
    """Responder that halts the run on every checkpoint."""

    def respond(self, *, checkpoint_id, trigger, proposal) -> CheckpointDecision:
        return CheckpointDecision(decision="halt", actor="analyst", reason="not remediable")


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
        ctx.checkpoint(trigger="fairness_review", proposal=f"spend {args.amount}")
        rid = ctx.rng.uuid()
        return Result(A(amount=args.amount), mutations=[Mutation.set(f"x.{rid}", args.amount)])

    @hz.tool(args=A, result=A, layer="action")
    def plain(args, ctx) -> Result[A]:
        rid = ctx.rng.uuid()
        return Result(A(amount=args.amount), mutations=[Mutation.set(f"y.{rid}", args.amount)])

    return hz, log


def test_halt_rolls_back_the_step_and_marks_the_run_halted():
    hz, log = _harness(HaltAll())
    r = hz.call("big", {"amount": 5})
    assert not r.ok
    assert r.error.kind == "run_halted"
    assert hz.state == {}          # the triggering step rolled back
    assert hz.halted is True
    types = [e.type for e in log.events()]
    assert "checkpoint.requested" in types
    assert "checkpoint.decided" in types
    assert "tool.rejected" in types
    assert "run.halted" in types   # terminal record, distinct from the step rejection
    halted = next(e for e in log.events() if e.type == "run.halted")
    assert halted.trigger == "fairness_review"
    assert halted.actor == "analyst"
    assert halted.reason == "not remediable"


def test_halted_run_refuses_further_calls():
    hz, _ = _harness(HaltAll())
    hz.call("big", {"amount": 5})
    # A later call on a halted run must not advance state.
    r = hz.call("plain", {"amount": 1})
    assert not r.ok
    assert r.error.kind == "run_halted"
    assert hz.state == {}


def test_finalize_after_halt_seals_a_halted_bundle():
    hz, _ = _harness(HaltAll())
    hz.call("big", {"amount": 5})
    fr = hz.finalize()
    assert fr.ok is False          # a halted run is not a clean promotion
    assert fr.bundle is not None   # but the evidence record is still sealed
    assert fr.bundle.terminal == "halted"
    assert verify_bundle(fr.bundle)


def test_explicit_reason_halted_seals_a_halted_bundle():
    # finalize(reason="halted") works even without a checkpoint-driven halt.
    hz, _ = _harness(HaltAll())
    hz.call("plain", {"amount": 2})  # commits; run not auto-halted
    fr = hz.finalize(reason="halted")
    assert fr.ok is False
    assert fr.bundle is not None
    assert fr.bundle.terminal == "halted"
    assert verify_bundle(fr.bundle)
