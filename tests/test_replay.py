"""Replay determinism + tamper-evident hash chain."""

from __future__ import annotations

from agentgov import (
    FixedClock,
    Harness,
    InMemoryEventLog,
    JsonlEventLog,
    Mutation,
    RailResult,
    Registry,
    Result,
    SeededRng,
    replay,
    replay_from_jsonl,
    state_hash,
    verify_chain,
)
from pydantic import BaseModel


class A(BaseModel):
    amount: float


def _run(log):
    hz = Harness(
        app="t",
        registry=Registry(),
        log=log,
        clock=FixedClock(),
        rng=SeededRng(seed=42),
        session_id="s",
    )

    @hz.tool(args=A, result=A, layer="action")
    def add(args, ctx) -> Result[A]:
        rid = ctx.rng.uuid()
        return Result(A(amount=args.amount), mutations=[Mutation.set(f"items.{rid}", args.amount)])

    @hz.rail(id="noop")
    def noop(state) -> RailResult:
        return RailResult.passed()

    for amt in (10, 20, 30):
        hz.call("add", {"amount": amt})
    return hz


def test_replay_reproduces_state_hash():
    log = InMemoryEventLog()
    hz = _run(log)
    rebuilt = replay(log.events())
    assert state_hash(rebuilt) == state_hash(hz.state)


def test_two_seeded_runs_are_byte_identical():
    h1 = state_hash(_run(InMemoryEventLog()).state)
    h2 = state_hash(_run(InMemoryEventLog()).state)
    assert h1 == h2


def test_chain_verifies():
    log = InMemoryEventLog()
    _run(log)
    assert verify_chain(log.events())


def test_tampered_chain_fails():
    log = InMemoryEventLog()
    _run(log)
    events = list(log.events())
    # Tamper with a committed event's payload after the fact.
    idx = next(i for i, e in enumerate(events) if e.type == "state.mutation")
    events[idx] = events[idx].model_copy(update={"value": 9999})
    assert not verify_chain(events)


def test_jsonl_roundtrip_replay(tmp_path):
    path = tmp_path / "log.jsonl"
    hz = _run(JsonlEventLog(path))
    rebuilt = replay_from_jsonl(path)
    assert state_hash(rebuilt) == state_hash(hz.state)
    assert verify_chain(list(__import__("agentgov").read_jsonl(path)))


def test_reopened_jsonl_log_continues_one_chain(tmp_path):
    # Simulate an agent calling tools across separate processes against the
    # same log: each "process" opens a fresh JsonlEventLog on the same path.
    path = tmp_path / "log.jsonl"
    from agentgov import read_jsonl

    def _one_call(amount: float) -> None:
        log = JsonlEventLog(path)  # re-opens; must resume the chain
        hz = Harness(
            app="t",
            registry=Registry(),
            log=log,
            clock=FixedClock(),
            rng=SeededRng(seed=int(amount)),
            session_id="s",
            state=replay_from_jsonl(path),
        )

        @hz.tool(args=A, result=A, layer="action")
        def add(args, ctx) -> Result[A]:
            rid = ctx.rng.uuid()
            return Result(
                A(amount=args.amount), mutations=[Mutation.set(f"items.{rid}", args.amount)]
            )

        hz.call("add", {"amount": amount})

    _one_call(10)
    _one_call(20)
    _one_call(30)

    events = list(read_jsonl(path))
    # Three calls, each emitting requested + mutation + committed.
    assert len(events) == 9
    assert [e.seq for e in events] == list(range(9))
    assert verify_chain(events)
