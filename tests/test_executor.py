"""Transaction boundary: commit on pass, rollback on reject, schema errors."""

from __future__ import annotations

from agentgov import state_hash


def _types(log):
    return [e.type for e in log.events()]


def test_commit_on_rail_pass(make_harness):
    hz = make_harness()
    r = hz.call("add", {"amount": 100})
    assert r.ok
    assert len(hz.state["items"]) == 1
    assert "tool.committed" in _types(hz.log)
    assert "state.mutation" in _types(hz.log)


def test_rollback_on_rail_reject(make_harness):
    hz = make_harness(cap=150)
    assert hz.call("add", {"amount": 100}).ok
    before = state_hash(hz.state)
    r = hz.call("add", {"amount": 100})  # 200 > cap 150
    assert not r.ok
    assert r.error.kind == "rail_violation"
    # State is byte-identical to before the rejected call (rollback).
    assert state_hash(hz.state) == before
    assert len(hz.state["items"]) == 1
    types = _types(hz.log)
    assert "rail.violated" in types
    assert "tool.rejected" in types


def test_observe_mode_logs_but_commits(make_harness):
    hz = make_harness(mode="observe", cap=150)
    hz.call("add", {"amount": 100})
    r = hz.call("add", {"amount": 100})  # over cap, but observe mode commits
    assert r.ok
    assert len(hz.state["items"]) == 2
    assert "rail.violated" in _types(hz.log)
    assert "tool.committed" in _types(hz.log)


def test_postcondition_error_on_wrong_result_type(make_harness):
    hz = make_harness()
    r = hz.call("bad_result", {"amount": 1})
    assert not r.ok
    assert r.error.kind == "postcondition"
    assert hz.state == {}


def test_arg_validation_rejects_bad_input(make_harness):
    hz = make_harness()
    # amount must be > 0; pydantic should raise on validation.
    import pytest

    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        hz.call("add", {"amount": -5})
