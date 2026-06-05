"""The governed MCP gateway proxies tool calls and surfaces rail rejections."""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import BaseModel

from agentgov import (
    FixedClock,
    Harness,
    InMemoryEventLog,
    Mutation,
    RailResult,
    Registry,
    Result,
    SeededRng,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.mcp_gateway.gateway import GovernedGateway  # noqa: E402


class PingArgs(BaseModel):
    label: str


class PingResult(BaseModel):
    seq: int


def _gateway() -> GovernedGateway:
    hz = Harness(
        app="gw-test",
        registry=Registry(),
        log=InMemoryEventLog(),
        clock=FixedClock(),
        rng=SeededRng(seed=3),
        session_id="s1",
    )

    @hz.tool(args=PingArgs, result=PingResult, layer="action")
    def ping(args: PingArgs, ctx) -> Result[PingResult]:
        """Record a ping."""
        n = len(ctx.state.get("pings", []))
        return Result(PingResult(seq=n), mutations=[Mutation.append("pings", args.label)])

    @hz.rail(id="ping-budget")
    def budget(state) -> RailResult:
        if len(state.get("pings", [])) > 1:
            return RailResult.reject("ping-budget", "one ping only")
        return RailResult.passed()

    return GovernedGateway(hz)


def test_list_tools_exposes_json_schema():
    gw = _gateway()
    tools = gw.list_tools()
    assert [t["name"] for t in tools] == ["ping"]
    assert tools[0]["inputSchema"]["properties"]["label"]["type"] == "string"


def test_call_tool_governs_and_reports_rail_rejection():
    gw = _gateway()
    ok = gw.call_tool("ping", {"label": "a"})
    assert ok["isError"] is False
    blocked = gw.call_tool("ping", {"label": "b"})
    assert blocked["isError"] is True
    assert blocked["violations"] == ["ping-budget"]


def test_unknown_tool_is_rejected():
    gw = _gateway()
    out = gw.call_tool("nope", {})
    assert out["isError"] is True
    assert "unknown tool" in out["content"][0]["text"]
