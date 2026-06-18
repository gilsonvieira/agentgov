"""``Harness`` — the public facade that makes a governed call one line.

It owns the registry, the rail set, the event log, the host ports, the running
state, and the correlation ids. ``hz.call(tool, args)`` runs the full
transaction boundary and returns the typed result; the audit log is written as
a side effect. ``mode="enforce"`` blocks on rail rejection; ``mode="observe"``
logs would-be rejections without blocking — the safe way to roll the harness
out over existing tools.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .bundle import EvidenceBundle, build_bundle
from .checkpoints import CheckpointResponder, checkpoint_id
from .context import ToolContext
from .contracts import CheckpointPending, Result, RunHalted, ToolSpec
from .eventlog import JsonlEventLog, NoopRedactor, Redactor
from .events import (
    CheckpointDecidedEvent,
    CheckpointRequestedEvent,
    Event,
    FinalizeAttemptedEvent,
    RunHaltedEvent,
)
from .executor import EventLog, Mode, ToolRunResult, run_tool
from .hosts import Clock, DefaultRng, Rng, SystemClock
from .rails import Rail, RailResult, Violation, run_finalize_rails
from .registry import Registry, default_registry
from .replay import read_jsonl
from .state import State


@dataclass(frozen=True)
class FinalizeResult:
    """Outcome of the terminal finalize gate."""

    ok: bool
    violations: tuple[Violation, ...]
    bundle: EvidenceBundle | None


def _default_root() -> Path:
    override = os.environ.get("AGENTGOV_ROOT")
    return Path(override) if override else Path.cwd() / ".agentgov"


class Harness:
    """A governed runtime for a finite set of tools."""

    def __init__(
        self,
        app: str,
        *,
        mode: Mode = "enforce",
        registry: Registry | None = None,
        log: EventLog | None = None,
        state: State | None = None,
        clock: Clock | None = None,
        rng: Rng | None = None,
        responder: CheckpointResponder | None = None,
        redactor: Redactor | None = None,
        session_id: str | None = None,
        artifacts: dict[str, Any] | None = None,
    ) -> None:
        """Build a harness for ``app``. Defaults to a JSONL log under ``.agentgov/``."""
        self.app = app
        self.mode = mode
        self.registry = registry or default_registry()
        self.clock = clock or SystemClock()
        self.rng = rng or DefaultRng()
        self.state: State = state if state is not None else {}
        # Ephemeral, non-audited runtime scratch shared across calls (e.g. a
        # fitted model or a dataframe that must survive between pipeline steps).
        self.artifacts: dict[str, Any] = artifacts if artifacts is not None else {}
        self.responder = responder
        self.session_id = session_id or self.rng.uuid()
        self._rails: list[Rail] = []
        self._turn = 0
        self._halted = False
        if log is not None:
            self.log: EventLog = log
        else:
            path = _default_root() / app / f"{self.session_id}.jsonl"
            self.log = JsonlEventLog(path, redactor=redactor or NoopRedactor())

    # ------------------------------------------------------------------ rails
    def rail(
        self,
        *,
        id: str,
        finalize_only: bool = False,
    ) -> Callable[[Callable[[State], RailResult]], Callable[[State], RailResult]]:
        """Register a rail. The decorated ``check(state) -> RailResult`` runs per call."""

        def _wrap(fn: Callable[[State], RailResult]) -> Callable[[State], RailResult]:
            self._rails.append(Rail(rail_id=id, check=fn, finalize_only=finalize_only))
            return fn

        return _wrap

    def add_rail(self, rail: Rail) -> None:
        """Register an already-built :class:`Rail`."""
        self._rails.append(rail)

    @property
    def rails(self) -> tuple[Rail, ...]:
        """The registered rails (non-finalize and finalize-only)."""
        return tuple(self._rails)

    # ------------------------------------------------------------------ tools
    def tool[A: BaseModel, R: BaseModel](
        self,
        *,
        args: type[A],
        result: type[R],
        layer: str = "action",
        name: str | None = None,
        rails: Sequence[str] = (),
    ) -> Callable[
        [Callable[[A, ToolContext], Result[R]]],
        Callable[[A, ToolContext], Result[R]],
    ]:
        """Register a tool in this harness's registry (delegates to :meth:`Registry.tool`)."""
        return self.registry.tool(
            args=args, result=result, layer=layer, name=name, rails=rails
        )

    # ------------------------------------------------------------------ call
    def call[R: BaseModel](
        self,
        tool_name: str,
        args: Any,
        *,
        turn_id: str | None = None,
    ) -> ToolRunResult[R]:
        """Run ``tool_name`` under the transaction boundary; return its result."""
        spec: ToolSpec[Any, R] = self.registry.get(tool_name)
        turn = turn_id or f"turn-{self._turn}"
        self._turn += 1
        if self._halted:
            # The run was halted at an earlier checkpoint; refuse further work
            # so a driver that keeps calling cannot advance a stopped run.
            err = RunHalted(
                checkpoint_id="", trigger="(halted)", actor="",
                reason="run already halted; no further calls are governed",
            )
            return ToolRunResult(False, None, self.state, err, ())
        ctx = ToolContext(
            state=self.state,
            clock=self.clock,
            rng=self.rng,
            artifacts=self.artifacts,
            session_id=self.session_id,
            turn_id=turn,
        )
        self._bind_checkpoint(ctx, turn)
        artifacts_before = set(self.artifacts)
        result = run_tool(spec, args, ctx, rails=self._rails, log=self.log, mode=self.mode)
        self.state = result.state
        if not result.ok:
            # Artifact invalidation: a rejected step's scratch handles (e.g. a
            # rejected model's estimator) are keyed to the call that produced
            # them; evict them on rollback so a later step cannot read a stale
            # "validated" object. Audited state already rolled back in run_tool.
            for key in set(self.artifacts) - artifacts_before:
                del self.artifacts[key]
            # A halt is terminal, not a re-planable rejection: mark the run
            # halted and write the terminal record so the bundle reads as halted.
            if isinstance(result.error, RunHalted):
                self._halted = True
                self.log.emit(
                    RunHaltedEvent(
                        event_id=self.rng.uuid(),
                        session_id=self.session_id,
                        turn_id=turn,
                        timestamp=self.clock.now(),
                        checkpoint_id=result.error.checkpoint_id,
                        trigger=result.error.trigger,
                        reason=result.error.reason,
                        actor=result.error.actor,
                    )
                )
        return result

    @property
    def halted(self) -> bool:
        """True once an analyst has halted the run at a checkpoint."""
        return self._halted

    # ------------------------------------------------------------- finalization
    def finalize(
        self,
        *,
        report: dict[str, Any] | None = None,
        write_bundle: bool = False,
        reason: str = "complete",
    ) -> FinalizeResult:
        """Run the terminal gate: all rails over final state, then seal a bundle.

        On a *complete* run, every rail (including ``finalize_only`` ones) runs
        over the current state. If any rejects, a blocked ``finalize.attempted``
        event is logged and no bundle is produced. On a clean pass, a sealed
        :class:`EvidenceBundle` is built with ``terminal="finalized"``.

        On a *halted* run — either ``reason="halted"`` was passed or an analyst
        halted the run at a checkpoint (``self.halted``) — the promotion gate is
        moot: a halted run is never a clean promotion. A bundle is still sealed,
        with ``terminal="halted"``, so the evidence record explains the stop.
        ``ok`` is ``False`` for a halted run.
        """
        halted = self._halted or reason == "halted"
        from . import __version__

        ref = str(self.log.path) if isinstance(self.log, JsonlEventLog) else None

        def _seal(terminal: str) -> EvidenceBundle:
            return build_bundle(
                app=self.app,
                session_id=self.session_id,
                events=self._all_events(),
                state=self.state,
                agentgov_version=__version__,
                mode=self.mode,
                tool_names=self.registry.names(),
                report=report,
                event_log_ref=ref,
                terminal=terminal,
            )

        def _write(bundle: EvidenceBundle) -> None:
            if write_bundle and isinstance(self.log, JsonlEventLog):
                out = self.log.path.with_suffix(".bundle.json")
                out.write_text(
                    json.dumps(bundle.model_dump(mode="json"), indent=2, sort_keys=True),
                    encoding="utf-8",
                )

        if halted:
            self.log.emit(
                FinalizeAttemptedEvent(
                    event_id=self.rng.uuid(),
                    session_id=self.session_id,
                    turn_id="finalize",
                    timestamp=self.clock.now(),
                    outcome="halted",
                    blocking_rail_ids=(),
                )
            )
            bundle = _seal("halted")
            _write(bundle)
            return FinalizeResult(ok=False, violations=(), bundle=bundle)

        violations = tuple(run_finalize_rails(self._rails, self.state))
        outcome = "blocked" if violations else "succeeded"
        self.log.emit(
            FinalizeAttemptedEvent(
                event_id=self.rng.uuid(),
                session_id=self.session_id,
                turn_id="finalize",
                timestamp=self.clock.now(),
                outcome=outcome,
                blocking_rail_ids=tuple(v.rail_id for v in violations),
            )
        )
        if violations:
            return FinalizeResult(ok=False, violations=violations, bundle=None)

        bundle = _seal("finalized")
        _write(bundle)
        return FinalizeResult(ok=True, violations=(), bundle=bundle)

    def _all_events(self) -> list[Event]:
        """Read every event from this harness's log, file- or memory-backed."""
        if isinstance(self.log, JsonlEventLog):
            return list(read_jsonl(self.log.path))
        return list(self.log.events())

    # --------------------------------------------------------------- internals
    def _bind_checkpoint(self, ctx: ToolContext, turn: str) -> None:
        def _checkpoint(*, trigger: str, proposal: str) -> Any:
            cid = checkpoint_id(trigger, proposal)
            self.log.emit(
                CheckpointRequestedEvent(
                    event_id=self.rng.uuid(),
                    session_id=self.session_id,
                    turn_id=turn,
                    timestamp=self.clock.now(),
                    checkpoint_id=cid,
                    trigger=trigger,
                    proposal=proposal,
                )
            )
            if self.responder is None:
                raise CheckpointPending(
                    f"checkpoint {trigger!r} has no responder; call blocked"
                )
            decision = self.responder.respond(
                checkpoint_id=cid, trigger=trigger, proposal=proposal
            )
            self.log.emit(
                CheckpointDecidedEvent(
                    event_id=self.rng.uuid(),
                    session_id=self.session_id,
                    turn_id=turn,
                    timestamp=self.clock.now(),
                    checkpoint_id=cid,
                    decision=decision.decision,
                    reason=decision.reason,
                    actor=decision.actor,
                )
            )
            if decision.halt:
                raise RunHalted(
                    checkpoint_id=cid,
                    trigger=trigger,
                    actor=decision.actor,
                    reason=decision.reason,
                )
            if not decision.approved:
                raise CheckpointPending(
                    f"checkpoint {trigger!r} denied by {decision.actor}"
                )
            return decision

        ctx.checkpoint = _checkpoint  # type: ignore[method-assign]


__all__ = ["Harness"]
