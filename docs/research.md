# Competitive Research — session handoff for AI coding CLIs

*Initial survey: 2026-08-30. Learning sweep below: 2026-09-01. Sources: GitHub
topic [`context-handoff`](https://github.com/topics/context-handoff) (21 public
repos as of Aug 30; still 21+ on Sep 1), GitHub search, Reddit r/ClaudeCode,
dev.to, OpenAI community forum, npm/GitHub trending coverage.*

## Why this survey exists

Before building `agenthandoff` we needed to know whether the "resume an AI
coding session in another CLI/tool" problem is already solved, and where the
gaps are. Conclusion up front:

1. **The space is active** — 21 repos, the most recent pushes in August 2026.
2. **Overseas CLIs are well covered** (Claude Code, Codex, Cursor, Cline,
   OpenCode, Gemini CLI, …).
3. **Chinese-ecosystem CLIs are covered by nobody**: Qoderwork, Qwen Work CN,
   CodeBuddy / CodeBuddy CN, MiMoCode, dsh, ZCode — zero entries in the topic.
4. **Most tools delegate handoff quality to the model itself** ("ask the agent
   to write a HANDOFF.md"). Only a minority parse the CLI's own local session
   storage deterministically.
5. **No open, tool-neutral bundle format** with a published schema — every
   project invents a private one-shot format.

## Landscape by category

| Category | Representative work | How it works | Limitation we address |
|---|---|---|---|
| Universal storage extractor (CLI) | Go CLI on `context-handoff` topic covering Claude Code, Codex, Cursor, Cline, Kimi, Antigravity, OpenCode, Pi Agent | Reads each CLI's local session files, transfers/resumes | No Chinese-ecosystem CLIs; closed format |
| Agent-authored handoff file | "Handoff" (r/ClaudeCode, `HANDOFF.md` watcher), "Continue Later" (skills + CLI), 薪尽火传 Agent Relay (verifiable handoff protocol) | A skill/prompt tells the agent to write a handoff doc before exiting | Quality depends on model compliance; nothing captured if the session crashes; non-deterministic |
| MCP bridge | Claude Code ↔ Codex CLI bridge (MCP), `context-pack` (MCP, pass code excerpts) | Live inter-agent messaging via MCP | Requires both ends online simultaneously; setup cost |
| Orchestrator with shared memory | Multi-agent orchestrators on the topic (persistent memory tree, session viewer + handoff doc generator) | Runs agents inside one harness with a shared store | Locks you into the orchestrator; not for CLI users |
| IDE built-ins | Continue/OpenCode context meter (structured handoff at ~60% usage) | Harness-internal trigger | Only works inside that harness |

## Where `agenthandoff` sits

**Positioning: the deterministic, local-first, coverage-maximal extractor with
an open bundle format.**

| Differentiator | Evidence of the gap |
|---|---|
| **Chinese-ecosystem CLI coverage** — Qoderwork, Qwen Work CN, CodeBuddy (+CN), dsh, ZCode, Kimi CLI, plus Claude Code | None of the 21 repos list any of these |
| **Deterministic extraction** — parse each CLI's own storage (SQLite/JSONL/zstd-JSONL), no model in the loop, reproducible output | Most competitors are prompt/skill-based |
| **Zero-dependency core** — stdlib only; zstd support ships as an optional extra | Matters for security review and air-gapped use |
| **Open bundle format** — versioned spec + JSON Schema, readable by humans and machines | Competitors use private one-off formats |
| **Engineering-grade resume prompt** — budgeted, priority-ordered brief, not a transcript dump | Handoff files from skill-based tools are unbounded prose |

## Honest risks

- **Crowded topic.** New repos must earn attention; we compete on coverage,
  determinism and format discipline, not on being first.
- **Private formats drift.** Every parser targets an undocumented storage
  layout. Mitigation: version-tolerant readers, corruption-tolerant line
  parsing, a fixture-based test suite per dialect, and `handoff doctor` that
  reports exactly which store broke.
- **"Good enough" built-ins.** CLIs keep improving native resume (`claude
  --resume`, `codex resume`). Our niche is *cross-CLI and cross-machine*
  handoff, which built-ins do not do.

## Learning sweep — 2026-09-01

A second pass over the space, one day later, focused on *what to learn*
rather than positioning. The category is visibly consolidating: trending
coverage (Builder Radar, week of Aug 30) counts at least five actively
maintained repos for agent memory/context persistence alone.

### ai-memory (akitaonrosso/ai-memory, Rust) — the strongest competitor

5,366 GitHub stars (verified via the GitHub API, pushed 2026-09-01); the
repo is `akitaonrails/ai-memory`. Read its README closely; it is the product
our README will be compared against. What it does and does not do, honestly:

- **Live hook capture, not post-hoc parsing.** It installs lifecycle hooks
  (MCP config + per-CLI hook files) into ~20 agents, captures bounded
  observations (user prompts ≤16 KiB, tool excerpts ≤2 KB, automatic secret
  redaction) into a spool, and *compiles* them into a git-backed markdown
  wiki ("compile, don't retrieve", Karpathy-wiki influence). At session end
  the observations become a handoff; the next agent receives it **injected
  before its first prompt** via SessionStart hooks.
- **Managed workstreams.** `ai-memory run claude` → `ai-memory run codex`
  resumes the *native* session of each harness plus a portable visible-event
  ledger. Covers Claude Code, Codex, OpenCode, Pi, Crush, Kimi Code, Command
  Code, Kiro CLI v2/v3, OMP, Grok Build, Antigravity.
- **Support matrix honesty that we should copy.** Every row states the
  mechanism *and* the limitation ("Hooks-only", "MCP-only", "no true
  session-end hook — run `finalize-session`", "verified live against engine
  v0.16.5"). This is exactly the `stable`/`shape-only`/`unverified`
  discipline we built, applied per agent instead of per parser.
- **ZCode is hooks-only there** (no store parser; tracked as its issue
  #512). Our offline zcode parser remains a real differentiator.
- **What it does NOT cover:** none of the Chinese-ecosystem CLIs we parse
  offline (CodeBuddy/CN, Qoderwork, QwenWork, dsh, MiMo) — but see the
  correction in the Sep 1 status check below: AgentRecall's GUI now covers
  part of this list. It also cannot operate without first installing hooks
  — a session that ran before installation has nothing to hand off. That is
  the hole agenthandoff sits in: **deterministic post-hoc extraction from
  whatever is already on disk.**

### Other entries worth watching

- **Agent Handoff (npm, v0.6.0)** — event-sourced memory:
  `.agent-handoff/EVENTS.jsonl` is the single source of truth, `STATE.json`
  and `CONTEXT.md` (≤200 lines) are derived reducers; `memory verify` checks
  file completeness, event parseability, state/log consistency, evidence
  commits and **log key-leak**; cross-machine sync is plain git. Its
  "reported ≠ observed ≠ verified" evidence levels are a good vocabulary.
- **Hermes Agent v0.18+** — a harness-native `/handoff <target>` command
  that transfers the live session to another model/persona. Proof that
  harnesses will absorb handoff as a built-in (the "good enough built-ins"
  risk below is real and accelerating).
- **Memmy (MemOS team)** — open-sourced local memory base with GUI/CLI/TUI,
  OpenAI-compatible API and MCP; targets the same "switch agents, not
  context" pitch with a heavier product surface.
- **GitHub Copilot Sessions** (Aug 2026) — multi-session sidebar (n/x/
  arrows) to keep parallel agent sessions from contaminating each other.
  Native multi-session UX is moving into the harnesses themselves.

### What we should learn (concrete, prioritized)

1. **Delivery beats format.** ai-memory's real edge is not capture — it is
   *automatic injection at the next session start*. Our bundle currently
   ends at "print/paste the brief". Highest-value gap: a `handoff inject`
   path (append to AGENTS.md / project rule file, or hook the target CLI's
   session-start where one exists) so the receiving agent never needs to be
   told manually.
2. **Git-native artifacts.** The npm Agent Handoff keeps everything
   diffable in `.agent-handoff/`. Our bundles are portable but not
   git-committed by default; a one-command `publish`-to-repo flow would
   give the same cross-machine story without a server.
3. **`verify` as a first-class verb.** Its `memory verify` (completeness,
   parseability, consistency, leak check, budget) mirrors our doctor +
   privacy scanner + evidence check, but packaged as *one* command the user
   runs before sharing. Worth consolidating.
4. **Bootstrapping from code, not sessions.** `ai-memory bootstrap` seeds
   pages from git log/README/docs. We only know a project from its sessions;
   a bootstrap mode would make the first bundle useful even when the CLI
   history is empty.
5. **Keep our moat sharp.** What none of them have: offline deterministic
   parsing of Chinese-ecosystem stores, zero-dependency core, evidence-
   graded fixtures with leak scanning, and a versioned open bundle schema.
   The learning items above should extend that position, not imitate the
   hook-based architecture — that race is already crowded and server-shaped.

### Status check — the seven tools named in the Aug 30 survey

Queried the npm registry and GitHub API directly (2026-09-01). What is real
today, versus what no longer checks out:

| Tool | Status today (verified) | Verdict |
|---|---|---|
| AgentRecall | `zszz3/AgentRecall` — 779 stars, pushed **today**, MIT, TypeScript/Electron desktop app. v1: unified search/view/resume/migrate/export over Claude Code + Codex plus 12 optional sources; v2 preview adds workbench, multi-agent Chat, Workflow, Eval, Runtime, directory memory. Supabase-based cross-device sync; MCP gateway; token usage + quota display | **Alive and the closest direct competitor.** See below |
| AgentTape | `renrenmimi/AgentTape` — 0 stars but pushed today (created Aug 29). Replays a *finished* Claude Code session entirely in the browser; `check` command asserts a session against rule sets (exit codes 0/1/2, CI-embeddable) | Alive, tiny, but **the purest form of our "post-hoc, no instrumentation" thesis** |
| tokscale | `junhoyeo/tokscale` — 5,233 stars, pushed Aug 31, Rust. Terminal token/cost tracker over 15+ agent stores (OpenCode DB, `~/.claude/projects`, `~/.codex/sessions`, Copilot OTel, Hermes state.db, Gemini chats, Cursor CSV, Droid, Amp, Codebuff…) | Alive, dominant. Not handoff — but its **per-CLI store-location table is the best published map of the space** |
| ResumeSession | npm `resumesession` v1.0.4, last modified **2025-12-28** ("cross-CLI memory sharing") | Stale — no movement in 8+ months |
| TokenTracker | npm `token-tracker` is an unrelated 2023 blockchain module; `tokentracker` does not exist. The live successor is tokscale | Name did not survive; category absorbed by tokscale |
| tape (session tool) | npm `tape` is the 2012 test harness — unrelated. No active "tape" handoff package found; nearest living ideas are AgentTape and two 0-star recorders (vibe-tape, June) | The name from the survey does not resolve to a real product today |
| baton | npm `baton` is a 2022 dead orchestration package. GitHub has `kzoldyk/baton` (2 stars, desktop cross-agent handoff app, pushed Aug 30) and `timurabi3/baton-mcp` (0 stars, zero-dependency MCP handoff) | The npm package is dead; the idea lives on as two micro-repos |
| save-my-session | npm v0.5.1, created Apr 2026, last modified **May 2026** ("transfer sessions between Claude Code, Gemini CLI, Codex") | Quiet since May — possibly abandoned |
| agent-teleport | npm v0.3.1, created Mar 2026, last modified **Mar 2026** ("convert agent sessions between formats") | One-shot release, no follow-up |

**Two corrections to the Aug 30 conclusions:**

- **"Chinese-ecosystem CLIs are covered by nobody" is no longer fully true.**
  AgentRecall v1 lists CodeBuddy, WorkBuddy, CodeWiz, TClaude, TCodex,
  OpenClaw, Hermes, OpenCode, ZCode, Cursor Agent, Trae and Qoder as
  optional sources, with per-source honesty ("WorkBuddy 首版仅支持本地搜索、
  查看和导出……不支持 Resume、迁移"). What it still does not cover: dsh and
  MiMo, and it has no open bundle format. Our remaining defensible claims:
  dsh/MiMo coverage, deterministic exportable bundles, evidence-graded
  fixtures, zero-dependency core, and a schema nobody else publishes.
- **Three of the seven names were already stale or never real** (token-tracker,
  tape, baton-as-package). The survey lesson: verify every competitor name
  against a registry before citing it.

**New things to learn from these three alive ones:**

6. **AgentTape's `check` verb.** Asserting a *finished* session against rules
   ("it looped", "it hit a context wall", "a tool hung", strict mode: "read
   before edit") with CI exit codes is a category we do not occupy. Its
   structure-only `.tape.json` checks exactly as the original — our
   shape-only fixture concept, taken one step further into QA.
7. **AgentTape's privacy enforcement is verifiable**: `node verify.mjs`
   asserts no source file makes a non-loopback network request. Our privacy
   scanner checks output; checking *the tool itself* this way is stronger.
8. **tokscale's store-location table.** A maintained, per-CLI table of where
   each agent keeps its sessions is exactly the map our parsers encode
   privately; publishing ours would be cheap authority in the space.
9. **AgentRecall proves the GUI + local-first + Chinese-ecosystem combination
   wins attention** (779 stars in three months). Our answer is not to build
   an Electron app — it is the already-planned single-binary cockpit, plus a
   bundle format its "export" cannot claim to be open.

### Implementation-level notes — reading their source, not their stars

Same day, pulled the actual source of the three alive competitors via the
GitHub API (trees + 12 key files read line by line). What their engineering
actually does, and what it means for us:

**AgentTape (`renrenmimi/AgentTape`) — redaction done right**

- `lib/redact.ts` is *subtractive*: the redactor is never handed the
  transcript. It reads only the index (numbers, writer vocabulary, one
  96-char preview field), so "no body reaches the output" holds by
  construction — not by filter quality. Then `auditRedacted()` re-walks the
  finished export asking "is this string in a slot allowed to hold a name?"
  against a whitelist (placeholders, fixed labels, `SAFE_NAME` regex), which
  is a much narrower question than "does this look safe?".
- Correlation ids are *renumbered* per export (`t1`, `m4`) because opaque ids
  get quoted inside message bodies and would otherwise travel along.
  Placeholders keep the *length* (`[text 1,284 chars]`) because the length
  is the analytically useful part.
- Our privacy pipeline is the opposite shape: content substitution + leak
  scanning. Their slot-audit-on-the-output is a stronger second gate, and
  both could coexist in our flow.
- `lib/assert.ts`: the rule vocabulary is deliberately five rules (before /
  max-repeats / max-context / max-tool-seconds / ends-clean) — "the moment a
  rule needs a parser, the thing being tested stops being the run". Each
  result carries a `vacuous` flag separating "nothing violated this" from
  "this was never tested". That pass/vacuous distinction is exactly our
  proven/shape-only honesty, applied to assertions.
- `.github/workflows/ci.yml` is worth reading as a document: the in-page
  selftest asserts the *exact totals* (`164/168 passed · 0 failed · 4 not
  run here`) because totals that merely "didn't fail" hid 18 broken
  assertions through six green runs; a `counters` step deliberately breaks
  its own guards four ways and requires each break to be caught by the
  right counter; and the tool dogfoods its own exit-code contract in both
  directions (passing fixture exits 0, failing fixture must exit non-zero).
  Mutating your own test to prove it bites is a discipline our CI does not
  have yet.

**AgentRecall (`zszz3/AgentRecall`) — the cost of writing back**

- `codex-migration-repair.ts`: after a format change broke sessions it had
  *itself* written into `~/.codex/sessions`, it ships a repair pass that
  scans every rollout, touches only files carrying its own `originator`
  marker + `cli_version: "migration"`, patches ids in place via a chunked
  `r+` handle, renames filenames to canonical form, and counts
  scanned/repaired/failed. Lesson: anything that writes into a vendor store
  must carry an originator marker and ship its own forward-repair.
- `zcode-session-writer.ts` (they *delete* sessions inside zcode's SQLite):
  refuses any path that is not literally `…/cli/db/db.sqlite`; writes a
  backup next to the database before mutating; `busy_timeout=5000` +
  `foreign_keys=ON` + `BEGIN IMMEDIATE` + rollback; deletes in 500-id
  chunks; ATTACHes the second `tasks-index.sqlite` DB so the cross-database
  mutation is one transaction; soft-deletes task-index rows to match the
  vendor client's own deletion behavior. This is the most careful
  vendor-store write path in the space, and it exists because they crossed
  the read-only line we have not crossed.
- `atomic-config-write.ts` in 40 lines: save previous → temp file (pid+uuid,
  mode 0o600) → rename → run a `verify()` callback → on failure restore
  previous or delete. Write-verify-rollback as a reusable primitive.
- Every core module ships a same-named test (46 core modules, near-1:1 test
  ratio). Their zcode loader has 16.9 KB of tests for 12.9 KB of code.

**tokscale (`junhoyeo/tokscale`) — corruption tolerance with receipts**

- `sessions/utils.rs` documents issue #1031: Rust `BufReader::lines()` ends
  iteration on the first invalid-UTF-8 line, so one stray byte silently
  discarded the *rest* of a transcript — measured as ~2% of an 83 MB Grok
  `updates.jsonl` surviving. Their fix is lossy per-line decoding so the
  damage stays local to the bad line, plus BOM stripping and "I/O error
  means stop, not retry". **Our `read_jsonl` already opens with
  `errors="replace"` and skips malformed lines**, so we are on the right
  side of this bug — but their writeup is the citation for why that matters,
  and a good fixture scenario (inject one bad byte mid-file, assert the
  tail still parses).
- `sessions/codebuddy.rs` (109 lines total): one CodeBuddy shape is actually
  four sources — CLI JSONL under `~/.codebuddy/projects/<key>/`, plus IDE
  extension logs and two VS Code extension-host log formats, each with a
  real-world-shaped test literal (including `rawUsage` with
  `prompt_cache_hit_tokens` and log-line usage JSON). Delegates to a shared
  `tencent_buddy` module — the same jsonl-family factoring we use. Their
  coverage of CodeBuddy is *usage-only* (token counting), not conversation
  content — our content-level fixtures remain differentiated.

**ai-memory (`akitaonrails/ai-memory`) — privacy as a type boundary**

Read `sanitize.rs`, `handoff.rs`, `capture_policy.rs`. The strongest
engineering in the space is in its privacy layer:

- `Sanitized<T>` is a newtype whose *only* constructor runs the scrub —
  persistence code can only receive `Sanitized<NewObservation>`, so "skip
  the sanitizer" is a compile error, not a convention. Our privacy scanner
  checks after the fact; theirs makes the wrong call unrepresentable.
- The built-in redaction list (28 patterns) is annotated with the mistakes
  that produced each anchoring decision: AWS keys are pinned to exactly 20
  chars because `ASIA` is an English word and an open tail destroyed
  `ASIAPACIFICREGION` — "the strip runs BEFORE storage and is irreversible";
  Telegram tokens carry two branches because the docs' own example fell
  outside the original shape; GoHighLevel's `pit-` is anchored to a UUID
  because `pit-` is an English fragment. It also states a deliberate
  non-goal: standalone high-entropy strings are *not* caught, because
  false positives at that layer are unrecoverable. False-positive tolerance
  is tuned per pattern, not globally.
- Truncation is head-plus-tail with a visible marker (head `max/2`, tail
  `max/2`, `...[truncated N bytes]...` between) because head-only truncation
  showed the consolidator an incomplete tool output and degraded summaries.
  Code-point-safe throughout.
- `handoff.rs`: the handoff is a first-class row with an explicit state
  machine (open → accepted/expired) and an acceptance record (which agent,
  session and *operator* took the baton, when) — "stored explicitly rather
  than inferred from the observations log because cross-agent continuity is
  the headline feature". Same conviction as our exchange/claim/lease, and
  their accepted_by_user split ("which agent" vs "which teammate") is a
  refinement our lease file does not yet carry.
- `capture_policy.rs` is pure, IO-free policy evaluation with hard budgets
  on every untrusted input (≤128 ignore patterns, ≤1 KiB per pattern, ≤64
  KiB marker read, ≤1,000,000 pattern-by-path comparisons per inspection).
  Its comments document issue #446: denylist mode makes "forgot the marker"
  a leak, allowlist mode makes it a recall miss — and the gate must sit
  above event kinds or "prompt text, the field the issue cares about most,
  flows anyway". Treating the policy *file itself* as adversarial input
  with explicit work budgets is a discipline our fixture readers could copy.

**What this changes for agenthandoff (implementation priorities)**

10. Add a slot-audit gate to the privacy pipeline: after sanitization, walk
    the exported structure and require every string to match a whitelist of
    allowed shapes (placeholder / fixed label / safe-name). AgentTape's
    `auditRedacted` is the model.
11. If we ever write into a vendor store (`inject`, resume-support), adopt
    AgentRecall's full checklist: originator marker, path-shape guard,
    pre-mutation backup, `BEGIN IMMEDIATE`, chunked statements, and a
    shipped repair pass for our own earlier writes.
12. Add a "bad byte mid-file" JSONL fixture asserting tail survival, citing
    tokscale #1031 as the motivating incident.
13. Adopt the CI discipline of asserting exact test totals and dogfooding
    exit-code contracts in both directions — both are cheap and both have
    already caught real regressions elsewhere.
14. Adopt ai-memory's secret-pattern pack (or cite it) for our privacy
    scanner — anchored per vendor prefix, with the false-positive postmortems
    kept as comments — and make our own "what we deliberately do not catch"
    statement explicit.
15. Put explicit byte/work budgets on every untrusted input we read
    (fixture manifests, marker files, published bundles), the way
    `capture_policy.rs` bounds pattern count, pattern length and match work.

### Honest limits of this sweep

- Star counts and feature claims come from the repos' own READMEs and press
  coverage; only agenthandoff's own claims are independently tested here.
- ai-memory's per-agent hook matrices were read, not executed.
- The npm Agent Handoff write-up comes from a tutorial article (v0.6.0),
  not from running the tool.

## Sources

- [GitHub topic: context-handoff](https://github.com/topics/context-handoff)
- [r/ClaudeCode — "I built a tool Handoff"](https://www.reddit.com/r/ClaudeCode/comments/1sd5ubf/i_built_a_tool_handoff_switch_ai_agents/)
- [dev.to — "Stop losing AI coding context between sessions: Continue Later"](https://dev.to/dhruv_anand_aintech/stop-losing-ai-coding-context-between-sessions-continue-later-skills-cli-3jca)
- [OpenAI community — context-pack MCP](https://community.openai.com/t/context-pack-mcp-tool-for-high-signal-context-handoff-between-ai-agents/1374795)
- [GitHub — akitaonrosso/ai-memory](https://github.com/akitaonrosso/ai-memory)
- [CSDN — Agent Handoff v0.6.0 跨电脑同步教程](https://blog.csdn.net/q977734161/article/details/164223721)
- [Builder Radar — week of Aug 30, 2026 (agent-memory category)](https://buttondown.com/Builder-Radar/archive/builder-radar-week-of-august-30-2026/)
- [Hermes Agent practitioner reference (2026)](https://blakecrosley.com/guides/hermes)
