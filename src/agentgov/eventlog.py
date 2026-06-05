"""Event log: redaction + hash-chaining + durable JSONL append.

The log is the product surface — the audit record a governed call leaves
behind. Every event passes through a :class:`Redactor` (noop by default), gets
its chain fields assigned (``seq`` / ``prev_hash`` / ``event_hash``), and is
appended as one canonical JSON line, fsync'd per write so replay is safe after
a crash. ``InMemoryEventLog`` is the same contract without a file, for tests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from pydantic import TypeAdapter

from .events import Event, chain_hash

_EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


class Redactor(Protocol):
    """Transform an event payload dict before it is persisted."""

    def redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a redacted copy of ``payload``."""


class NoopRedactor:
    """Default redactor that passes payloads through unchanged."""

    def redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return ``payload`` unchanged."""
        return payload


class _ChainState:
    """Tracks the running sequence number and last hash for a log."""

    def __init__(self) -> None:
        self.seq = 0
        self.last_hash: str | None = None

    def stamp(self, event: Event) -> tuple[Event, dict[str, Any]]:
        """Assign chain fields to ``event`` and return (event, json payload)."""
        payload = _EVENT_ADAPTER.dump_python(event, mode="json")
        h = chain_hash(self.last_hash, payload)
        event = event.model_copy(
            update={"seq": self.seq, "prev_hash": self.last_hash, "event_hash": h},
        )
        self.seq += 1
        self.last_hash = h
        return event, _EVENT_ADAPTER.dump_python(event, mode="json")


class InMemoryEventLog:
    """List-backed event log; same emit contract as the JSONL writer."""

    def __init__(self, *, redactor: Redactor | None = None) -> None:
        """Start an empty in-memory log."""
        self._events: list[Event] = []
        self._redactor = redactor or NoopRedactor()
        self._chain = _ChainState()

    def emit(self, event: Event) -> Event:
        """Redact, chain-stamp, and store ``event``; return the stamped event."""
        stamped, payload = self._chain.stamp(event)
        redacted = self._redactor.redact(payload)
        final = _EVENT_ADAPTER.validate_python(redacted)
        self._events.append(final)
        return final

    def events(self) -> tuple[Event, ...]:
        """Return all stored events in append order."""
        return tuple(self._events)


class JsonlEventLog:
    """Durable JSON Lines event log with redaction + hash-chaining."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        redactor: Redactor | None = None,
    ) -> None:
        """Open (or create) the JSONL log at ``path``."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._redactor = redactor or NoopRedactor()
        self._chain = _ChainState()
        self._resume_chain()

    def _resume_chain(self) -> None:
        """Seed the chain from the last record so appends extend one chain.

        A governed run may span several processes (e.g. an agent calling one
        tool per invocation, chaining through the same log). Re-opening the file
        must continue the existing hash chain rather than restart it, or
        :func:`agentgov.replay.verify_chain` would reject the seam.
        """
        last: dict[str, Any] | None = None
        with self.path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if line:
                    last = json.loads(line)
        if last is not None:
            self._chain.seq = int(last["seq"]) + 1
            self._chain.last_hash = last["event_hash"]

    def emit(self, event: Event) -> Event:
        """Redact, chain-stamp, fsync-append ``event``; return the stamped event."""
        stamped, payload = self._chain.stamp(event)
        redacted = self._redactor.redact(payload)
        final = _EVENT_ADAPTER.validate_python(redacted)
        line = json.dumps(redacted, sort_keys=True, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return final


__all__ = [
    "InMemoryEventLog",
    "JsonlEventLog",
    "NoopRedactor",
    "Redactor",
]
