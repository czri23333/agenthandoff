---
feature: divergent-slice-render-1
status: delivered
updated: 2026-09-07
branch: compose/divergent-slice-render-1
commits: 5389600..ee2b2a8
---

# Divergent Slice Render 1

## Report

**What was built** — Official-aligned Dashboard: generic grouping switch (project/activity/flat, derived from domain config + `updated_at` for every CLI), canonical sort (`updated_at` DESC, `session_id` ASC tiebreak), 60-codepoint display titles with full-text hover, and an archived-or-deleted badge for task transcripts the readable snapshot no longer lists. Plus a blocking boot fix found by measurement: pinned web MIME types so the cockpit renders on machines whose registry maps `.js` to `text/plain`. Shared 50-row paging extracted to `PagedRows` so no view mounts the whole store.

**Verification** — `pytest` 226 PASS; `conformance` 12 ok; `evidence` 21 rows match; `tsc` exit 0; ruff deltas pre-existing only. Headless-chromium vs served cockpit: FCP 292 ms, 186 rows / 2740 nodes; domain/activity/flat conserve 299 sessions, flat caps at 50 mounted rows, zero page errors; live probe: 9 task sessions carry `archived:true`. Independent review + delta re-review: all acceptance met, no criticals.

**Journey log** — Baseline measurement rendered blank (0 nodes) and exposed the MIME boot failure; without measuring first this ships-broken-on-some-machines bug stays hidden. `uv run` re-syncs undeclared packages away: measurement-only `playwright` must be used via direct venv python, never `uv run`. Readable-but-empty snapshot flagging transcripts is literally true ("no longer listed"), not overclaim — the honesty check that shaped the badge. `index.html` line-ending churn in rebuilds is cosmetic; leave it. Postscript: `ee2b2a8` (reviewer-suggested astral gate one-liner + rebuild) landed after the delta re-review; covered by `tsc` + fresh build + green browser group-check on the shipped bundle, not by a third subagent pass.

## [S1] Problem
Dashboard rendering is not provably aligned with the official QoderCN IDE: chat-list ordering/grouping/title rules and task-panel presentation are reimplemented from observed transcripts, never reverse-checked against the product itself. Separately, first-screen list cost is asserted (214KB snapshot) but unmeasured, so virtualization scope is a guess.

## [T1-RuleTable] Official QoderCN presentation rules (asar evidence, 2026-09-07)
Source: `D:/Qoder CN/resources/app.asar`, read-only single-file extraction. All paths are in-asar bundle paths.

| # | Rule | Official behavior | Evidence | Cockpit verdict |
|---|---|---|---|---|
| 1 | Chat-list order | `ORDER BY updated_at DESC`, tiebreak `session_id ASC`; no date grouping in store | `out/main/index.js:L1304-1310`; renderer `@18208475` | ALIGNED: tiebreak added to render sort |
| 2 | Sidebar view | Default `{grouping:"workspace",sorting:"manual"}`; visible = standard, non-archived, non-deleted, non-fork, productMode-matched; manual sort = `placement.order` asc (missing first), then updatedAt desc, then sessionId; groups = pinned + workspace (paged 10 + expander) or activity (today/yesterday/7d/older) or flat | renderer `index-CJIZlk4N.js` `@17943328/17944461/17947335/4872015`; `out/main/index.js:L1481-1484` | ALIGNED (generic subset): domain/activity/flat switch; pinned/manual order deferred (needs placement store) |
| 3 | Title priority | `custom > ai/provisional/fallback > legacy`; rename→custom wins permanently; store truncation 60 code points + `"..."`, display 60 chars + `"…"` | `out/main/index.js:L1280/L1134/L1491/L1500/L1397` | ALIGNED (display): 60-codepoint clip + full hover; store titles untouched for search/bundle fidelity |
| 4 | Fragment merge | No `add_user_message` in bundles/SDK (disk-only); unity = projection folds events into turns by `turnId`, in-place update by message id; adjacent equal assistant texts deduped; `[Request interrupted by user…]` user rows dropped | projection `qe()/He()/Jt()`, `N()/U()`, `Uz()`, `Rz()` | PARTIAL: interrupt-row drop locked by test; turnId-vs-60min-window merge stays an approximation |
| 5 | Task panel | No quest code in asar (agent-runtime-owned); `executionSessionId` = scheduled-automation surface: unknown id → `automationTasks.sessionArchivedOrDeleted` tag + `viewConversation` button | renderer `@18151374-18155838` (6 sites) | ALIGNED: `snapshot_archived` note → `archived:true` → 🗄 badge (readable snapshot only) |
| 6 | Sub-agent visibility | `automationExecution` excluded from default list; subagent transcripts served per-task via worker matched by `parent_tool_use_id`, never chat-list rows | `out/main/index.js:L1304/L1338`; `chatSessionSubagentTranscriptWorker-RTlIOOFe.js:1` | OPEN: cockpit shows automation badge inline instead of hiding (behavior change, needs decision) |
| 7 | Per-message billing | None in message area (confirms billing-coverage §5-16); usage = header waterlevel hover | renderer `@17698884/@17702769`; projection `Et()` | MATCH; cockpit `dur_ms` chips exceed official |

## [S2] Design
Official-first, generic-always (ADR-009): reverse `D:/Qoder CN/resources/app.asar` (read-only; global `asar@3.2.0` available) for session-presentation rules only — chat-list order/group/title source, quest-task panel mapping, fragment/merge behavior. Land findings as a rule table in this document, then align cockpit rendering to the table with zero scene-specific hardcode (config or data-shape derivation only). Virtualize only what measurement justifies: playwright first-screen timings before/after; per-domain paging (50 + expander) stays unless numbers demand windowing. No new runtime deps unless measurement forces it.

## [S3] Out of Scope
Other vendors' surfaces (Workbuddy/CodeBuddy/IDE-international follow as later slices), usage/billing model reverse (already exhausted in docs/billing-coverage.md), any store-format parsing change, decrypting opaque blobs, and touching the asar or the IDE install itself.

## Tasks
- [x] T1: Official rule table — acceptance: asar-derived chat-list/task-panel/fragment rules recorded in this spec with file:line evidence, each mapped to a cockpit gap or an explicit match (covers: S2)
- [x] T2: Cockpit alignment — acceptance: Dashboard gains a generic grouping switch (workspace/activity/flat, ADR-009: derived from cwd/updated_at for every CLI, no vendor hardcode) plus small wins (session_id tiebreak, 60-char title rule, archived badge, interrupt-row check); `npx tsc -b && npm run build` clean, byte-identical dist committed (covers: S2; depends: T1)
- [x] T3: First-screen cost — acceptance: playwright timings for Dashboard first paint + scroll before/after; virtualization (or kept paging) justified by numbers in Report (covers: S2; depends: T2)
- [x] T4: Regression — acceptance: `uv run pytest tests/ -q`, `conformance --check`, `evidence --check` green; no renderer output-byte drift except intended alignment (covers: S2; depends: T2, T3)
