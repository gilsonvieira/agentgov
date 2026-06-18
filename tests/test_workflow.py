"""The governed workflow engine, exercised with deterministic stub providers.

No LLM: the engine is driven end-to-end by fixed/rule-based providers so the
whole control path is reproducible. Covers the happy path, plan amend/halt,
invariant I3 (a judgment reaches state only through a gated tool), the
fairness-style human gate, and iteration-budget escalation.
"""

from __future__ import annotations

import pytest
from agentgov import (
    ApproveAll,
    DenyAll,
    FixedClock,
    Harness,
    InMemoryEventLog,
    Mutation,
    RailResult,
    Registry,
    Result,
    SeededRng,
    verify_bundle,
)
from agentgov.workflow import Plan, Stage, StageOutcome, Workflow, WorkflowRunner
from agentgov.workflow.stubs import (
    AmendPlanReviewer,
    ApprovePlanReviewer,
    FixedPlanner,
    HaltPlanReviewer,
    NoopCritic,
    StrategyAdvisor,
    TemplateScribe,
)
from pydantic import BaseModel


class TArgs(BaseModel):
    features: list[str]


class TRes(BaseModel):
    model_id: str


def _harness(responder=None):
    hz = Harness(
        app="wf-test", registry=Registry(), log=InMemoryEventLog(),
        clock=FixedClock(), rng=SeededRng(seed=7), responder=responder, session_id="s",
    )

    @hz.tool(args=TArgs, result=TRes, layer="action")
    def train(args: TArgs, ctx) -> Result[TRes]:
        mid = f"m_{ctx.rng.uuid()[:6]}"
        return Result(TRes(model_id=mid), mutations=[Mutation.set(f"candidates.{mid}", {"features": args.features})])

    @hz.rail(id="no-banned")
    def no_banned(state) -> RailResult:
        for mid, cand in state.get("candidates", {}).items():
            if "banned" in cand.get("features", []):
                return RailResult.reject("no-banned", f"{mid} uses a banned feature")
        return RailResult.passed()

    return hz


def _workflow() -> Workflow:
    def s_features(ctx) -> StageOutcome:
        res = ctx.decide(node="feats", kind="judgment", question="propose features",
                         then_tool="train", context={})
        if not res.ok:
            return StageOutcome(status="retry", reason="rail rejected")
        ctx.scratch["model_id"] = res.result.model_id
        return StageOutcome(status="ok", data={"model_id": res.result.model_id})

    def s_done(ctx) -> StageOutcome:
        return StageOutcome(status="ok")

    def transition(state, stage_id, outcome):
        if outcome.status == "halt":
            return "HALT"
        if stage_id == "S2_features":
            return "S_done" if outcome.status == "ok" else "S2_features"
        return "DONE"

    return Workflow(
        id="wf", version="1",
        stages=(Stage("S2_features", s_features), Stage("S_done", s_done)),
        transition=transition,
    )


def _plan(strategies, budget=4) -> Plan:
    return Plan(workflow_id="wf", goal="g", target="y", protected_attribute="p",
                candidate_strategies=tuple(strategies), iteration_budget=budget)


def _runner(hz, *, plan, reviewer, strategies):
    return WorkflowRunner(
        hz=hz, workflow=_workflow(), planner=FixedPlanner(plan),
        advisor=StrategyAdvisor(list(strategies)), critic=NoopCritic(),
        scribe=TemplateScribe(), plan_reviewer=reviewer,
    )


def test_happy_path_seals_a_workflow_bundle():
    hz = _harness(ApproveAll())
    strategies = [{"features": ["a", "b"]}]
    fr = _runner(hz, plan=_plan(strategies), reviewer=ApprovePlanReviewer(), strategies=strategies).run(goal="g")
    assert fr.ok
    b = fr.bundle
    assert b is not None and verify_bundle(b)
    assert b.terminal == "finalized"
    assert b.workflow_id == "wf"
    assert b.plan["goal"] == "g"
    assert [s["stage_id"] for s in b.stage_trace] == ["S2_features", "S_done"]
    assert any(d["node"] == "feats" and d["kind"] == "judgment" for d in b.decisions)
    assert b.narrative and "Stages:" in b.narrative


def test_i3_judgment_reaches_state_only_through_a_gated_tool():
    # Advisor first proposes a banned feature (rail rejects -> rolled back),
    # then a clean one (commits). The banned proposal never reaches state.
    hz = _harness(ApproveAll())
    strategies = [{"features": ["banned", "a"]}, {"features": ["a", "b"]}]
    fr = _runner(hz, plan=_plan(strategies), reviewer=ApprovePlanReviewer(), strategies=strategies).run(goal="g")
    assert fr.ok
    cands = list(hz.state.get("candidates", {}).values())
    assert len(cands) == 1
    assert cands[0]["features"] == ["a", "b"]
    types = [e.type for e in hz.log.events()]
    assert "rail.violated" in types and "decision.made" in types


def test_plan_halt_is_terminal_no_stages_run():
    hz = _harness(ApproveAll())
    strategies = [{"features": ["a"]}]
    fr = _runner(hz, plan=_plan(strategies), reviewer=HaltPlanReviewer(), strategies=strategies).run(goal="g")
    assert fr.ok is False
    assert hz.halted
    assert fr.bundle.terminal == "halted"
    types = [e.type for e in hz.log.events()]
    assert "run.halted" in types
    assert "stage.entered" not in types  # halted before execution


def test_plan_amend_records_the_edit_and_uses_the_amended_plan():
    hz = _harness(ApproveAll())
    original = _plan([{"features": ["a"]}])
    amended = _plan([{"features": ["a", "b"]}])
    fr = _runner(hz, plan=original, reviewer=AmendPlanReviewer(amended), strategies=[{"features": ["a", "b"]}]).run(goal="g")
    assert fr.ok
    types = [e.type for e in hz.log.events()]
    assert "plan.amended" in types and "plan.approved" in types
    assert fr.bundle.plan["candidate_strategies"][0]["features"] == ["a", "b"]


def test_budget_exhaustion_escalates_then_halts_on_denial():
    # Every strategy is banned, so every train is rejected; the runner exhausts
    # the budget and escalates to the human, who (DenyAll) halts the run.
    hz = _harness(DenyAll())
    strategies = [{"features": ["banned"]}]
    fr = _runner(hz, plan=_plan(strategies, budget=2), reviewer=ApprovePlanReviewer(),
                 strategies=strategies).run(goal="g")
    assert fr.ok is False
    assert hz.halted
    triggers = [e.trigger for e in hz.log.events() if e.type == "checkpoint.requested"]
    assert "budget_exhausted" in triggers


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
