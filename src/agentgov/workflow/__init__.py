"""agentgov.workflow — a governed workflow engine over the kernel.

Control flow lives here, in code (invariant I2): an explicit ``Workflow`` of
stages, advanced by a ``WorkflowRunner``, which consults injected decision
providers (``Planner`` / ``Advisor`` / ``Critic`` / ``Scribe`` / ``PlanReviewer``)
only at the open nodes. The engine imports no ``pydantic_ai`` / LLM SDK — the
LLM is a component injected behind the ports, never the conductor.

    from agentgov import Harness
    from agentgov.workflow import WorkflowRunner
    from agentgov.workflow.workflows.credit import credit_workflow

    runner = WorkflowRunner(
        hz=hz, workflow=credit_workflow(),
        planner=..., advisor=..., critic=..., scribe=..., plan_reviewer=...,
    )
    result = runner.run(goal="build a PD scorecard")
"""

from __future__ import annotations

from .ports import (
    Advisor,
    Critic,
    Finding,
    Plan,
    PlanReview,
    PlanReviewer,
    Planner,
    Proposal,
    Scribe,
)
from .runner import WorkflowRunner
from .stage import Stage, StageContext, StageOutcome, Workflow

__all__ = [
    "Advisor",
    "Critic",
    "Finding",
    "Plan",
    "PlanReview",
    "PlanReviewer",
    "Planner",
    "Proposal",
    "Scribe",
    "Stage",
    "StageContext",
    "StageOutcome",
    "Workflow",
    "WorkflowRunner",
]
