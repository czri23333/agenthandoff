---
feature: divergent-slice-usability-1
status: delivered
updated: 2026-09-08
branch: compose/divergent-slice-usability-1
commits: 5389600..6fd06c0
---

# Divergent Slice Usability 1

## Report

**What was built** — Anticipated-typo CLI errors: unknown `--cli` suggests `difflib` closest matches from **all** known ids (not just local stores) plus `handoff doctor`; dead session ids point at `handoff list -n 5` / `handoff search --body` instead of a bare 20-id list. Exit codes and valid-input bytes unchanged, stdlib only. README install path no longer promises PyPI: verified `pip install git+https://…` (via `pip download --no-deps`, "Successfully downloaded") in both languages.

**Verification** — `test_console.py` 7/7 (3 new); full `pytest` 225 + 1 PRE-EXISTING FAIL (`test_readme_and_matrix_json_are_current`, stale `qoder-ide` row, byte-identical on clean main — same root failure makes `evidence --check` red on main too, unrelated to this diff which touches no tables); ruff on touched files: only PRE-EXISTING I001. Independent review found one genuine critical (list-path suggested from machine-local stores — fixed, empty-machine test added, delta re-reviewed clean).

**Journey log** — Fresh worktrees need `uv sync --extra` before `uv run pytest`, else the system pytest shadows with a stale installed package (30 min rabbit hole; symptom: tests run old code despite correct `__file__`). Suggestion lists must draw from universal ids, never machine-local availability — a newcomer on an empty machine is exactly who needs them. PyPI publish stays with the maintainer (credentials).

## [S1] Problem
A newcomer fails fast and blind: `--cli qoder` answers only "has no available store" with no candidates; `capture <bad-id>` lists 20 CLI ids with no next step; the README's `pip install agenthandoff[zstd]` fails outright (never published on PyPI) with no working alternative stated. Every message assumes the reader already knows the tool.

## [S2] Design
Anticipate the typo, then point at the next command. Unknown `--cli` values get stdlib-`difflib` closest matches plus `handoff doctor`; unknown sessions get `handoff list -n 5` / `handoff search` pointers (prefix matching already exists in `resolve_session`). Messages stay single-line `error:` on stderr, exit codes unchanged. Install path: README states PyPI-pending honestly and gives a verified `pip install git+https://…` command (verified via `pip download --no-deps`, not just written). No behavior change for valid inputs; no new dependencies.

## [S3] Out of Scope
Publishing to PyPI (needs the maintainer's credentials), `handoff ui` missing-extra path (already clear), empty-machine flows beyond message text, and any change to valid-input output bytes.

## Tasks
- [x] T1: CLI error hints — acceptance: `list --cli qoder` suggests qoderwork* + doctor; unknown cli in resolve suggests matches; unknown session prints list/search next steps; new tests in tests/test_console.py assert stderr text (covers: S2)
- [x] T2: Install honesty — acceptance: README install section states PyPI-pending with a `pip download git+https://… --no-deps` verified command; `evidence --check` still green (covers: S2; depends: T1)
- [x] T3: Regression — acceptance: `uv run pytest tests/ -q` and `ruff check` on touched files pass (covers: S2; depends: T1, T2)
