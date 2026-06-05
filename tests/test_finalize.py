"""The finalize terminal gate seals a bundle on pass and blocks on rail failure."""

from __future__ import annotations

from pathlib import Path

from agentgov import (
    FixedClock,
    Harness,
    JsonlEventLog,
    RailResult,
    Registry,
    SeededRng,
    verify_bundle,
)


def _types(log):
    return [e.type for e in log.events()]


def test_finalize_passes_and_seals_a_bundle(make_harness):
    hz = make_harness()
    hz.call("add", {"amount": 100})
    fr = hz.finalize(report={"note": "done"})
    assert fr.ok
    assert fr.violations == ()
    assert fr.bundle is not None
    assert fr.bundle.manifest_hash is not None
    assert fr.bundle.report == {"note": "done"}
    assert fr.bundle.chain_verified
    assert fr.bundle.tool_names == ("add", "bad_result")
    assert verify_bundle(fr.bundle)
    assert "finalize.attempted" in _types(hz.log)


def test_finalize_blocks_on_finalize_only_rail(make_harness):
    hz = make_harness()
    hz.call("add", {"amount": 100})

    @hz.rail(id="needs-review", finalize_only=True)
    def review(state) -> RailResult:
        return RailResult.reject("needs-review", "manual review required")

    fr = hz.finalize()
    assert not fr.ok
    assert fr.bundle is None
    assert [v.rail_id for v in fr.violations] == ["needs-review"]
    finalize_events = [e for e in hz.log.events() if e.type == "finalize.attempted"]
    assert finalize_events[-1].outcome == "blocked"
    assert finalize_events[-1].blocking_rail_ids == ("needs-review",)


def test_finalize_only_rail_does_not_run_per_call(make_harness):
    hz = make_harness()

    @hz.rail(id="finalize-block", finalize_only=True)
    def block(state) -> RailResult:
        return RailResult.reject("finalize-block")

    # The per-call path must ignore finalize-only rails, so this commits.
    r = hz.call("add", {"amount": 100})
    assert r.ok


def test_tampering_with_a_bundle_breaks_verification(make_harness):
    hz = make_harness()
    hz.call("add", {"amount": 100})
    bundle = hz.finalize().bundle
    assert bundle is not None
    tampered = bundle.model_copy(update={"final_state": {"items": {"x": 999}}})
    assert not verify_bundle(tampered)


def test_write_bundle_emits_a_file(tmp_path: Path):
    log_path = tmp_path / "run.jsonl"
    hz = Harness(
        app="t",
        registry=Registry(),
        log=JsonlEventLog(log_path),
        clock=FixedClock(),
        rng=SeededRng(seed=1),
        session_id="s1",
    )

    from pydantic import BaseModel

    from agentgov import Mutation, Result

    class A(BaseModel):
        n: int

    class Res(BaseModel):
        ok: bool

    @hz.tool(args=A, result=Res, layer="action")
    def noop(args: A, ctx) -> Result[Res]:
        return Result(Res(ok=True), mutations=[Mutation.set("n", args.n)])

    hz.call("noop", {"n": 5})
    fr = hz.finalize(write_bundle=True)
    assert fr.ok
    out = log_path.with_suffix(".bundle.json")
    assert out.exists()
    assert fr.bundle is not None
    assert fr.bundle.event_log_ref == str(log_path)
