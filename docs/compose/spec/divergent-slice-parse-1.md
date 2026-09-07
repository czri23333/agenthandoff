---
feature: divergent-slice-parse-1
status: in-progress
updated: 2026-09-07
branch: compose/divergent-slice-parse-1
commits: 5389600..HEAD
---

# Divergent Slice Parse 1

## Report

## [S1] Problem
Divergent sweep (§1 parsing + §3 evidence) still has three honest gaps: file-only supplements grow `files_touched` but `supplement_files` counting misses the exact-match `task_files:` note, so drift reports stay confusing; precise per-session supplements (`telemetry_anchors`, `_task_execution_files`) lack regression cover; `qwenwork-app` empty plus confirmed non-sessions need an explicit honest verdict instead of re-investigation.

## [S2] Design
Transcript stays the only dialogue source. `qodersec` global traces, CLI `ai-stats` telemetry, and exact-match task execution files merge as file-only supplements into `files_touched` with `notes` counts, never into messages. Fixture trees never merge supplements so evidence measures the transcript alone. Supplement counting sums every file-only note prefix (`qodersec_anchors:`, `aistats_files:`, `task_files:`). Missing billing stays missing: no fabrication, empty stores keep the verified-empty label.

## [S3] Out of Scope
Cockpit rendering and interaction (§2), engineering hygiene (§4: bundle size, polling), cloud/RPC billing, credential decryption, PyPI packaging, and any new CLI parser for confirmed non-sessions (`chatEditingSessions`, `cache/experts`, intl `.qoder` browser-connector only).

## Tasks
- [ ] T1: Count all file-only supplements — acceptance: `fixtures.measure` sums `qodersec_anchors:`, `aistats_files:`, `task_files:` into `supplement_files`; `uv run pytest tests/test_fixtures.py -q` passes (covers: S2)
- [ ] T2: Regression for precise supplements — acceptance: new tests build temp home/fixture trees proving `telemetry_anchors(session_id)` only attributes matching sessionId and `_task_execution_files` exact-matches task id without touching messages; `uv run pytest tests/test_parsers.py tests/test_fixtures.py -q` passes (covers: S2; depends: T1)
- [ ] T3: Empty/non-session verdict — acceptance: `qwenwork-app` empty stays verified-empty in matrix, confirmed non-sessions produce no parser and no regression; `uv run pytest tests/test_parsers.py -q` plus `uv run python -m agent_handoff.evidence --check` pass (covers: S2)
- [ ] T4: Evidence refresh — acceptance: `uv run pytest tests/ -q`, `uv run python -m agent_handoff.conformance --check`, `uv run python -m agent_handoff.evidence --check` all green; baselines only rewritten if a measured supplement count intentionally moved (covers: S2; depends: T1, T2, T3)
