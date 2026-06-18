## Summary

What does this change and why?

## Changes

-

## Checklist

- [ ] `pytest` passes
- [ ] `ruff check src tests examples` is clean
- [ ] Kernel stays framework-independent (no `pydantic_ai` / LLM SDK import in `src/agentgov`)
- [ ] New behavior has tests (deterministic — `FixedClock` / `SeededRng`)
- [ ] Tool bodies still return mutations and never mutate state, write the log, or bypass a rail
- [ ] README / examples updated if developer-facing behavior changed
