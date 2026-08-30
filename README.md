# agenthandoff

**Hand off any AI coding CLI session to the next one — deterministic, fully local, zero dependencies.**

![CI](https://github.com/czri23333/agenthandoff/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/pypi/pyversions/agenthandoff)
![License](https://img.shields.io/pypi/l/agenthandoff)

[README in Chinese / 中文说明](README.zh-CN.md)

Long agent sessions die the same way every time: the context window fills up,
and the next session starts from zero — unless you manually re-explain the
task, the decisions, the dead ends, and the file layout. `agenthandoff`
automates that handoff. It reads each CLI's **own local session storage**,
extracts the durable state, and emits:

1. a **Handoff Bundle** — a portable, human-readable markdown document
   (objective / done / open / user directives / file anchors / next steps),
2. a **continuation brief** — a budgeted, priority-ordered prompt you paste
   into the next session of *any* CLI.

No API keys. No network. No LLM in the loop. Same input ⇒ byte-identical
output, so bundles are diffable and trustworthy.

## Supported CLIs

Evidence levels: **read** = parsed a real store on the maintainer's machine
(2026-08-31, one Windows host); **never verified** = code exists, nobody has fed
it data; **proven** = a sanitized fixture in this repo is parsed in CI (nobody is
at this level yet — see [docs/limitations.md](docs/limitations.md)). Run
`handoff doctor` to see what is real on *your* machine; it, not this table, is the
source of truth.

| CLI | Storage read | Evidence |
|---|---|---|
| ZCode | SQLite (`~/.zcode/cli/db/db.sqlite`) | ✅ read — 453 sessions |
| Qoder CN IDE | JSONL (`~/.qoder-cn/projects/…`) | ✅ read — 118 files |
| CodeBuddy | JSONL (`~/.codebuddy/projects/…`) | ✅ read — 32 files |
| Qoderwork (+CN, dual-account) | JSONL (`~/.qoderwork[cn]/projects/…`) | ✅ read — 13 files, 3 account configs |
| Qwen Work CN | JSONL (`~/.qwenworkcn/projects/…`) | ✅ read — 1 file |
| dsh (DeepSeekHarness) | zstd-JSONL (`~/.dsh/sessions/…`) | ✅ read — 46 rolls, incl. a WSL-side store |
| Kimi CLI | `state.json` + `wire.jsonl` | 🧪 read once — experimental |
| Codex CLI | `~/.codex/sessions` | ❌ detected, not readable — rollout layout moved |
| Claude Code | JSONL (`~/.claude/projects/…`) | ⚠️ never verified (no store seen, no fixture) |
| CodeBuddy CN | JSONL (`~/.codebuddy-cn/projects/…`) | ⚠️ never verified |
| opencode | `~/.local/share/opencode/storage` | 🔜 roadmap |
| Qoder IDE (intl.) | Electron leveldb, no session files | 🔜 roadmap |
| Trae / IDE-family (SQLite state) | per-vendor app data | 🔜 roadmap, read-only only |

Multi-account harnesses are reported as evidence: `handoff doctor` shows
`N account config(s)` (one encrypted model catalog per login); per-session
attribution stays with the user via `capture --note account:work`, because
no store records which account produced a session.

Sessions stored inside **WSL** distros are discovered and read from the
Windows side automatically (`handoff doctor` shows them tagged `[wsl]`).

## Quick start

```bash
pip install "agenthandoff[zstd]"     # or: pipx install / uv tool install
# (unreleased on PyPI — from source: git clone + pip install -e ".[dev,zstd]")
handoff doctor                       # which CLI stores exist and are readable?
handoff list                         # recent sessions across every CLI
handoff list --cwd myproject -n 5
handoff capture                      # latest session → bundle to stdout
handoff capture sess_c66487e -o handoff.md
handoff resume handoff.md            # → continuation brief (paste into next session)
handoff resume handoff.md --lang zh --max-chars 8000
handoff search "cockpit"               # full-text search across every session
handoff ui --open                   # cockpit WebUI on 127.0.0.1:8620 (needs [server])
handoff publish handoff.md          # drop a bundle into the exchange dir
handoff inbox                       # bundles other agents left for you
handoff threads                     # one job spread across many CLI sessions
handoff backup                      # snapshot every session store (sources stay read-only)
```

Everything is read-only. `agenthandoff` never writes into a CLI's store.

## What is *not* working

The honest inventory lives in
[docs/limitations.md](docs/limitations.md): which support claims rest on real
data, which are unverified, and the 15 known gaps — including the one that
matters most, that a brief assembled after a quota death currently drops recent
context first. If a sentence below sounds like marketing, go read that file.

## Why not just ask the agent to write a handoff file?

Most existing handoff tools are a *skill/prompt* that tells the model to
"write a HANDOFF.md before finishing". That fails precisely when you need it:
crashed sessions, context-window death, and non-compliant models. It is also
non-deterministic — you cannot diff two handoffs or trust that "done" items
were actually done.

`agenthandoff` inverts the design: the CLI's own event log is the source of
truth. Todo state comes from the todo table, file anchors from real tool
calls, user directives from the user's own turns. See
[docs/research.md](docs/research.md) for the competitive survey behind this
positioning.

## The bundle format

`spec/handoff-bundle-spec.md` defines the markdown bundle (v0.1) with a
matching JSON Schema (`schema/handoff-bundle-v0.1.schema.json`). Any tool —
including other agent CLIs — can emit or consume it. The format is
deliberately boring: YAML metadata, plain lists, one objective, numbered
next steps.

`spec/resume-prompt-spec.md` defines how a bundle is compiled into a
continuation brief: section priorities (`rules` and `facts` outrank
`digest`), whole-section budget dropping, and an explicit anti-redo header.

## Architecture

One pipeline, pluggable readers:

```
discover → parse (per CLI) → RawSession → summarize → bundle (md/JSON) → brief
```

Adding a CLI = one parser file implementing `list_sessions()` + `load()`.
Details in [docs/architecture.md](docs/architecture.md).

## Privacy

- Session content never leaves your machine; the tool makes zero network calls.
- No session data of any kind is committed — the repo ships no fixtures yet, and
  when it does they will be structure-preserving, content-replaced files.
- Nothing leaves your machine: the tool makes zero network calls, and the cockpit
  binds to 127.0.0.1 only.
- Bundles are written only where you point `--out`.

## Development

```bash
git clone https://github.com/czri23333/agenthandoff
cd agenthandoff
pip install -e ".[dev]"
pytest
ruff check .
```

Design docs: [architecture](docs/architecture.md) ·
[competitive research](docs/research.md) ·
[bundle spec](spec/handoff-bundle-spec.md) ·
[resume-prompt spec](spec/resume-prompt-spec.md)

## License

[MIT](LICENSE)
