# agentgov

![license](https://img.shields.io/badge/license-Apache--2.0-blue)
![python](https://img.shields.io/badge/python-3.12%2B-blue)

**A governance harness for agent tool calls.** Wrap a tool, and every
invocation becomes **transactional**, **rail-checked**, **human-gated**,
**fully audited**, and **replayable** — without coupling your code to any model
vendor.

> Tracing tells you what your agent did *after* it broke something. agentgov
> makes the dangerous action impossible to commit in the first place, and leaves
> a replayable, audit-grade record proving it.

A chat transcript is not an audit trail. When an agent issues a refund, edits a
record, or calls an internal API, you need to (1) stop the bad action before it
commits, and (2) hand someone a record they can replay and verify. That is what
this library does, in-process, with no cloud dependency.

## Install

```bash
pip install -e ".[viewer]"
```

## 10-minute quickstart

Each step builds on the last. Paste them into a file and run it.

### 1. Wrap a tool

A tool declares typed `args`/`result` and returns **requested mutations** — it
never writes state directly. The engine runs it inside a transaction boundary.

```python
from pydantic import BaseModel, Field
from agentgov import Harness, Result, Mutation, RailResult

class RefundArgs(BaseModel):
    order_id: str
    amount: float = Field(gt=0)

class RefundResult(BaseModel):
    refund_id: str

hz = Harness(app="refunds-agent", mode="enforce")  # mode="observe" to log without blocking

@hz.tool(args=RefundArgs, result=RefundResult, layer="action")
def issue_refund(args, ctx) -> Result[RefundResult]:
    rid = ctx.rng.uuid()
    return Result(
        RefundResult(refund_id=rid),
        mutations=[Mutation.set(f"refunds.{rid}", {"amount": args.amount})],
    )
```

### 2. Add a rail (enforcement)

A rail is a **pure function over candidate state** that can *reject* a
transition. On rejection the call returns `ok=False`, **state is unchanged**,
and a `rail.violated` + `tool.rejected` pair is written to the log.

```python
@hz.rail(id="refund-cap")
def cap(state) -> RailResult:
    total = sum(r["amount"] for r in state.get("refunds", {}).values())
    if total > 1000:
        return RailResult.reject("refund-cap", "daily cap exceeded")
    return RailResult.passed()

print(hz.call("issue_refund", {"order_id": "o1", "amount": 250}).ok)   # True
print(hz.call("issue_refund", {"order_id": "o2", "amount": 900}).ok)   # False — rolled back
```

### 3. Replay and verify the chain

The event log is the source of truth. Replaying the `state.mutation` events
rebuilds state exactly; `verify_chain` proves the log was not edited after the
fact.

```python
from agentgov import read_jsonl, replay, state_hash, verify_chain

events = list(read_jsonl(hz.log.path))
assert verify_chain(events)                       # tamper-evident
assert state_hash(replay(events)) == state_hash(hz.state)  # deterministic
```

### 4. Gate a risky action on a human

A tool calls `ctx.checkpoint(...)` to pause for a decision. The harness emits
`checkpoint.requested`, asks a responder, and emits `checkpoint.decided`. With
no responder (or a denial) the call is blocked and rolled back — the gate holds.

```python
from agentgov import ApproveAll

hz = Harness(app="refunds-agent", responder=ApproveAll())  # swap for a real inbox

@hz.tool(args=RefundArgs, result=RefundResult, layer="action")
def large_refund(args, ctx) -> Result[RefundResult]:
    if args.amount > 1000:
        ctx.checkpoint(trigger="large_refund", proposal=f"refund {args.amount}")
    rid = ctx.rng.uuid()
    return Result(RefundResult(refund_id=rid),
                  mutations=[Mutation.set(f"refunds.{rid}", {"amount": args.amount})])
```

### 5. Finalize → a sealed evidence bundle

`finalize()` runs the terminal gate (every rail, including `finalize_only`
ones) over the final state. On a clean pass it returns a self-contained,
hash-sealed `EvidenceBundle`: final state, chain verdict, checkpoint decisions,
tool/harness versions, and an optional report. This is what you hand a regulator
or a security reviewer — inspectable without rerunning the model.

```python
from agentgov import verify_bundle

result = hz.finalize(report={"reviewer": "compliance"}, write_bundle=True)
assert result.ok
assert verify_bundle(result.bundle)               # seal + state hash check
# write_bundle=True also drops <log>.bundle.json next to the event log
```

### 6. Open the viewer

```bash
agentgov-viewer --log .agentgov/refunds-agent/<session>.jsonl
```

A timeline of sessions → turns → tool calls (committed/rejected, with rail
violations and checkpoints inline), plus a per-call inspector and a
chain-verification endpoint.

## What you get

- **Transaction boundary** — tool bodies return mutations; the engine applies
  them to a candidate, runs rails, and commits only on pass (rollback on fail).
- **Hard rails** — invariants checked against post-mutation candidate state;
  they *reject*, they don't merely advise the model.
- **Human checkpoints** — `ctx.checkpoint(...)` pauses for a recorded decision.
- **Hash-chained event log** — tamper-evident JSONL audit trail; the log *is*
  the state.
- **Deterministic replay** — `replay(events)` reproduces `state_hash` exactly
  under `FixedClock` / `SeededRng`.
- **Evidence bundles** — `finalize()` seals a portable, verifiable record.
- **Framework-independent kernel** — plain Python; the kernel imports no
  `pydantic_ai` or LLM SDK and knows nothing about the brain that drives it.

## Examples

- [`examples/refunds_agent`](examples/refunds_agent) — the end-to-end loop:
  typed tool, a cap rail that rolls back, a checkpoint that pauses large
  refunds. Run: `python -m examples.refunds_agent.app`
- [`examples/mcp_gateway`](examples/mcp_gateway) — a governed MCP gateway: proxy
  any MCP agent's tool calls through the harness with **zero agent code
  changes**. Run: `python -m examples.mcp_gateway.gateway`

## Artifacts: non-audited runtime scratch

Audited state must be JSON-serializable (it is hashed and replayed). For runtime
objects that should *not* be event-sourced — a fitted model, an open connection,
a dataframe — use `ctx.artifacts`, a plain dict the harness holds and passes
into every call. Artifacts persist across `hz.call(...)` but are never logged.

## Chaining calls across processes

A `JsonlEventLog` resumes its hash chain when reopened, so a run can span many
processes — an agent calling one tool per invocation — and still produce a
single, continuously verifiable log. Rebuild state at the start of each process
by replaying:

```python
from agentgov import Harness, JsonlEventLog, Registry, replay_from_jsonl

path = "runs/session.jsonl"
hz = Harness(
    app="trainer",
    registry=Registry(),
    log=JsonlEventLog(path),            # re-opens; continues the chain
    state=replay_from_jsonl(path),      # state rebuilt from prior events
)
```

Give each logical call a distinct `turn_id` (`hz.call(tool, args, turn_id=...)`)
so the viewer renders them as separate timeline entries.

## Development

```bash
pip install -e ".[dev,viewer]"
pytest
ruff check src tests examples
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow and
[SECURITY.md](SECURITY.md) to report a vulnerability.

## License

[Apache-2.0](LICENSE).
