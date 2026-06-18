"""The workflow runner — control flow lives here, in code (invariant I2).

The runner owns the run: propose the plan, gate it (approve / amend / reject /
halt), then advance through the workflow's stages by asking the workflow's pure
``transition`` what comes next. It honors analyst halts and the plan's
iteration budget (escalating to a human when the budget is exhausted), and it
documents and seals the run at the end. The LLM is never the conductor here —
it is consulted only inside stages, through the StageContext.
"""

from __future__ import annotations

from typing import Any

from ..harness import FinalizeResult, Harness
from .ports import Advisor, Critic, Plan, Planner, PlanReviewer, Scribe
from .stage import StageContext, Workflow


def _base(hz: Harness, turn: str = "plan") -> dict[str, Any]:
    return {
        "event_id": hz.rng.uuid(),
        "session_id": hz.session_id,
        "turn_id": turn,
        "timestamp": hz.clock.now(),
    }


class WorkflowRunner:
    """Executes a governed workflow over a harness, with injected deciders."""

    # Stage id the workflow uses for the feature-proposal node; re-entering it
    # consumes the iteration budget. Override per workflow if named differently.
    FEATURE_STAGE = "S2_features"

    def __init__(
        self,
        *,
        hz: Harness,
        workflow: Workflow,
        planner: Planner,
        advisor: Advisor,
        critic: Critic,
        scribe: Scribe,
        plan_reviewer: PlanReviewer,
    ) -> None:
        """Wire the harness, the workflow, and the five decision providers."""
        self.hz = hz
        self.workflow = workflow
        self.planner = planner
        self.advisor = advisor
        self.critic = critic
        self.scribe = scribe
        self.plan_reviewer = plan_reviewer

    # ------------------------------------------------------------------ run
    def run(self, *, goal: str) -> FinalizeResult:
        """Plan, gate, execute, document, and seal one development run."""
        plan = self._plan_phase(goal)
        if plan is None:  # rejected or halted at plan review
            return self._finalize(plan=None)

        scratch: dict[str, Any] = {"plan": plan}
        ctx = StageContext(hz=self.hz, advisor=self.advisor, critic=self.critic, scratch=scratch)
        stage_id = self.workflow.stages[0].id
        feature_attempts = 0
        while stage_id not in ("DONE", "HALT"):
            stage = self.workflow.stage(stage_id)
            self._emit_stage_entered(stage_id)
            outcome = stage.run(ctx)
            self._emit_stage_exited(stage_id, outcome.status, outcome.reason)
            if self.hz.halted:
                break
            next_id = self.workflow.transition(self.hz.state, stage_id, outcome)
            if next_id == self.FEATURE_STAGE:
                feature_attempts += 1
                if feature_attempts > plan.iteration_budget:
                    if not self._escalate_budget(plan):
                        break  # human halted
                    feature_attempts = 0  # human extended the budget
            stage_id = next_id

        return self._finalize(plan=plan)

    # --------------------------------------------------------------- plan phase
    def _plan_phase(self, goal: str) -> Plan | None:
        from ..events import PlanProposedEvent

        profile = self.hz.state.get("lineage", {})
        plan = self.planner.propose_plan(goal=goal, profile=profile)
        self.hz.log.emit(PlanProposedEvent(**_base(self.hz), plan=plan.model_dump(mode="json")))

        review = self.plan_reviewer.review(plan=plan)
        if review.decision == "amend" and review.plan is not None:
            from ..events import PlanAmendedEvent

            plan = review.plan
            self.hz.log.emit(
                PlanAmendedEvent(
                    **_base(self.hz), actor=review.actor, reason=review.reason,
                    plan=plan.model_dump(mode="json"),
                )
            )
            self._emit_plan_approved(plan, review.actor, review.reason)
            return plan
        if review.decision == "approve":
            self._emit_plan_approved(plan, review.actor, review.reason)
            return plan
        if review.decision == "reject":
            from ..events import PlanRejectedEvent

            self.hz.log.emit(
                PlanRejectedEvent(**_base(self.hz), actor=review.actor, reason=review.reason)
            )
        self.hz.mark_halted(
            trigger="plan_review", actor=review.actor, reason=review.reason or review.decision
        )
        return None

    def _emit_plan_approved(self, plan: Plan, actor: str, reason: str | None) -> None:
        from ..events import PlanApprovedEvent

        self.hz.log.emit(
            PlanApprovedEvent(
                **_base(self.hz), actor=actor, reason=reason, plan=plan.model_dump(mode="json")
            )
        )

    # --------------------------------------------------------------- gates/events
    def _escalate_budget(self, plan: Plan) -> bool:
        decision = self.hz.request_decision(
            trigger="budget_exhausted",
            proposal=(
                f"iteration budget {plan.iteration_budget} exhausted with no clean candidate. "
                f"Approve to grant another round of attempts, or deny/halt to stop."
            ),
        )
        if decision.approved:
            return True
        self.hz.mark_halted(
            trigger="budget_exhausted", actor=decision.actor, reason=decision.reason
        )
        return False

    def _emit_stage_entered(self, stage_id: str) -> None:
        from ..events import StageEnteredEvent

        self.hz.log.emit(StageEnteredEvent(**_base(self.hz, stage_id), stage_id=stage_id))

    def _emit_stage_exited(self, stage_id: str, status: str, reason: str | None) -> None:
        from ..events import StageExitedEvent

        self.hz.log.emit(
            StageExitedEvent(**_base(self.hz, stage_id), stage_id=stage_id, status=status, reason=reason)
        )

    # --------------------------------------------------------------- finalize
    def _finalize(self, *, plan: Plan | None) -> FinalizeResult:
        narrative = self._narrate(plan)
        reason = "halted" if self.hz.halted else "complete"
        return self.hz.finalize(
            report={"goal": plan.goal} if plan else None,
            write_bundle=True,
            reason=reason,
            workflow_id=self.workflow.id,
            workflow_version=self.workflow.version,
            narrative=narrative,
        )

    def _narrate(self, plan: Plan | None) -> str | None:
        from ..events import DecisionEvent, StageExitedEvent

        events = self.hz._all_events()
        stage_trace = [
            {"stage_id": e.stage_id, "status": e.status, "reason": e.reason}
            for e in events
            if isinstance(e, StageExitedEvent)
        ]
        decisions = [
            {"node": e.node, "kind": e.kind, "tool": e.tool, "rationale": e.rationale}
            for e in events
            if isinstance(e, DecisionEvent)
        ]
        try:
            return self.scribe.narrate(
                plan=plan.model_dump(mode="json") if plan else {},
                stage_trace=stage_trace,
                decisions=decisions,
                state=self.hz.state,
            )
        except Exception:  # the narrative is documentation, never the audit record
            return None


__all__ = ["WorkflowRunner"]
