---
feature: divergent-slice-matrix-1
status: delivered
updated: 2026-09-08
branch: compose/divergent-slice-matrix-1
commits: 5389600..9bbaa68
---

# Divergent Slice Matrix 1

## Report

**What was built** — Unblocked CI for all four open PRs at the root: `build_rows()` is now a pure function of fixtures + reader registry (live probe removed); new `with_live_overlay()` keeps the verified-empty verdict for the live `handoff matrix` command only. Committed artifacts regenerated once (`qwenwork-app` back to `unverified` + date stamp — the only row change). `empty` semantics unchanged, still shown live.

**Verification** — Full `pytest` 224 PASS under BOTH real home and empty `AGENTHANDOFF_HOME`/`APPDATA` (pre-fix each failed on one side); `evidence --check` green on both; `conformance` 12 ok; `ruff` on touched files clean; live `handoff matrix` still shows both empty verdicts here. Independent review: spec/correctness/consistency PASS, no criticals.

**Journey log** — The committed matrix mixed two machines' live states, so no machine could ever green CI; the giveaway was different stale rows on different machines (qoder-ide here, qwenwork-app on empty). `evidence.py`'s own docstring already promised fixture-only — the fix aligns code with its contract. Fresh worktrees still need `uv sync --extra` before `uv run pytest` or the system pytest shadows with stale code.

## [S1] Problem
CI is red on all 9 legs and no single machine can green it: `matrix.build_rows()` probes live stores for fixture-less CLIs and bakes the result into committed `support-matrix.json`/README tables. Committed state is a mix no machine reproduces — `qoder-ide: unverified` matches only store-less machines, `qwenwork-app: empty` only machines with that empty store. This contradicts `evidence.py`'s own contract ("never from a live store") and blocks all four open PRs.

## [S2] Design
Fixture-only committed truth, live overlay at the edges: `build_rows()` stops probing live stores (its derivation becomes a pure function of fixtures + reader registry); new `with_live_overlay()` applies the verified-empty verdict for fixture-less CLIs and is called ONLY by the live `handoff matrix` command. `evidence --check/--write`, conformance-adjacent tests, and unit tests all consume fixture-only rows. Committed artifacts regenerate once (qwenwork-app returns to `unverified`). No status semantics change; `empty` remains a live-only verdict.

## [S3] Out of Scope
Changing status derivation rules, touching parsers/fixtures/conformance baselines, README prose outside the generated blocks, and merging any branch.

## Tasks
- [x] T1: Fixture-only rows + live overlay — acceptance: `build_rows` contains no live call; `with_live_overlay` used only by `_cmd_matrix`; committed artifacts regenerated (covers: S2)
- [x] T2: Determinism regression test — acceptance: new test compares `build_rows` under real vs empty `AGENTHANDOFF_HOME`/`APPDATA` and asserts identical rows (fails pre-fix, passes post-fix) (covers: S2; depends: T1)
- [x] T3: Dual-machine verification — acceptance: full `pytest`, `evidence --check`, `conformance --check` green under BOTH real home and empty home; `ruff` on touched files clean (covers: S2; depends: T1, T2)
