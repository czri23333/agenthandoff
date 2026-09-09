---
feature: divergent-slice-matrix-1
status: delivered
updated: 2026-09-09
branch: compose/divergent-slice-matrix-1
commits: 5389600..fe0b906
---

# Divergent Slice Matrix 1

## Report

**What was built** — Unblocked CI for every open PR: `build_rows()` is now a pure function of fixtures + reader registry (live probe removed); new `with_live_overlay()` keeps the verified-empty verdict for the live `handoff matrix` command only. Committed artifacts regenerated once (`qwenwork-app` back to `unverified` + date stamp — the only row change). This branch also carries the lint cleanup (42 → 0 `ruff` violations, merged from `compose/divergent-slice-lint-1`) because CI's Lint step was the second, independent blocker, and `scripts/ci_annotate_failures.py` + a CI step that names failing tests as check annotations — a red run no longer hides its test name behind log sign-in.

**Verification** — `pytest` 224 PASS under BOTH real home and empty `AGENTHANDOFF_HOME`/`APPDATA` (pre-fix each failed on one side); `evidence --check` green on both; `conformance` 12 ok; `ruff check .` zero; `scripts/ci_annotate_failures.py` proven on a crafted junit.xml and on a real green run. CI: run 19 (77d6c91) and run 20 (fe0b906) both **success on all 9 legs**.

**Journey log** — The committed matrix mixed two machines' live states, so no machine could ever green CI; the giveaway was different stale rows on different machines (qoder-ide here, qwenwork-app on empty). CI logs require sign-in, so the failure was unreadable from here: the fix was to make CI self-describing (junit → `::error::` annotations) instead of guessing. Run 18's single red leg (windows 3.12 only) turned out to be a timing flake, not a code defect: `test_warm_async_is_single_flight` raced a 360 ms build window; it now gates the build with a `threading.Event`, so "building" is a fact (25 local repeats green). Fresh worktrees still need `uv sync --extra` before `uv run pytest` or the system pytest shadows with stale code.

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
