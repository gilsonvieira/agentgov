"""Tool registry + the ``@tool`` decorator.

The registry is an instantiable class (so tests get isolation) with a process-
global default instance backing the bare ``@tool`` decorator — matching the
zero-ceremony DX shown in the examples. Registering a duplicate name or looking
up an unknown name raises, so the tool surface is finite and explicit.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from .contracts import Result, ToolSpec

if TYPE_CHECKING:
    from .context import ToolContext


class Registry:
    """A finite, explicit set of registered tools."""

    def __init__(self) -> None:
        """Initialise an empty registry."""
        self._tools: dict[str, ToolSpec[Any, Any]] = {}

    def register(self, spec: ToolSpec[Any, Any]) -> None:
        """Register ``spec``; raise if the name is already taken."""
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name!r} already registered")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec[Any, Any]:
        """Look up a tool by name; raise ``KeyError`` if unknown."""
        if name not in self._tools:
            raise KeyError(f"unknown tool {name!r}")
        return self._tools[name]

    def names(self) -> tuple[str, ...]:
        """Return the registered tool names in insertion order."""
        return tuple(self._tools)

    def tool[A: BaseModel, R: BaseModel](
        self,
        *,
        args: type[A],
        result: type[R],
        layer: str = "action",
        name: str | None = None,
        rails: Sequence[str] = (),
    ) -> Callable[
        [Callable[[A, "ToolContext"], Result[R]]],
        Callable[[A, "ToolContext"], Result[R]],
    ]:
        """Decorator registering a tool body while keeping it directly callable."""

        def _wrap(
            fn: Callable[[A, "ToolContext"], Result[R]],
        ) -> Callable[[A, "ToolContext"], Result[R]]:
            self.register(
                ToolSpec(
                    name=name or fn.__name__,
                    layer=layer,
                    args_model=args,
                    result_model=result,
                    fn=fn,
                    rails=tuple(rails),
                ),
            )
            return fn

        return _wrap


_DEFAULT_REGISTRY = Registry()


def default_registry() -> Registry:
    """Return the process-global default registry backing bare ``@tool``."""
    return _DEFAULT_REGISTRY


def tool[A: BaseModel, R: BaseModel](
    *,
    args: type[A],
    result: type[R],
    layer: str = "action",
    name: str | None = None,
    rails: Sequence[str] = (),
) -> Callable[
    [Callable[[A, "ToolContext"], Result[R]]],
    Callable[[A, "ToolContext"], Result[R]],
]:
    """Register a tool in the default registry. See :meth:`Registry.tool`."""
    return _DEFAULT_REGISTRY.tool(
        args=args, result=result, layer=layer, name=name, rails=rails
    )


__all__ = ["Registry", "default_registry", "tool"]
