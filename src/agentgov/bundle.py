"""Evidence bundles: a self-contained, signable record of a finished session.

A bundle is what you hand a regulator, a customer's security team, or your own
incident review. It stands alone — inspectable without rerunning the model or
even loading the SDK: a JSON document holding the final state snapshot, the
chain-verification verdict, every human checkpoint decision, the tool/harness
versions in play, and a ``manifest_hash`` that seals the whole thing.

The seal is a blake2b digest over the canonical encoding of every other field.
Re-sealing a tampered bundle yields a different hash, so
:func:`verify_bundle` can prove the evidence was not edited after the fact.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from .events import (
    CheckpointDecidedEvent,
    CriticFindingEvent,
    DecisionEvent,
    Event,
    PlanApprovedEvent,
    PlanProposedEvent,
    StageExitedEvent,
)
from .replay import verify_chain
from .state import State, state_hash

_SEAL_FIELD = "manifest_hash"


class EvidenceBundle(BaseModel):
    """A self-contained, optionally-sealed record of a finalized session."""

    model_config = ConfigDict(frozen=True)

    app: str
    session_id: str
    created_at: datetime
    agentgov_version: str
    mode: str
    # How the run ended: "finalized" (clean promotion gate) or "halted"
    # (an analyst stopped the run at a checkpoint). Reads differently in review.
    terminal: str
    tool_names: tuple[str, ...]
    final_state: dict[str, Any]
    final_state_hash: str
    event_count: int
    chain_verified: bool
    checkpoints: tuple[dict[str, Any], ...]
    findings: tuple[dict[str, Any], ...] = ()
    report: dict[str, Any] | None = None
    event_log_ref: str | None = None
    # Workflow provenance (populated for governed-workflow runs; empty otherwise).
    # The control flow is reconstructed from the event log — the bundle is
    # self-describing (invariant I2).
    workflow_id: str | None = None
    workflow_version: str | None = None
    plan: dict[str, Any] = {}
    stage_trace: tuple[dict[str, Any], ...] = ()
    decisions: tuple[dict[str, Any], ...] = ()
    critic_findings: tuple[dict[str, Any], ...] = ()
    # The human-readable model-development narrative authored by the Scribe.
    narrative: str | None = None
    manifest_hash: str | None = None

    def sealed(self) -> EvidenceBundle:
        """Return a copy with ``manifest_hash`` set to the computed seal."""
        return self.model_copy(update={_SEAL_FIELD: _seal(self)})


def _seal(bundle: EvidenceBundle) -> str:
    """Blake2b digest over every bundle field except the seal itself."""
    payload = bundle.model_dump(mode="json")
    payload.pop(_SEAL_FIELD, None)
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.blake2b(blob.encode("utf-8"), digest_size=32).hexdigest()


def build_bundle(
    *,
    app: str,
    session_id: str,
    events: Sequence[Event],
    state: State,
    agentgov_version: str,
    mode: str,
    tool_names: Sequence[str],
    report: dict[str, Any] | None = None,
    event_log_ref: str | None = None,
    findings: Sequence[dict[str, Any]] = (),
    terminal: str = "finalized",
    workflow_id: str | None = None,
    workflow_version: str | None = None,
    narrative: str | None = None,
) -> EvidenceBundle:
    """Assemble and seal an :class:`EvidenceBundle` from a finished session.

    Workflow provenance (the approved plan, the stage trace, the decisions, and
    the critic findings) is reconstructed from the event log so the bundle is
    self-describing — the control flow can be read back without rerunning.
    """
    events = list(events)
    checkpoints = tuple(
        e.model_dump(mode="json") for e in events if isinstance(e, CheckpointDecidedEvent)
    )
    approved = [e for e in events if isinstance(e, PlanApprovedEvent)]
    proposed = [e for e in events if isinstance(e, PlanProposedEvent)]
    plan = approved[-1].plan if approved else (proposed[-1].plan if proposed else {})
    stage_trace = tuple(
        {"stage_id": e.stage_id, "status": e.status, "reason": e.reason}
        for e in events
        if isinstance(e, StageExitedEvent)
    )
    decisions = tuple(
        {"node": e.node, "kind": e.kind, "provider": e.provider, "tool": e.tool,
         "chosen_args": e.chosen_args, "rationale": e.rationale}
        for e in events
        if isinstance(e, DecisionEvent)
    )
    critic_findings = tuple(
        {"model_id": e.model_id, "severity": e.severity, "category": e.category, "message": e.message}
        for e in events
        if isinstance(e, CriticFindingEvent)
    )
    bundle = EvidenceBundle(
        app=app,
        session_id=session_id,
        created_at=datetime.now().astimezone(),
        agentgov_version=agentgov_version,
        mode=mode,
        terminal=terminal,
        tool_names=tuple(tool_names),
        final_state=state,
        final_state_hash=state_hash(state),
        event_count=len(events),
        chain_verified=verify_chain(events),
        checkpoints=checkpoints,
        findings=tuple(findings),
        report=report,
        event_log_ref=event_log_ref,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        plan=plan,
        stage_trace=stage_trace,
        decisions=decisions,
        critic_findings=critic_findings,
        narrative=narrative,
    )
    return bundle.sealed()


def verify_bundle(bundle: EvidenceBundle) -> bool:
    """Return True iff the seal matches and the recorded state hash is consistent."""
    if bundle.manifest_hash is None:
        return False
    if bundle.manifest_hash != _seal(bundle):
        return False
    return bundle.final_state_hash == state_hash(bundle.final_state)


__all__ = ["EvidenceBundle", "build_bundle", "verify_bundle"]
