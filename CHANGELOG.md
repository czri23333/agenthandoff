# Changelog

All notable changes to this project will be documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
