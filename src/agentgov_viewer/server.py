"""FastAPI viewer for agentgov event logs.

Two data paths, one set of views:

* **local** — read one or more ``.jsonl`` logs from disk at startup.
* **store** — a SQLite-backed store that ``POST /ingest`` writes to; the same
  timeline/inspector endpoints render from it identically.

The browser UI (``static/index.html``) calls ``/api/calls`` for the timeline
and ``/api/events`` for the raw, chain-verified event stream behind a call.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from agentgov.events import EVENT_TYPES
from agentgov.replay import read_jsonl, verify_chain

_STATIC = Path(__file__).resolve().parent / "static"

_COMMIT_TYPES = {"tool.committed"}
_REJECT_TYPES = {"tool.rejected"}


def _event_to_dict(event: Any) -> dict[str, Any]:
    return event.model_dump(mode="json")


def _load_local(paths: list[Path]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for p in paths:
        for ev in read_jsonl(p):
            d = _event_to_dict(ev)
            d["_source_file"] = p.name
            events.append(d)
    return events


def _build_calls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group the flat event stream into one entry per tool call (turn)."""
    by_turn: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for ev in events:
        key = (ev.get("session_id", "?"), ev.get("turn_id", "?"))
        by_turn[key].append(ev)

    calls: list[dict[str, Any]] = []
    for (session_id, turn_id), evs in by_turn.items():
        evs.sort(key=lambda e: e.get("seq", 0))
        status = "pending"
        tool_name = None
        layer = None
        duration = None
        error = None
        mutations = []
        rails = []
        checkpoints = []
        for e in evs:
            t = e["type"]
            if t == "tool.requested":
                tool_name = e.get("tool_name")
                layer = e.get("layer")
            elif t in _COMMIT_TYPES:
                status = "committed"
                tool_name = e.get("tool_name", tool_name)
                duration = e.get("duration_ms")
            elif t in _REJECT_TYPES:
                status = "rejected"
                tool_name = e.get("tool_name", tool_name)
                duration = e.get("duration_ms")
                error = {"kind": e.get("error_kind"), "message": e.get("error_message")}
            elif t == "state.mutation":
                mutations.append({"op": e["op"], "path": e["path"], "value": e.get("value")})
            elif t == "rail.violated":
                rails.append({"rail_id": e["rail_id"], "message": e["message"]})
            elif t in ("checkpoint.requested", "checkpoint.decided"):
                checkpoints.append(e)
        calls.append(
            {
                "session_id": session_id,
                "turn_id": turn_id,
                "seq": evs[0].get("seq", 0),
                "tool_name": tool_name,
                "layer": layer,
                "status": status,
                "duration_ms": duration,
                "error": error,
                "mutations": mutations,
                "rails": rails,
                "checkpoints": checkpoints,
                "event_count": len(evs),
            }
        )
    calls.sort(key=lambda c: c["seq"])
    return calls


class Store:
    """SQLite-backed event store for the ingest path."""

    def __init__(self, path: str | Path) -> None:
        """Open (or create) the SQLite store at ``path``."""
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "seq INTEGER, session_id TEXT, turn_id TEXT, type TEXT, "
            "ts TEXT, payload TEXT)"
        )
        self.conn.commit()

    def ingest(self, events: list[dict[str, Any]]) -> int:
        rows = [
            (
                e.get("seq", 0),
                e.get("session_id", "?"),
                e.get("turn_id", "?"),
                e.get("type", "?"),
                e.get("timestamp", ""),
                json.dumps(e, sort_keys=True),
            )
            for e in events
        ]
        self.conn.executemany("INSERT INTO events VALUES (?,?,?,?,?,?)", rows)
        self.conn.commit()
        return len(rows)

    def all_events(self) -> list[dict[str, Any]]:
        cur = self.conn.execute("SELECT payload FROM events ORDER BY session_id, seq")
        return [json.loads(r[0]) for r in cur.fetchall()]


def create_app(*, local_paths: list[Path] | None = None, store_path: str | Path) -> FastAPI:
    """Build the FastAPI app bound to optional local logs + a SQLite store."""
    app = FastAPI(title="agentgov viewer")
    local_events = _load_local(local_paths or [])
    store = Store(store_path)

    def _events_for(source: str) -> list[dict[str, Any]]:
        if source == "store":
            return store.all_events()
        return local_events

    @app.get("/api/calls")
    def api_calls(source: str = Query("local")) -> JSONResponse:
        return JSONResponse(_build_calls(_events_for(source)))

    @app.get("/api/events")
    def api_events(
        source: str = Query("local"),
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> JSONResponse:
        evs = _events_for(source)
        if session_id is not None:
            evs = [e for e in evs if e.get("session_id") == session_id]
        if turn_id is not None:
            evs = [e for e in evs if e.get("turn_id") == turn_id]
        evs = sorted(evs, key=lambda e: e.get("seq", 0))
        return JSONResponse(evs)

    @app.get("/api/verify")
    def api_verify(source: str = Query("local")) -> JSONResponse:
        from pydantic import TypeAdapter

        from agentgov.events import Event

        adapter: TypeAdapter[Event] = TypeAdapter(Event)
        by_session: dict[str, list[Any]] = defaultdict(list)
        for e in _events_for(source):
            clean = {k: v for k, v in e.items() if not k.startswith("_")}
            by_session[e.get("session_id", "?")].append(adapter.validate_python(clean))
        results = {
            sid: verify_chain(sorted(evs, key=lambda x: x.seq))
            for sid, evs in by_session.items()
        }
        return JSONResponse({"sessions": results, "ok": all(results.values())})

    @app.post("/ingest")
    def ingest(events: list[dict[str, Any]]) -> JSONResponse:
        known = [e for e in events if e.get("type") in EVENT_TYPES]
        n = store.ingest(known)
        return JSONResponse({"ingested": n})

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
    return app


def main() -> None:
    """CLI entry point: serve the viewer over a local log and/or a store."""
    parser = argparse.ArgumentParser(description="agentgov local event-log viewer")
    parser.add_argument("--log", action="append", default=[], help="path to a .jsonl event log")
    parser.add_argument("--runs", help="directory of .jsonl logs to load")
    parser.add_argument("--store", default=".agentgov/viewer.sqlite3", help="SQLite store path")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    ns = parser.parse_args()

    paths: list[Path] = [Path(p) for p in ns.log]
    if ns.runs:
        paths.extend(sorted(Path(ns.runs).glob("**/*.jsonl")))

    import uvicorn

    Path(ns.store).parent.mkdir(parents=True, exist_ok=True)
    app = create_app(local_paths=paths, store_path=ns.store)
    print(f"agentgov viewer: http://{ns.host}:{ns.port}  ({len(paths)} log file(s))")
    uvicorn.run(app, host=ns.host, port=ns.port)


if __name__ == "__main__":
    main()
