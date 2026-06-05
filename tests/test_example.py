"""The refunds example behaves as documented, end to end."""

from __future__ import annotations

from agentgov import (
    ApproveAll,
    DenyAll,
    FixedClock,
    InMemoryEventLog,
    SeededRng,
)

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.refunds_agent.app import build_harness  # noqa: E402


def _det(**kw):
    return build_harness(
        log=InMemoryEventLog(),
        clock=FixedClock(),
        rng=SeededRng(seed=1),
        **kw,
    )


def test_small_refunds_commit():
    hz = _det(responder=ApproveAll())
    for amt in (100, 200, 300):
        assert hz.call("issue_refund", {"order_id": "o", "amount": amt}).ok
    assert len(hz.state["refunds"]) == 3


def test_over_cap_rolls_back():
    hz = _det(responder=ApproveAll())
    hz.call("issue_refund", {"order_id": "o", "amount": 400})
    hz.call("issue_refund", {"order_id": "o", "amount": 400})
    r = hz.call("issue_refund", {"order_id": "o", "amount": 400})  # 1200 > 1000
    assert not r.ok
    assert r.error.kind == "rail_violation"
    assert len(hz.state["refunds"]) == 2


def test_large_refund_denied_at_checkpoint():
    hz = _det(responder=DenyAll())
    r = hz.call("issue_refund", {"order_id": "o", "amount": 750})
    assert not r.ok
    assert r.error.kind == "checkpoint_pending"
    assert hz.state.get("refunds", {}) == {}
