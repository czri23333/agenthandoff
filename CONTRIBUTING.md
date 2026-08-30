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

## Style

- `ruff check .` must pass (E, F, I, UP, B, SIM; line length 100).
- Type hints on public functions; docstrings state *why* where it matters.
- Python >= 3.10.

## Commit / PR

- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- One logical change per PR; include test updates in the same PR.
