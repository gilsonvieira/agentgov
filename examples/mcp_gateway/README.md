# Governed MCP gateway

Point any MCP-speaking agent at a gateway instead of your raw tool servers, and
every `call_tool` runs through an agentgov `Harness` — transaction boundary,
rails, checkpoints, and an audit log — with **zero changes to the agent**.

## Run the stub demo

```bash
python -m examples.mcp_gateway.gateway
```

It registers a `send_message` tool with a `send-budget` rail (max 2 messages),
then drives four calls through the gateway. The third and fourth come back
`isError=True` with the rail id that blocked them, and the audit log records the
whole sequence.

## Wiring it into a real MCP server

`GovernedGateway` is deliberately dependency-free. To expose it over the wire,
install the official `mcp` package and forward the two handlers:

```python
from mcp.server import Server
from mcp import types
from examples.mcp_gateway.gateway import GovernedGateway

gw = GovernedGateway(your_harness)
server = Server("agentgov-gateway")

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [types.Tool(**t) for t in gw.list_tools()]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    out = gw.call_tool(name, arguments)
    return [types.TextContent(type="text", text=c["text"]) for c in out["content"]]
```

The agent never learns it is governed; you get the audit trail for free.
