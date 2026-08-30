# Competitive Research — session handoff for AI coding CLIs

*Survey date: 2026-08-30. Sources: GitHub topic [`context-handoff`](https://github.com/topics/context-handoff) (21 public repos), GitHub search, Reddit r/ClaudeCode, dev.to, OpenAI community forum.*

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

## Sources

- [GitHub topic: context-handoff](https://github.com/topics/context-handoff)
- [r/ClaudeCode — "I built a tool Handoff"](https://www.reddit.com/r/ClaudeCode/comments/1sd5ubf/i_built_a_tool_handoff_switch_ai_agents/)
- [dev.to — "Stop losing AI coding context between sessions: Continue Later"](https://dev.to/dhruv_anand_aintech/stop-losing-ai-coding-context-between-sessions-continue-later-skills-cli-3jca)
- [OpenAI community — context-pack MCP](https://community.openai.com/t/context-pack-mcp-tool-for-high-signal-context-handoff-between-ai-agents/1374795)
