"""agentgov — a governance harness for agent tool calls.

Wrap a tool with ``@tool``, run it through a ``Harness``, and get a
transactional, rail-checked, fully-audited, replayable call. The audit log is
the product: an append-only, hash-chained record you can replay to reproduce
state exactly.

    from agentgov import Harness, tool, Result, Mutation, RailResult

    hz = Harness(app="refunds-agent", mode="enforce")

    @hz.tool(args=RefundArgs, result=RefundResult, layer="action")
    def issue_refund(args, ctx) -> Result[RefundResult]:
        rid = ctx.rng.uuid()
        return Result(
            RefundResult(refund_id=rid),
            mutations=[Mutation.set(f"refunds.{rid}", {"amount": args.amount})],
        )

    @hz.rail(id="refund-cap")
    def cap(state) -> RailResult:
        total = sum(r["amount"] for r in state.get("refunds", {}).values())
        return RailResult.reject("refund-cap") if total > 1000 else RailResult.passed()

    hz.call("issue_refund", {"amount": 250})
"""

from __future__ import annotations

from .bundle import EvidenceBundle, build_bundle, verify_bundle
from .checkpoints import (
    ApproveAll,
    CheckpointDecision,
    CheckpointResponder,
    DenyAll,
    checkpoint_id,
)
from .context import ToolContext
from .contracts import (
    CheckpointPending,
    PostconditionError,
    PreconditionError,
    RailViolation,
    Result,
    ToolError,
    ToolSpec,
)
from .eventlog import InMemoryEventLog, JsonlEventLog, NoopRedactor, Redactor
from .events import Event
from .executor import ToolRunResult, run_tool
from .harness import FinalizeResult, Harness
from .hosts import (
    Clock,
    DefaultRng,
    FixedClock,
    InMemoryStorage,
    Rng,
    SeededRng,
    Storage,
    SystemClock,
)
from .rails import Rail, RailResult, Violation, run_finalize_rails, run_rails
from .registry import Registry, default_registry, tool
from .replay import read_jsonl, replay, replay_from_jsonl, verify_chain
from .state import Mutation, State, apply, state_hash

__version__ = "0.1.0"

__all__ = [
    "ApproveAll",
    "CheckpointDecision",
    "CheckpointPending",
    "CheckpointResponder",
    "Clock",
    "DefaultRng",
    "DenyAll",
    "Event",
    "EvidenceBundle",
    "FinalizeResult",
    "FixedClock",
    "Harness",
    "InMemoryEventLog",
    "InMemoryStorage",
    "JsonlEventLog",
    "Mutation",
    "NoopRedactor",
    "PostconditionError",
    "PreconditionError",
    "Rail",
    "RailResult",
    "RailViolation",
    "Redactor",
    "Registry",
    "Result",
    "Rng",
    "SeededRng",
    "State",
    "Storage",
    "SystemClock",
    "ToolContext",
    "ToolError",
    "ToolRunResult",
    "ToolSpec",
    "Violation",
    "__version__",
    "apply",
    "build_bundle",
    "checkpoint_id",
    "default_registry",
    "read_jsonl",
    "replay",
    "replay_from_jsonl",
    "run_finalize_rails",
    "run_rails",
    "run_tool",
    "state_hash",
    "tool",
    "verify_bundle",
    "verify_chain",
]
