"""A governed MCP gateway — the no-code adoption path (spec step 5).

The idea: instead of pointing an MCP agent at raw tool servers, point it at a
gateway that proxies every ``call_tool`` through an agentgov :class:`Harness`.
The agent speaks plain MCP; governance (transaction boundary, rails,
checkpoints, audit log) applies with zero changes to the agent's code.

This module is a dependency-free *stub*: it maps the two MCP tool primitives —
``list_tools`` and ``call_tool`` — onto the harness, returning MCP-shaped result
dicts. To wire it into a real server, install the ``mcp`` package and forward
its handlers to :class:`GovernedGateway` (see this folder's README).
"""

from __future__ import annotations

from typing import Any

from agentgov import Harness


class GovernedGateway:
    """Proxies MCP tool calls through a governed :class:`Harness`."""

    def __init__(self, harness: Harness) -> None:
        """Wrap ``harness``; its registry defines the exposed tool surface."""
        self.hz = harness

    def list_tools(self) -> list[dict[str, Any]]:
        """Return MCP tool descriptors generated from the harness registry."""
        tools = []
        for name in self.hz.registry.names():
            spec = self.hz.registry.get(name)
            tools.append(
                {
                    "name": name,
                    "description": (spec.fn.__doc__ or "").strip().split("\n")[0],
                    "inputSchema": spec.args_model.model_json_schema(),
                }
            )
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run ``name`` under governance; return an MCP ``call_tool`` result dict."""
        if name not in self.hz.registry.names():
            return _error(f"unknown tool {name!r}")
        result = self.hz.call(name, arguments)
        if result.ok and result.result is not None:
            return {
                "isError": False,
                "content": [{"type": "text", "text": result.result.model_dump_json()}],
            }
        reason = f"{result.error.kind}: {result.error}" if result.error else "rejected"
        out = _error(reason)
        if result.violations:
            out["violations"] = [v.rail_id for v in result.violations]
        return out


def _error(message: str) -> dict[str, Any]:
    return {"isError": True, "content": [{"type": "text", "text": message}]}


def _demo() -> None:
    """Build a tiny governed harness and exercise the gateway over it."""
    import json

    from pydantic import BaseModel, Field

    from agentgov import Mutation, RailResult, Registry, Result

    class SendArgs(BaseModel):
        """Send a message to a recipient."""

        to: str
        body: str = Field(min_length=1)

    class SendResult(BaseModel):
        message_id: str

    hz = Harness(app="mcp-demo", registry=Registry())

    @hz.tool(args=SendArgs, result=SendResult, layer="action")
    def send_message(args: SendArgs, ctx) -> Result[SendResult]:
        """Send a message and record it in state."""
        mid = ctx.rng.uuid()
        return Result(
            SendResult(message_id=mid),
            mutations=[Mutation.append("sent", {"to": args.to, "body": args.body})],
        )

    @hz.rail(id="send-budget")
    def send_budget(state) -> RailResult:
        if len(state.get("sent", [])) > 2:
            return RailResult.reject("send-budget", "no more than 2 messages per session")
        return RailResult.passed()

    gw = GovernedGateway(hz)
    print("== tools ==")
    print(json.dumps(gw.list_tools(), indent=2))
    print("\n== calls ==")
    for i in range(4):
        out = gw.call_tool("send_message", {"to": f"user{i}", "body": "hi"})
        print(f"  call {i}: isError={out['isError']}  {out['content'][0]['text']}")
    print(f"\naudit log: {hz.log.path}")


if __name__ == "__main__":
    _demo()
