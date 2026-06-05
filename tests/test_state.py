"""Generic state model: path mutations + canonical hashing."""

from __future__ import annotations

from agentgov import Mutation, apply, state_hash


def test_set_creates_nested_dicts():
    s: dict = {}
    apply(s, Mutation.set("a.b.c", 1))
    assert s == {"a": {"b": {"c": 1}}}


def test_append_creates_and_extends_list():
    s: dict = {}
    apply(s, Mutation.append("xs", 1))
    apply(s, Mutation.append("xs", 2))
    assert s == {"xs": [1, 2]}


def test_delete_is_noop_when_absent():
    s = {"a": 1}
    apply(s, Mutation.delete("missing.key"))
    apply(s, Mutation.delete("a"))
    assert s == {}


def test_state_hash_is_order_independent_for_dicts():
    a = {"x": 1, "y": 2}
    b = {"y": 2, "x": 1}
    assert state_hash(a) == state_hash(b)


def test_state_hash_changes_with_content():
    assert state_hash({"x": 1}) != state_hash({"x": 2})


def test_state_hash_rounds_floats():
    # 12 significant figures: differences below that collapse.
    assert state_hash({"v": 1.0000000000001}) == state_hash({"v": 1.0000000000002})
