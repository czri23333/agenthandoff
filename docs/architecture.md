# Architecture

## Pipeline

```
                 ┌──────────────────────── discovery ────────────────────────┐
                 │  locations.py: probe each CLI's local store (read-only)   │
                 │  + WSL bridge: \\wsl.localhost\<distro>\home\<u>\.<cli>   │
                 └───────────────────────────┬───────────────────────────────┘
                                             ▼
┌────────────── parse ──────────────┐   ┌──────────── normalize ─────────────┐
│ parsers/zcode.py        (SQLite)  │   │  RawSession:                       │
│ parsers/jsonl_family.py (JSONL ×4)│ ─▶│   meta · messages · todos          │
│ parsers/dsh.py          (zstd)    │   │   files_touched · tool_counts      │
│ parsers/kimi.py         (exp.)    │   └─────────────────┬──────────────────┘
└───────────────────────────────────┘                     ▼
                                    ┌──────────── summarize ─────────────┐
                                    │ deterministic heuristics, no LLM:  │
                                    │ objective · todo-state split ·     │
                                    │ user directives · file anchors     │
                                    └─────────────────┬──────────────────┘
                                                      ▼
                                    ┌────── render ──────┐   ┌──── resume ────┐
                                    │ bundle markdown    │──▶│ budgeted       │
                                    │ bundle JSON        │   │ continuation   │
                                    │ (spec v0.1+schema) │   │ brief (spec)   │
                                    └────────────────────┘   └────────────────┘
```

## Modules

| Module | Responsibility |
|---|---|
| `locations.py` | Store discovery per CLI; Windows + WSL bridge probing; `munge_cwd` for project-dir naming |
| `parsers/base.py` | `Parser` ABC (`list_sessions`, `load`), JSONL reading, text/tool-block splitting, path extraction, noise filtering |
| `parsers/zcode.py` | ZCode SQLite store, opened with `mode=ro` URI so a live instance is never disturbed |
| `parsers/jsonl_family.py` | One configurable reader for the Claude-Code-style JSONL dialect; subclasses: Claude Code, CodeBuddy(+CN), Qoderwork, Qwen Work CN |
| `parsers/dsh.py` | dsh `session.jsonl.zstd` via the optional `zstandard` codec (see below) |
| `parsers/kimi.py` | Kimi CLI `state.json` + `wire.jsonl` (experimental — protocol still being mapped) |
| `summarize.py` | `RawSession → HandoffBundle` deterministic heuristics |
| `render.py` | Bundle → markdown / JSON per `spec/handoff-bundle-spec.md` |
| `resume.py` | Bundle → budgeted continuation brief per `spec/resume-prompt-spec.md` |
| `cli.py` | argparse surface: `doctor` / `list` / `capture` / `resume` |

## Parser contract

```python
class Parser(ABC):
    cli: str
    def list_sessions(self) -> list[SessionMeta]: ...
    def load(self, session_id: str) -> RawSession | None: ...
```

A new CLI = one file implementing these two methods + one registry entry.
Everything downstream (summarize/render/resume) is parser-agnostic. Parsers
must be tolerant: skip unknown line types, skip malformed rows, never raise on
unexpected upstream fields — private formats drift.

## Optional codec: zstd (dsh)

dsh compresses sessions (`session.jsonl.zstd`). To keep the core
zero-dependency, `zstandard` is an optional extra:

```
pip install "agenthandoff[zstd]"
```

`parsers/dsh.py` degrades gracefully: without the extra it reports the
missing codec in `doctor` instead of crashing.

## WSL bridge

Chinese/overseas CLIs are increasingly run inside WSL. From Windows,
`agenthandoff` probes each distro's home through two redundant paths:

1. `wsl.exe -d <distro> -- test -d /home/<user>/.<cli>` (authoritative)
2. `\\wsl.localhost\<distro>\home\<user>\.<cli>` (fast UNC reads)

Distro/user enumeration is cached per process. WSL-backed stores are listed
in `doctor` with a `[wsl]` tag and read through the same parsers — a
`\\wsl.localhost` SQLite path is opened with the same read-only URI mode.
If WSL is not running, discovery marks the distro as unreachable instead of
failing.

## Design principles

1. **Read-only.** We never write into any CLI's store. SQLite is opened
   `mode=ro`; JSONL is read with `errors="replace"`.
2. **Deterministic.** Same store state ⇒ byte-identical bundle. No LLM, no
   network, no randomness.
3. **Privacy.** Session content stays on the machine. The repo's test
   fixtures are synthetic; no real session transcript is ever committed.
4. **Honest degradation.** Every feature reports what it could not do
   (`doctor`), rather than silently producing an empty bundle.

## Support matrix (verified against live local stores, 2026-08-30)

| CLI | Storage | Status |
|---|---|---|
| ZCode | `~/.zcode/cli/db/db.sqlite` (SQLite) | stable |
| Claude Code | `~/.claude/projects/<munged>/*.jsonl` | stable (fixtures) |
| CodeBuddy / CodeBuddy CN | `~/.codebuddy[cn]/projects/<munged>/*.jsonl` | stable |
| Qoderwork | `~/.qoderwork/projects/<munged>/*.jsonl` | stable |
| Qwen Work CN | `~/.qwenworkcn/projects/<munged>/*.jsonl` | stable |
| dsh | `~/.dsh/sessions/<munged>/<uuid>/session.jsonl.zstd` | stable (`[zstd]` extra) |
| Kimi CLI | `~/.kimi-code/sessions/wd_*/session_*/{state.json,wire.jsonl}` | experimental |
| Codex CLI | `~/.codex/sessions/*.jsonl` | roadmap |
| opencode | `~/.local/share/opencode/storage` | roadmap |
