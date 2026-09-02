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

<!-- MATRIX BEGIN: generated, do not edit -->
This table is derived from the sanitized real-format fixtures under `tests/fixtures/sanitized/` - not typed by hand (the derivation date lives in `config/support-matrix.json`). 8 rows carry fixture evidence you can reproduce after a clone with `pip install -e . && python -m agent_handoff.evidence --check`; the other labels name evidence gaps, not feature promises.

| CLI | store | reader | fixtures | proven from fixtures | fingerprint | status |
|---|---|---|---|---|---|---|
| `zcode` | SQLite (read-only URI) | ✓ | 2 | 3 ses / 46 msg | ✓ | ✅ stable (fixture-proven) |
| `claude` | JSONL dir | ✓ | — | — | — | ⚠️ unverified (no fixture) |
| `codebuddy` | JSONL dir | ✓ | 25 | 23 ses / 110 msg | ✓ | ✅ stable (fixture-proven) |
| `codebuddy-cn` | JSONL dir | ✓ | — | — | — | ⚠️ unverified (no fixture) |
| `qoderwork` | JSONL dir | ✓ | 4 | 2 ses / 3 msg | ✓ | ✅ stable (fixture-proven) |
| `qoderwork-cn` | JSONL dir | ✓ | 25 | 2 ses / 34 msg | ✓ | ✅ stable (fixture-proven) |
| `qodercn-ide` | JSONL dir | ✓ | 25 | 3 ses / 31 msg | ✓ | ✅ stable (fixture-proven) |
| `qoder-ide` | unknown | ✓ | — | — | — | ⚠️ unverified (no fixture) |
| `qwenwork` | JSONL dir | ✓ | 3 | 1 ses / 2 msg | ✓ | ✅ stable (fixture-proven) |
| `workbuddy` | unknown | ✓ | — | — | — | ⚠️ unverified (no fixture) |
| `dsh` | zstd JSONL dir | ✓ | 4 | 3 ses / 7 msg | ✓ | ✅ stable (fixture-proven) |
| `kimi` | state.json + wire.jsonl | ✓ | 4 | — | ✓ | ⬜ shape only (source store held no dialogue) |
| `codex` | JSONL rollouts | ✓ | 21 | 19 ses / 426 msg | ✓ | ✅ stable (fixture-proven) |
| `opencode` | unknown | ✓ | — | — | — | ⚠️ unverified (no fixture) |
| `qoderwake` | unknown | ✓ | — | — | — | ⚠️ unverified (no fixture) |
| `qoderwake-cn` | unknown | ✓ | — | — | — | ⚠️ unverified (no fixture) |
| `trae` | IDE SQLite; read-only only, never written | — | — | — | — | 🔜 roadmap |

Legend: stable = a fixture parses to real dialogue; shape only = the source store held no conversation to sample; unverified = reader exists, no fixture yet; fixture fails = the fixture does not parse; roadmap = no reader; unavailable = needs an optional codec here.
<!-- MATRIX END -->


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
[docs/limitations.md](docs/limitations.md): which support claims rest on parsed
fixtures, which are unverified, and the known gaps — including the two that bite
hardest, that a fixture freezes a format at the moment it was sampled and that the
cockpit has never been exercised under concurrent load. If a sentence below sounds
like marketing, go read that file.

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
pip install -e ".[dev,zstd,server]"
pytest                                   # library + every shipped fixture
ruff check .
handoff matrix                           # the support table, derived from fixtures
python -m agent_handoff.evidence --check      # README/JSON vs the fixtures
python -m agent_handoff.conformance --check   # format fingerprints vs the baseline
```

Regenerating the evidence after a vendor update (maintainer's machine, needs the
real stores): `python scripts/sanitize_fixtures.py` rebuilds the sanitized
fixtures and audits them for leaks, then `--write` refreshes the fingerprints and
the README tables. Commit all three together, or CI fails - deliberately.

## License

[MIT](LICENSE)
