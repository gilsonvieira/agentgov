"""Deterministic, LLM-free decision providers.

These implement the ports with fixed/rule-based logic so the workflow engine can
be exercised end-to-end without any model call — fully reproducible. They are
the "de-risk the seam" tooling (spec build step 2) and back the seam trace. The
brain ships LLM-backed providers behind the same ports.
"""

from __future__ import annotations

from typing import Any

from .ports import Finding, Plan, PlanReview, Proposal


class FixedPlanner:
    """Returns a pre-built plan verbatim."""

    def __init__(self, plan: Plan) -> None:
        """Hold the plan this planner always proposes."""
        self._plan = plan

    def propose_plan(self, *, goal: str, profile: dict[str, Any]) -> Plan:
        """Ignore inputs; return the fixed plan."""
        return self._plan


class StrategyAdvisor:
    """Proposes the next feature strategy from the plan, advancing on each call.

    A deterministic stand-in for the judgment node: it walks the plan's ordered
    ``candidate_strategies`` so successive retries try successive feature sets.
    """

    def __init__(self, strategies: list[dict[str, Any]]) -> None:
        """Hold the ordered strategies and a call counter."""
        self._strategies = strategies
        self._i = 0

    def advise(self, *, question: str, state: dict[str, Any], context: dict[str, Any]) -> Proposal:
        """Return the next strategy's feature set as proposed train args."""
        strategies = context.get("strategies") or self._strategies
        i = min(self._i, len(strategies) - 1)
        self._i += 1
        features = list(strategies[i].get("features", []))
        return Proposal(
            tool="train_candidate",
            args={"features": features},
            rationale=f"strategy {i}: {features}",
        )


class NoopCritic:
    """Returns no findings (advisory critic that never objects)."""

    def critique(self, *, candidate: dict[str, Any], reports: dict[str, Any]) -> tuple[Finding, ...]:
        """Find nothing."""
        return ()


class ThresholdCritic:
    """Flags a low-disparate-impact candidate (advisory only)."""

    def __init__(self, di_threshold: float = 0.80) -> None:
        """Hold the DI threshold below which to raise an advisory finding."""
        self._t = di_threshold

    def critique(self, *, candidate: dict[str, Any], reports: dict[str, Any]) -> tuple[Finding, ...]:
        """Raise a 'proxy' warning when measured DI is below threshold."""
        di = reports.get("disparate_impact", candidate.get("disparate_impact", 1.0))
        if di < self._t:
            return (Finding(category="proxy", severity="high",
                            message=f"DI {di:.2f} below {self._t:.2f}; possible proxy"),)
        return ()


class TemplateScribe:
    """Writes a plain-text development narrative from the trace (no LLM)."""

    def narrate(self, *, plan: dict[str, Any], stage_trace: list[dict[str, Any]],
                decisions: list[dict[str, Any]], state: dict[str, Any]) -> str:
        """Render plan, stages, decisions, and candidates as a narrative."""
        lines = [
            f"Goal: {plan.get('goal', '(none)')}",
            f"Target: {plan.get('target')} | Protected: {plan.get('protected_attribute')}",
            "",
            "Stages:",
            *[f"  - {s['stage_id']}: {s['status']}" + (f" ({s['reason']})" if s.get('reason') else "")
              for s in stage_trace],
            "",
            "Decisions:",
            *[f"  - {d['node']} [{d['kind']}] -> {d['tool']}: {d.get('rationale') or ''}"
              for d in decisions],
            "",
            f"Candidates: {list(state.get('candidates', {}))}",
        ]
        return "\n".join(lines)


class ApprovePlanReviewer:
    """Plan reviewer that approves every plan (unattended)."""

    def __init__(self, actor: str = "analyst") -> None:
        """Record the approving actor."""
        self._actor = actor

    def review(self, *, plan: Plan) -> PlanReview:
        """Approve the plan as-is."""
        return PlanReview(decision="approve", actor=self._actor)


class AmendPlanReviewer:
    """Plan reviewer that applies a fixed amendment, then approves it."""

    def __init__(self, amended: Plan, actor: str = "analyst", reason: str = "edited strategies") -> None:
        """Hold the amended plan to substitute at review time."""
        self._plan = amended
        self._actor = actor
        self._reason = reason

    def review(self, *, plan: Plan) -> PlanReview:
        """Return the amended plan as an 'amend' verdict."""
        return PlanReview(decision="amend", actor=self._actor, plan=self._plan, reason=self._reason)


class HaltPlanReviewer:
    """Plan reviewer that halts the run at plan review."""

    def __init__(self, actor: str = "analyst", reason: str = "wrong approach") -> None:
        """Record the halting actor and reason."""
        self._actor = actor
        self._reason = reason

    def review(self, *, plan: Plan) -> PlanReview:
        """Halt before any execution."""
        return PlanReview(decision="halt", actor=self._actor, reason=self._reason)


__all__ = [
    "AmendPlanReviewer",
    "ApprovePlanReviewer",
    "FixedPlanner",
    "HaltPlanReviewer",
    "NoopCritic",
    "StrategyAdvisor",
    "TemplateScribe",
    "ThresholdCritic",
]
