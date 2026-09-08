---
feature: divergent-slice-usability-1
status: in-progress
updated: 2026-09-08
branch: compose/divergent-slice-usability-1
commits: 5389600..HEAD
---

# Divergent Slice Usability 1

## Report

## [S1] Problem
A newcomer fails fast and blind: `--cli qoder` answers only "has no available store" with no candidates; `capture <bad-id>` lists 20 CLI ids with no next step; the README's `pip install agenthandoff[zstd]` fails outright (never published on PyPI) with no working alternative stated. Every message assumes the reader already knows the tool.

## [S2] Design
Anticipate the typo, then point at the next command. Unknown `--cli` values get stdlib-`difflib` closest matches plus `handoff doctor`; unknown sessions get `handoff list -n 5` / `handoff search` pointers (prefix matching already exists in `resolve_session`). Messages stay single-line `error:` on stderr, exit codes unchanged. Install path: README states PyPI-pending honestly and gives a verified `pip install git+https://…` command (verified via `pip download --no-deps`, not just written). No behavior change for valid inputs; no new dependencies.

## [S3] Out of Scope
Publishing to PyPI (needs the maintainer's credentials), `handoff ui` missing-extra path (already clear), empty-machine flows beyond message text, and any change to valid-input output bytes.

## Tasks
- [ ] T1: CLI error hints — acceptance: `list --cli qoder` suggests qoderwork* + doctor; unknown cli in resolve suggests matches; unknown session prints list/search next steps; new tests in tests/test_console.py assert stderr text (covers: S2)
- [ ] T2: Install honesty — acceptance: README install section states PyPI-pending with a `pip download git+https://… --no-deps` verified command; `evidence --check` still green (covers: S2; depends: T1)
- [ ] T3: Regression — acceptance: `uv run pytest tests/ -q` and `ruff check` on touched files pass (covers: S2; depends: T1, T2)
