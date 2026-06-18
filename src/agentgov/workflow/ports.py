"""Decision-provider ports and the artifacts they exchange.

These are the seams between the framework-independent workflow engine and the
deciders that resolve its open nodes. The engine imports only these Protocols
and models — never an LLM SDK. Implementations live elsewhere (a rule, an
AutoML search, an LLM-backed provider in the brain, a human responder), so the
spine stays deterministic and the judgment is injected.

The least-powerful-sufficient menu (rule / search / judgment / human) is
expressed here: a deterministic ``Advisor`` (a rule), an AutoML ``Advisor`` (a
search), and an LLM ``Advisor`` (judgment) all satisfy the same Protocol.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class Plan(BaseModel):
    """A gated development plan: what to build, how, and within what budget."""

    workflow_id: str
    goal: str
    target: str
    protected_attribute: str
    # Ordered feature sets / strategies to try (each: {"features": [...], ...}).
    candidate_strategies: tuple[dict[str, Any], ...] = ()
    iteration_budget: int = 3
    rationale: str = ""


class Proposal(BaseModel):
    """A judgment/search output: proposed INPUTS to a governed tool call (I3).

    A proposal never carries a mutation. It names the tool to call and the args
    to call it with; the kernel commit is rail-gated, so the proposal reaches
    governed state only through a gate.
    """

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class Finding(BaseModel):
    """An adversarial critic's report on a candidate (advisory by default)."""

    category: str  # e.g. "leakage", "proxy", "overfit", "instability"
    severity: Literal["info", "warn", "high"] = "warn"
    message: str = ""


class PlanReview(BaseModel):
    """A human's verdict at the plan-review gate.

    ``amend`` carries an edited ``plan`` that becomes the approved plan. The
    edit is itself recorded (a governed change), so the audit trail shows what
    the human changed and why.
    """

    decision: Literal["approve", "amend", "reject", "halt"]
    actor: str
    plan: Plan | None = None  # required when decision == "amend"
    reason: str | None = None


@runtime_checkable
class Planner(Protocol):
    """Proposes the development plan from the goal and the data profile."""

    def propose_plan(self, *, goal: str, profile: dict[str, Any]) -> Plan: ...


@runtime_checkable
class Advisor(Protocol):
    """Resolves a judgment/search node by proposing tool inputs (never state)."""

    def advise(self, *, question: str, state: dict[str, Any], context: dict[str, Any]) -> Proposal: ...


@runtime_checkable
class Critic(Protocol):
    """Adversarially reviews a candidate; returns advisory findings."""

    def critique(self, *, candidate: dict[str, Any], reports: dict[str, Any]) -> tuple[Finding, ...]: ...


@runtime_checkable
class Scribe(Protocol):
    """Writes the human-readable model-development narrative from the trace."""

    def narrate(self, *, plan: dict[str, Any], stage_trace: list[dict[str, Any]],
                decisions: list[dict[str, Any]], state: dict[str, Any]) -> str: ...


@runtime_checkable
class PlanReviewer(Protocol):
    """Human authority at the plan-review gate: approve / amend / reject / halt."""

    def review(self, *, plan: Plan) -> PlanReview: ...


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
]
