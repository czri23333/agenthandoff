# Context management across coding agents — what they do, what we borrow

Surveyed 2026-08-31 against public docs, source walkthroughs and the stores on a
real machine. The point is not academic: every row below tells us either a format
detail we must parse, or a mechanism that decides whether a handoff survives.

Sources are dated because these formats change underneath us — that is the whole
premise of [limitations.md](limitations.md).

## What each tool actually does

| Tool | Store shape | Context mechanism | Persistence model |
|---|---|---|---|
| **Claude Code** | `~/.claude/projects/<path-with-dashes>/<session-id>.jsonl`, append-only | Auto-compact at a token threshold; Session-Memory compaction first (a background sub-agent maintains a 10-section note, capped ~2 000/section, 12 000 total), full 9-section LLM summary as fallback; microcompact replaces old tool results and images with placeholders; circuit breaker stops after 3 failed compactions | **Append-only on disk.** The compact boundary is a record carrying `logicalParentUuid`; resume walks the `parentUuid` chain, stops at the boundary and reuses the stored summary — no re-summarising |
| **OpenCode** | `~/.local/share/opencode/storage` | Stepped governance: prune first (mark, not delete), summarise later | **Prune stamps `compacted = Date.now()`; the row stays in the DB and can be pulled back.** Guards: never touch the newest 40 000 tokens, act only if ≥20 000 tokens are freed, `skill` outputs are never pruned, last 2 user turns protected, `tail_turns=2`, `preserve_recent_tokens≈8 000` |
| **Codex CLI / desktop** | `$CODEX_HOME/sessions/<YYYY>/<MM>/<DD>/rollout-<ts>-<thread>.jsonl` + `session_index.jsonl` + `archived_sessions/` | Event stream (`session_meta`, `turn_context`, `response_item`, `event_msg` incl. `token_count`, `function_call(_output)`); dialogue must be *reconstructed*; assistant turns are written twice (API-visible + UI notification) | Event log, sub-agents are their own thread files with `source.subagent.thread_spawn.{parent_thread_id, agent_path, agent_nickname}`; `task_started` carries `model_context_window`, so "how full was it when it died" is answerable |
| **MiMo Code** (Xiaomi, OpenCode fork) | `.mimo/memory.db` (SQLite FTS5) + `checkpoint.md` / `MEMORY.md` / `notes.md` / `tasks/<id>/progress.md` | Four memory layers: Session → Project → Global → History; an independent *writer sub-agent* extracts state | **Checkpoints trigger at 20 % / 45 % / 70 % of the context budget, not at the wall** — each one an incremental update, because "waiting until it's full means the model is already degraded and extraction quality suffers". History layer keeps raw turns as the floor ("上层越来越精炼，下层越来越完整") |
| **Kimi Code CLI** | `~/.kimi-code/`, relocatable via `KIMI_CODE_HOME` | `/compact` (accepts a focus instruction), `/export`, `/export-md`, `/fork` (branch a session keeping history), `/sessions` | Files + `state.json`/`wire.jsonl` per session |
| **ZCode** | `~/.zcode/cli/db/db.sqlite` (read-only URI) | Compaction events recorded in-schema, plus explicit end-state columns (`context_exceeded`, `cancelled_by_user`, `error_type`) | SQLite; the only store we parse that *proves* how a session died |
| **Cursor / Trae / VS Code-family IDEs** | editor SQLite (`state.vscdb`, `ModularData/ai-agent/database.*`) | n/a (IDE-side session lists) | No documented file-level import path; export exists, import mostly does not |

## What we borrow, and why

1. **Never physically drop: keep a copy the tool can point back to.**
   Claude Code's append-only log and OpenCode's `compacted` stamp both encode the
   same rule: the summary is a *view*, the original stays recoverable. Our
   bundle/brief is a lossy view by design — so the vault (`src/agent_handoff/vault.py`)
   holds the full extraction and the brief carries a pointer to it.
   *Status: vault module written; wiring pending.*
2. **Snapshot early, not at the wall.** MiMo's 20/45/70 % ladder is the single
   most transferable idea here: extraction quality collapses when you only
   summarise a dying context. We can do this read-only — `handoff watch` snapshots
   a live session into the vault at budget thresholds using `model_context_window`
   / `token_count` (Codex), usage tables (ZCode) or size heuristics elsewhere.
   *Status: proposed; not implemented. This is the answer to "额度烧光时还能找回来".*
3. **Respect compaction boundaries instead of pretending they aren't there.**
   A bundle assembled from a compacted session must say so (we already surface
   `compaction` markers; the brief must never present a summary of a summary as
   the full story) — and if the vault has the pre-boundary turns, the boundary
   becomes recoverable rather than fatal.
4. **Protect the tail.** OpenCode's "never touch the newest 40 000 tokens" and
   "last 2 user turns" translate directly into our resume-pack budget: recent
   turns are verbatim, old turns are summarised, and the sections dropped first
   are the *least* recent. Today `digest` (last-round context) is priority 4 — the
   first thing thrown away, which is backwards.
   *Status: open defect, see limitations gap 1.*
5. **Env-var store relocation is table stakes.** `CODEX_HOME`, `KIMI_CODE_HOME`,
   `CLAUDE_CONFIG_DIR`, `XDG_*`: "installed somewhere else" must not break
   discovery. We now honour `AGENTHANDOFF_HOME` (whole-profile relocation) and
   `CODEX_HOME`; the rest follow the same probe.
   *Status: partial — one env var wired, others pending.*
6. **Sub-agent lineage is already in the stores.** Codex records `agent_path`
   (`/root/audio_wiring`) and nicknames; ZCode records `parent_id`; the Qoder
   family stores 118 sessions with parent links. That is free raw material for the
   agent-tree view and (later) any lease/conflict story — no invention needed.
   *Status: parsed into `meta.notes`; not yet visualised.*

## Where this leaves the positioning

Coverage breadth is a commodity in this niche: `tape` (12 agents incl. Qwen/Qoder/
MiMo/Kimi, CJK bigram search, npmmirror + Gitee delivery), `AgentRecall`
(CodeBuddy/WorkBuddy/Trae/Qoder + WSL/SSH), `TokenTracker` (29 tools) already
out-cover us, and none of that is reproducible evidence.

What none of them publish: a spec, a JSON Schema, a CI matrix, a derived
support table, fixture-proven parsing, or a format-drift sentinel. Claude Code's
own docs warn that entry formats "change between versions, so scripts parsing
these files directly may break on any version" — that warning *is* the argument
for the sentinel, and we can cite the vendor.

So the claim we can defend is narrow and checkable: **not "we read the most
tools", but "our support claims are the ones you can verify, and drift gets
detected instead of silently returning nothing."**
