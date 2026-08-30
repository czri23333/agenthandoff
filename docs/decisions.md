# Architecture Decision Records

Short-lived rationale kept next to the code it explains. Status: accepted
unless marked otherwise.

## ADR-001: Implementation language — Python 3.10+, stdlib-only core

Options considered: Python, Go, Rust, Node/TypeScript.

| Criterion | Python | Go | Rust | Node/TS |
|---|---|---|---|---|
| Iteration speed for parsers/heuristics (the bulk of the work) | ★★★ | ★★ | ★ | ★★ |
| Zero-install reach (`pipx`/`uv tool` single command) | ★★★ | ★★★ (binary) | ★★★ (binary) | ★★ (npx) |
| SQLite/JSONL/async-file ergonomics | ★★★ (stdlib) | ★★ | ★★ | ★★ |
| Contribution accessibility for agent-tool users | ★★★ | ★★ | ★ | ★★ |
| Startup latency / runtime footprint | ★ (~100 ms) | ★★★ | ★★★ | ★ |
| Determinism friendliness (hashable dataclasses, sorted output) | ★★ | ★★★ | ★★★ | ★★ |

**Decision**: Python. The workload is I/O-bound parsing with heavy
format-drift tolerance — iteration speed and stdlib `sqlite3`/`json`/`pathlib`
beat raw performance, which is irrelevant at session-store scale (MBs).
Single-binary distribution (Go/Rust) is attractive but premature; if a
future `watch` mode or huge-store indexing demands it, the parser contract
(`list_sessions`/`load` → `RawSession`) is portable to a Rust core with a
Python facade. Zero-dependency is enforced so the security review surface
stays at "the stdlib plus zstandard".

Rejected alternatives: Node (the JSONL family is trivially handled there,
but the maintainer/user base here is Python-first); LLM-mediated extraction
in any language (violates determinism, see ADR-004).

## ADR-002: Exchange mechanism — files are the API, git is the bus

Options considered: filesystem exchange dirs, long-running daemon with
socket bus, MCP server, database queue.

**Decision**: plain files in `<cwd>/.handoff/` or `~/.agenthandoff/`,
published/claimed via the CLI. Cross-machine and cross-agent sync is
delegated to git (commit the dir, push a branch) or any file sync. Claim
markers are sidecar JSON — data, not locks.

Rejected: a daemon (install/ops burden, one more thing to crash), MCP
(listed on the roadmap as a *consumer* integration — an agent CLI should be
able to read bundles via MCP later, but the storage must not require a
running server), a queue DB (same daemon problem, plus SQLite-over-network
is a known footgun).

## ADR-003: Account identity — evidence of accounts, not attribution

Superseded earlier (wrong) claim that "variant directories are the account
scope". Live verification on a real dual-account setup showed:

* Product variant directories (`.qoderwork`, `.qoderworkcn`) are separate
  *harness* installs, not accounts — a single install can switch between
  multiple accounts.
* Account count is visible as per-account model-config directories
  (`.models/<uuid>/`, one per login, contents encrypted/opaque). `doctor`
  reports their count as multi-account evidence.
* Which account produced a *historical* session is **not recoverable** from
  local stores: session rows carry no account field, CLI logs expose no
  account uid, and auth tokens live in browser OAuth rather than on disk.
  Attributing sessions by correlating timestamps with account switches
  would be speculation, violating ADR-004.

**Decision**: report account-config evidence (`doctor`), never scrape
credentials, and let the user attribute sessions explicitly via
`capture --note account:work`. `SessionMeta.origin` keeps recording the
store directory (harness provenance — still useful, just not an account).

## ADR-004: Clustering & extraction — deterministic heuristics, no embeddings

Options considered: deterministic signals (lineage, path-Jaccard, title
tokens, time windows) vs embedding-based similarity vs LLM summarization.

**Decision**: deterministic only. Same store ⇒ byte-identical bundle is a
trust property (bundles are diffable; "done" items are checkable); embeddings
break it and add model dependencies. Heuristic quality is a maintained
surface: thresholds are CLI flags (`--min-overlap`, `--window-days`), and
every signal is individually inspectable in the output.

## ADR-005: Session end state — evidence over inference

Parsers report only what their store can prove (ZCode's usage tables carry
real cancellation/truncation/error records). Cross-CLI inference (e.g.
"user_pending" from a dangling user message, "unknown" from a trailing
fragment) happens once, in summarize, so all parsers stay thin and the
inference rules live in one reviewable place. A cut-off assistant fragment
is dropped from conclusions rather than labeled — a wrong conclusion is
worse than a missing one.
