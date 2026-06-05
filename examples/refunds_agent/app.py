"""Refunds agent wiring: tools, rails, and a runnable demo.

Run it::

    python -m examples.refunds_agent.app

It issues a few refunds, trips the daily cap (state rolls back), and shows a
large refund pausing at a checkpoint. The audit log lands under
``.agentgov/refunds-agent/<session>.jsonl`` — point the viewer at it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentgov import ApproveAll, DenyAll, Harness, Mutation, RailResult, Registry, Result

DAILY_CAP = 1000.0
CHECKPOINT_THRESHOLD = 500.0


class RefundArgs(BaseModel):
    """Inputs for issuing a refund."""

    order_id: str
    amount: float = Field(gt=0)


class RefundResult(BaseModel):
    """The id of the issued refund."""

    refund_id: str


def build_harness(*, responder=None, **kw) -> Harness:
    """Construct a refunds harness with the tool and rails registered.

    Each harness gets its own :class:`Registry` so building several (in the demo
    or in tests) never hits a duplicate-registration error.
    """
    kw.setdefault("registry", Registry())
    hz = Harness(app="refunds-agent", responder=responder, **kw)

    @hz.tool(args=RefundArgs, result=RefundResult, layer="action")
    def issue_refund(args: RefundArgs, ctx) -> Result[RefundResult]:
        # Large refunds pause for a human before committing.
        if args.amount >= CHECKPOINT_THRESHOLD:
            ctx.checkpoint(
                trigger="large_refund",
                proposal=f"refund {args.amount} on order {args.order_id}",
            )
        rid = ctx.rng.uuid()
        return Result(
            RefundResult(refund_id=rid),
            mutations=[
                Mutation.set(
                    f"refunds.{rid}",
                    {"order_id": args.order_id, "amount": args.amount},
                ),
            ],
        )

    @hz.rail(id="refund-cap")
    def refund_cap(state) -> RailResult:
        total = sum(r["amount"] for r in state.get("refunds", {}).values())
        if total > DAILY_CAP:
            return RailResult.reject("refund-cap", f"daily cap {DAILY_CAP} exceeded ({total})")
        return RailResult.passed()

    return hz


def main() -> None:
    """Run the demo end to end."""
    hz = build_harness(responder=ApproveAll())

    print("== small refunds (commit) ==")
    for amt in (200, 300, 400):
        r = hz.call("issue_refund", {"order_id": f"o-{amt}", "amount": amt})
        print(f"  amount={amt:>4}  ok={r.ok}  refunds={len(hz.state.get('refunds', {}))}")

    print("== over the daily cap (rejected, state rolls back) ==")
    r = hz.call("issue_refund", {"order_id": "o-big", "amount": 500})
    print(f"  ok={r.ok}  error={r.error and r.error.kind}  refunds={len(hz.state.get('refunds', {}))}")

    print("== large refund denied at checkpoint (rejected) ==")
    hz2 = build_harness(responder=DenyAll())
    r = hz2.call("issue_refund", {"order_id": "o-huge", "amount": 750})
    print(f"  ok={r.ok}  error={r.error and r.error.kind}  refunds={len(hz2.state.get('refunds', {}))}")

    print(f"\naudit log: {hz.log.path}")


if __name__ == "__main__":
    main()
