# Changelog

All notable changes to this project will be documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Cockpit WebUI (`handoff ui`): dashboard, session detail, inbox, threads and
  doctor views — bilingual (zh default), hash routing, keyboard view switching,
  usage/latency accounting, and a verified-launcher registry.
- Cross-session exchange: `handoff publish | inbox | claim` with sidecars.
- `handoff threads` — cluster sessions across CLIs into one task thread.
- `handoff search` + `GET /api/search` — ranked full-text search over titles,
  file anchors and message bodies of every discovered session.
- `handoff backup` + `GET /api/backup` — timestamped snapshot of all stores.
- Verbatim raw archive: `handoff capture --full --raw` embeds the session's
  ORIGINAL storage byte-faithfully (tool calls, system rows, vendor fields no
  parser reads), `handoff resume --dump-raw` extracts it hash-verified, and
  `GET /api/sessions/{cli}/{sid}/raw` serves the same files as a zip from the
  cockpit. SQLite stores archive record-level (every column of every row).
- Portable single-exe spec for the cockpit (`agenthandoff-ui.spec`,
  `docs/portable-single-exe.md`).

### Fixed

- Clean-clone install: the wheel no longer force-includes the gitignored
  `web/dist`, which made `pip install` fail in every CI matrix job. The built
  cockpit is tracked at `src/agent_handoff/server/static`, and `npm run build`
  emits straight into that directory.
- Server import crash from leftover WIP type-alias lines in `server/app.py`
  (took the whole cockpit, including `/api/heartbeat`, down with a NameError).

## [0.1.0] - 2026-08-30

### Added

- Core pipeline: discover → parse → `RawSession` → deterministic summarize →
  Handoff Bundle (markdown + JSON) → continuation brief.
- Parsers: ZCode (SQLite, read-only URI), Claude Code / CodeBuddy / CodeBuddy CN /
  Qoderwork / Qwen Work CN (Claude-Code-style JSONL family), dsh (zstd-JSONL via
  optional `zstandard` extra), Kimi CLI (experimental).
- WSL bridge: session stores inside WSL distros discovered via `wsl.exe` and read
  through `\\wsl.localhost` UNC paths.
- CLI: `handoff doctor | list | capture | resume` with `--json`, `--lang en|zh`,
  `--max-chars` budget.
- Open formats: Handoff Bundle spec v0.1 + JSON Schema; resume-prompt spec with
  section-priority budget policy.
- Deterministic heuristics: todo-state split, user-directive extraction,
  file-anchor ranking from tool calls, last-assistant context notes.
