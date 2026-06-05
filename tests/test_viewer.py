"""Viewer renders local logs and store-backed ingest identically."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agentgov import (
    FixedClock,
    Harness,
    JsonlEventLog,
    Mutation,
    RailResult,
    Registry,
    Result,
    SeededRng,
    read_jsonl,
)
from agentgov_viewer.server import create_app
from pydantic import BaseModel


class A(BaseModel):
    amount: float


def _write_log(path):
    hz = Harness(
        app="t",
        registry=Registry(),
        log=JsonlEventLog(path),
        clock=FixedClock(),
        rng=SeededRng(),
        session_id="s",
    )

    @hz.tool(args=A, result=A, layer="action")
    def add(args, ctx) -> Result[A]:
        rid = ctx.rng.uuid()
        return Result(A(amount=args.amount), mutations=[Mutation.set(f"i.{rid}", args.amount)])

    @hz.rail(id="cap")
    def cap(state) -> RailResult:
        total = sum(state.get("i", {}).values())
        return RailResult.reject("cap") if total > 50 else RailResult.passed()

    hz.call("add", {"amount": 30})  # commit
    hz.call("add", {"amount": 40})  # reject (70 > 50)


def test_local_calls_and_inspector(tmp_path):
    log_path = tmp_path / "log.jsonl"
    _write_log(log_path)
    app = create_app(local_paths=[log_path], store_path=tmp_path / "s.sqlite3")
    client = TestClient(app)

    calls = client.get("/api/calls?source=local").json()
    assert len(calls) == 2
    statuses = {c["status"] for c in calls}
    assert statuses == {"committed", "rejected"}

    rejected = next(c for c in calls if c["status"] == "rejected")
    assert rejected["rails"]  # has a rail violation
    assert rejected["error"]["kind"] == "rail_violation"

    events = client.get(
        f"/api/events?source=local&session_id={rejected['session_id']}&turn_id={rejected['turn_id']}"
    ).json()
    assert any(e["type"] == "rail.violated" for e in events)

    verify = client.get("/api/verify?source=local").json()
    assert verify["ok"] is True


def test_ingest_store_renders_identically(tmp_path):
    log_path = tmp_path / "log.jsonl"
    _write_log(log_path)
    app = create_app(local_paths=[log_path], store_path=tmp_path / "s.sqlite3")
    client = TestClient(app)

    payload = [e.model_dump(mode="json") for e in read_jsonl(log_path)]
    resp = client.post("/ingest", json=payload)
    assert resp.json()["ingested"] == len(payload)

    local_calls = client.get("/api/calls?source=local").json()
    store_calls = client.get("/api/calls?source=store").json()
    # Same number of calls and same statuses, regardless of path.
    assert len(store_calls) == len(local_calls)
    assert {c["status"] for c in store_calls} == {c["status"] for c in local_calls}


def test_index_served(tmp_path):
    app = create_app(local_paths=[], store_path=tmp_path / "s.sqlite3")
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "agentgov" in r.text
