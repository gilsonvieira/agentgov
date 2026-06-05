"""Generic state model: a plain ``dict`` mutated through dotted-path ops.

A richly-typed state aggregate is always an option, but the SDK default is
deliberately schemaless: state is a ``dict[str, Any]`` and a tool never mutates
it directly — it *returns* a list of :class:`Mutation` values. The executor
applies them to a deep-copied candidate, runs rails over the candidate, and
only then commits. This is what makes the ``@tool`` examples work with zero
ceremony while preserving the event-sourced, replayable, rollback-on-reject
contract.

``state_hash`` is the determinism anchor: a canonical JSON encoding (sorted
keys, compact separators, floats rounded to 12 significant figures) hashed with
blake2b. Replay of the same mutation events reproduces the same hash byte-for-
byte across machines.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Literal

State = dict[str, Any]

MutationOp = Literal["set", "append", "delete"]


@dataclass(frozen=True)
class Mutation:
    """A single declarative change to state, addressed by a dotted path.

    ``path`` segments traverse nested dicts (``"refunds.r1.amount"``).
    Intermediate dicts are created on ``set``/``append`` as needed.
    """

    op: MutationOp
    path: str
    value: Any = None

    @classmethod
    def set(cls, path: str, value: Any) -> Mutation:
        """Set ``path`` to ``value`` (creating intermediate dicts)."""
        return cls(op="set", path=path, value=value)

    @classmethod
    def append(cls, path: str, value: Any) -> Mutation:
        """Append ``value`` to the list at ``path`` (creating it if absent)."""
        return cls(op="append", path=path, value=value)

    @classmethod
    def delete(cls, path: str) -> Mutation:
        """Delete the key at ``path`` (no-op if absent)."""
        return cls(op="delete", path=path)


def _segments(path: str) -> list[str]:
    if not path:
        raise ValueError("mutation path must be non-empty")
    return path.split(".")


def _descend(state: State, segments: list[str], *, create: bool) -> State:
    node: Any = state
    for seg in segments[:-1]:
        if not isinstance(node, dict):
            raise ValueError(f"cannot descend into non-dict at segment {seg!r}")
        if seg not in node:
            if not create:
                raise KeyError(seg)
            node[seg] = {}
        node = node[seg]
    if not isinstance(node, dict):
        raise ValueError(f"path parent is not a dict for {segments!r}")
    return node


def apply(state: State, mutation: Mutation) -> State:
    """Apply ``mutation`` to ``state`` in place and return it.

    The executor passes a deep-copied candidate, so in-place mutation here
    never touches authoritative state until commit.
    """
    segments = _segments(mutation.path)
    leaf = segments[-1]
    if mutation.op == "set":
        parent = _descend(state, segments, create=True)
        parent[leaf] = mutation.value
    elif mutation.op == "append":
        parent = _descend(state, segments, create=True)
        existing = parent.get(leaf)
        if existing is None:
            parent[leaf] = [mutation.value]
        elif isinstance(existing, list):
            existing.append(mutation.value)
        else:
            raise ValueError(f"cannot append to non-list at {mutation.path!r}")
    elif mutation.op == "delete":
        try:
            parent = _descend(state, segments, create=False)
        except KeyError:
            return state
        parent.pop(leaf, None)
    else:  # pragma: no cover - exhaustive
        raise ValueError(f"unknown mutation op: {mutation.op!r}")
    return state


_FLOAT_SIG_FIGS = 12


def _normalise_floats(value: Any) -> Any:
    if isinstance(value, float):
        if value == 0.0 or not math.isfinite(value):
            return value
        digits = _FLOAT_SIG_FIGS - math.floor(math.log10(abs(value))) - 1
        return round(value, digits)
    if isinstance(value, dict):
        return {k: _normalise_floats(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise_floats(v) for v in value]
    return value


def state_hash(state: State) -> str:
    """Deterministic blake2b-128 digest over the canonical state encoding."""
    normalised = _normalise_floats(state)
    payload = json.dumps(normalised, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=16).hexdigest()


__all__ = ["Mutation", "MutationOp", "State", "apply", "state_hash"]
