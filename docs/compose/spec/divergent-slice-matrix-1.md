---
feature: divergent-slice-matrix-1
status: in-progress
updated: 2026-09-08
branch: compose/divergent-slice-matrix-1
commits: 5389600..HEAD
---

# Divergent Slice Matrix 1

## Report

## [S1] Problem
CI is red on all 9 legs and no single machine can green it: `matrix.build_rows()` probes live stores for fixture-less CLIs and bakes the result into committed `support-matrix.json`/README tables. Committed state is a mix no machine reproduces — `qoder-ide: unverified` matches only store-less machines, `qwenwork-app: empty` only machines with that empty store. This contradicts `evidence.py`'s own contract ("never from a live store") and blocks all four open PRs.

## [S2] Design
Fixture-only committed truth, live overlay at the edges: `build_rows()` stops probing live stores (its derivation becomes a pure function of fixtures + reader registry); new `with_live_overlay()` applies the verified-empty verdict for fixture-less CLIs and is called ONLY by the live `handoff matrix` command. `evidence --check/--write`, conformance-adjacent tests, and unit tests all consume fixture-only rows. Committed artifacts regenerate once (qwenwork-app returns to `unverified`). No status semantics change; `empty` remains a live-only verdict.

## [S3] Out of Scope
Changing status derivation rules, touching parsers/fixtures/conformance baselines, README prose outside the generated blocks, and merging any branch.

## Tasks
- [ ] T1: Fixture-only rows + live overlay — acceptance: `build_rows` contains no live call; `with_live_overlay` used only by `_cmd_matrix`; committed artifacts regenerated (covers: S2)
- [ ] T2: Determinism regression test — acceptance: new test compares `build_rows` under real vs empty `AGENTHANDOFF_HOME`/`APPDATA` and asserts identical rows (fails pre-fix, passes post-fix) (covers: S2; depends: T1)
- [ ] T3: Dual-machine verification — acceptance: full `pytest`, `evidence --check`, `conformance --check` green under BOTH real home and empty home; `ruff` on touched files clean (covers: S2; depends: T1, T2)
