# Contributing

Thanks for considering a contribution. The project is small on purpose; these
rules keep it reviewable.

## Ground rules

1. **Determinism.** No LLM calls, no network, no randomness in library code.
   Same store state must render byte-identical output.
2. **Read-only.** Library code never writes into a CLI's session store.
   Output goes only where the caller points.
3. **Zero-dependency core.** Stdlib only. Optional codecs (e.g. `zstandard`)
   ship as extras and must degrade gracefully (`doctor` reports, never crashes).
4. **Tolerant parsers.** Skip unknown line types and malformed rows; never
   raise on unexpected upstream fields. Private formats drift — assume it.
5. **Synthetic fixtures only.** Never commit real session transcripts, yours
   or anyone else's.

## Adding a CLI parser

1. `src/agent_handoff/parsers/<cli>.py` — implement `list_sessions()` and
   `load()`, return `RawSession`.
2. Register it in `parsers/__init__.py` (`all_parsers` / `available_parsers`).
3. Add a store probe in `locations.py` (and the WSL mapping if relevant).
4. Add synthetic fixtures + tests: at minimum one happy path and one
   corrupted-line case.
5. Update the support matrix in both READMEs and `docs/architecture.md`.

## Cockpit frontend

The cockpit (FastAPI + React) ships its built UI inside the package at
`src/agent_handoff/server/static/`, which is **tracked on purpose**: a
clean clone must `pip install` and serve the UI without node. After
changing `web/src`:

```bash
cd web && npm ci && npm run build   # vite emits into ../src/agent_handoff/server/static
git add -A src/agent_handoff/server/static   # commit the rebuilt bundle in the same PR
```

`handoff ui --open` serves it at `http://127.0.0.1:8620` (loopback only).
During development, `npm run dev` proxies `/api` to that port.

## Before you push

One command runs the gates CI runs, in the same order:

```bash
python scripts/ci_local.py                  # pytest, ruff, tokens, evidence, conformance, CLI smoke
python scripts/ci_local.py --with-frontend  # ... plus npx tsc -b and npm run build
```

A commit in this repository once went red on all nine CI jobs because `ruff check .`
was run *before* the last test edit and not after: the gates are a set, not a menu,
and running four of them is easy to mistake for running all of them. The script
stops at the first failure and names the step.

`--with-frontend` is opt-in because CI does not build the UI (the bundle is
committed, so a clean clone can `pip install` and serve it) — which is exactly why
the rebuild has to be deliberate whenever `web/` changed, and why the rebuild
travels in the same commit as the source it came from.

## Style

- `ruff check .` must pass (E, F, I, UP, B, SIM; line length 100).
- Type hints on public functions; docstrings state *why* where it matters.
- Python >= 3.10.

## Commit / PR

- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- One logical change per PR; include test updates in the same PR.
