"""Replay: rebuild state from an event log and verify the hash chain.

Replay is the proof that the log is the source of truth. Folding the
``state.mutation`` events through :func:`agentgov.state.apply` reconstructs the
exact state, and :func:`state_hash` over the result must match the hash the
live run produced. :func:`verify_chain` independently confirms the log was not
tampered with after the fact.
"""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Iterable, Iterator
from pathlib import Path

from pydantic import TypeAdapter

from .events import Event, StateMutationEvent, chain_hash
from .state import Mutation, State, apply, state_hash

_EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


def read_jsonl(path: str | os.PathLike[str]) -> Iterator[Event]:
    """Stream events from a JSONL log, parsing each line."""
    p = Path(path)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            yield _EVENT_ADAPTER.validate_python(json.loads(line))


def replay(events: Iterable[Event]) -> State:
    """Rebuild state by folding every ``state.mutation`` event in order."""
    state: State = {}
    for event in events:
        if isinstance(event, StateMutationEvent):
            # Deep-copy the value: a set-at-nested-path mutation would otherwise
            # mutate a prior event's payload in place (shared reference),
            # corrupting its event_hash and breaking verify_chain.
            apply(state, Mutation(op=event.op, path=event.path, value=copy.deepcopy(event.value)))
    return state


def replay_from_jsonl(path: str | os.PathLike[str]) -> State:
    """Replay a JSONL log from ``path`` and return the rebuilt state."""
    return replay(read_jsonl(path))


def verify_chain(events: Iterable[Event]) -> bool:
    """Return True iff every event's ``event_hash`` matches the recomputed chain."""
    prev: str | None = None
    for event in events:
        payload = _EVENT_ADAPTER.dump_python(event, mode="json")
        expected = chain_hash(prev, payload)
        if event.event_hash != expected or event.prev_hash != prev:
            return False
        prev = event.event_hash
    return True


__all__ = [
    "read_jsonl",
    "replay",
    "replay_from_jsonl",
    "state_hash",
    "verify_chain",
]
