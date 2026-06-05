## Summary

What does this change and why?

## Changes

-

## Checklist

- [ ] `pytest` passes
- [ ] `ruff check src tests examples` is clean
- [ ] Import firewall is green (`python -c "from agentgov.firewall import enforce; enforce()"`)
- [ ] New behavior has tests (deterministic — `FixedClock` / `SeededRng`)
- [ ] Tool bodies still return mutations and never mutate state, write the log, or bypass a rail
- [ ] README / examples updated if developer-facing behavior changed
