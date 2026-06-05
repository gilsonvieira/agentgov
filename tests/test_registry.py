"""Registry rejects unknown + duplicate tool names."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agentgov import Registry, Result


class A(BaseModel):
    x: int = 0


def test_duplicate_registration_raises():
    reg = Registry()

    @reg.tool(args=A, result=A, name="t")
    def t(args, ctx) -> Result[A]:
        return Result(A())

    with pytest.raises(ValueError, match="already registered"):

        @reg.tool(args=A, result=A, name="t")
        def t2(args, ctx) -> Result[A]:
            return Result(A())


def test_unknown_lookup_raises():
    reg = Registry()
    with pytest.raises(KeyError, match="unknown tool"):
        reg.get("nope")


def test_names_in_insertion_order():
    reg = Registry()
    for n in ("b", "a", "c"):

        @reg.tool(args=A, result=A, name=n)
        def fn(args, ctx) -> Result[A]:
            return Result(A())

    assert reg.names() == ("b", "a", "c")
