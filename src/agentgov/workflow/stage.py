"""Stages, the workflow, and the stage context (where invariant I3 lives).

A :class:`Stage` is a node in the lifecycle; a :class:`Workflow` is the fixed
graph of stages plus a pure ``transition`` that owns the control flow (I2). A
stage body acts only through the :class:`StageContext`, which is the *only*
surface that lets a decision influence governed state — and it does so solely
through gated kernel tool calls, never by writing a proposal to state (I3).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from ..executor import ToolRunResult
from ..harness import Harness
from .ports import Advisor, Critic, Finding

DecisionKind = Literal["rule", "search", "judgment", "human"]
StageStatus = Literal["ok", "retry", "failed", "halt"]


@dataclass
class StageOutcome:
    """How a stage ended, plus any data the next stage needs."""

    status: StageStatus = "ok"
    reason: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


def _base(hz: Harness, turn: str) -> dict[str, Any]:
    return {
        "event_id": hz.rng.uuid(),
        "session_id": hz.session_id,
        "turn_id": turn,
        "timestamp": hz.clock.now(),
    }


class StageContext:
    """The controlled surface a stage body uses to act and to record decisions."""

    def __init__(self, *, hz: Harness, advisor: Advisor, critic: Critic, scratch: dict[str, Any]) -> None:
        """Bind the harness, the deciders, and the run-level orchestration scratch."""
        self.hz = hz
        self.advisor = advisor
        self.critic = critic
        # Ephemeral, non-audited orchestration state passed between stages
        # (e.g. the id of the candidate just trained). Not governed state.
        self.scratch = scratch
        self._turn_seq = 0

    @property
    def state(self) -> dict[str, Any]:
        """The current governed state (read-only view for stage logic)."""
        return self.hz.state

    def _mint(self, label: str) -> str:
        """Mint a unique, stage-readable turn id so each call is a distinct entry.

        A stage can be re-entered (retries consume the iteration budget), so a
        plain stage label would collapse every attempt into one timeline row.
        The ``label#n`` form keeps the stage readable while staying unique per
        call, so the viewer shows one row per attempt — including rejections.
        """
        turn = f"{label}#{self._turn_seq}"
        self._turn_seq += 1
        return turn

    def call(self, tool: str, args: dict[str, Any], *, turn_id: str | None = None) -> ToolRunResult:
        """Run a deterministic governed tool by name (one timeline entry per call)."""
        return self.hz.call(tool, args, turn_id=self._mint(turn_id or "call"))

    def decide(
        self,
        *,
        node: str,
        kind: DecisionKind,
        question: str,
        then_tool: str,
        context: dict[str, Any] | None = None,
        turn_id: str | None = None,
    ) -> ToolRunResult:
        """Resolve a judgment/search node and commit ONLY via a gated tool call (I3).

        The advisor proposes *inputs* to ``then_tool``; the proposal never
        touches governed state directly — it reaches state only through
        ``hz.call``, whose commit is rail-gated. The decision is recorded with
        its ``kind`` so a reviewer sees who decided it.
        """
        from ..events import DecisionEvent

        # One turn id for the whole decision: the DecisionEvent and the gated
        # tool call it drives group into a single timeline entry.
        turn = self._mint(turn_id or node)
        proposal = self.advisor.advise(question=question, state=self.hz.state, context=context or {})
        self.hz.log.emit(
            DecisionEvent(
                **_base(self.hz, turn),
                node=node,
                kind=kind,
                provider=type(self.advisor).__name__,
                tool=then_tool,
                chosen_args=proposal.args,
                rationale=proposal.rationale,
            )
        )
        return self.hz.call(then_tool, proposal.args, turn_id=turn)

    def critique(self, *, model_id: str, reports: dict[str, Any] | None = None) -> tuple[Finding, ...]:
        """Run the adversarial critic over a candidate; record findings (advisory)."""
        from ..events import CriticFindingEvent

        candidate = self.hz.state.get("candidates", {}).get(model_id, {})
        findings = tuple(self.critic.critique(candidate=candidate, reports=reports or {}))
        turn = self._mint("critique")
        for f in findings:
            self.hz.log.emit(
                CriticFindingEvent(
                    **_base(self.hz, turn),
                    model_id=model_id,
                    severity=f.severity,
                    category=f.category,
                    message=f.message,
                )
            )
        return findings

    def gate(self, *, trigger: str, proposal: str):
        """Raise a workflow-owned human gate; mark the run halted on a halt decision."""
        decision = self.hz.request_decision(trigger=trigger, proposal=proposal)
        if decision.halt:
            self.hz.mark_halted(trigger=trigger, actor=decision.actor, reason=decision.reason)
        return decision


@dataclass(frozen=True)
class Stage:
    """One node in the lifecycle: a body that acts through the StageContext."""

    id: str
    run: Callable[[StageContext], StageOutcome]
    description: str = ""


@dataclass(frozen=True)
class Workflow:
    """A fixed graph of stages plus a pure transition (the control flow, I2)."""

    id: str
    version: str
    stages: tuple[Stage, ...]
    # (state, current_stage_id, outcome) -> next stage id | "DONE" | "HALT"
    transition: Callable[[dict[str, Any], str, StageOutcome], str]

    def stage(self, stage_id: str) -> Stage:
        """Look up a stage by id."""
        for s in self.stages:
            if s.id == stage_id:
                return s
        raise KeyError(f"unknown stage {stage_id!r}")


__all__ = ["Stage", "StageContext", "StageOutcome", "Workflow"]
