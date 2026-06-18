# Contributing to agentgov

Thanks for your interest. agentgov is an open-core governance harness; the goal
of the OSS core is to be the small, auditable runtime that developers trust and
read. Contributions that keep it sharp, correct, and well-tested are very
welcome.

## Development setup

```bash
git clone <your-fork>
cd agentgov
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,viewer]"
```

## Before you open a PR

Run the full local gate — CI runs the same checks on Python 3.12 and 3.13:

```bash
ruff check src tests examples
pytest
```

- **Tests must pass and stay deterministic.** Use `FixedClock` and `SeededRng`
  in tests so replay assertions hold.
- **Keep the kernel framework-independent.** The core (`src/agentgov`) must not
  import `pydantic_ai` or any LLM SDK — the kernel governs decisions and knows
  nothing about the brain that drives it.
- **Add tests for new behavior.** Rails, the transaction boundary, replay,
  checkpoints, and finalize are the load-bearing parts — cover them.

## Design principles to respect

- **The model is not the authority; the harness is.** Tool bodies return
  *requested mutations*; they never mutate authoritative state, write the log,
  or bypass a rail.
- **The event log is the source of truth.** State is a fold over events; keep
  durable state JSON-serializable so it hashes and replays.
- **Rails are pure functions over state.** No I/O, no host calls, no tool
  dispatch inside a rail.
- **Keep the core dependency-light.** `pydantic` is the core dependency; the
  viewer's web stack stays behind the `[viewer]` extra.

## Commit and PR style

- Small, focused PRs with a clear description of *why*.
- Keep the public API surface (`agentgov.__all__`) intentional; flag additions.
- Update the README/examples when you change developer-facing behavior.

## Reporting bugs and proposing features

Open an issue using the templates. For security issues, see
[SECURITY.md](SECURITY.md) — please do not file a public issue.
