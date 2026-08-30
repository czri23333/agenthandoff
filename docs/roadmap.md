# Roadmap — what this product must become

Requirements below come from real usage review (2026-08-30), in the owner's
words, plus systematic gap-fills. Guiding rule: **ADR-009 — nothing specific
to one user's setup may be hardcoded**; everything scene-specific lives in
config files or is derived from data shapes at runtime.

## Now — must exist before any public release

| # | Requirement | Source | Design |
|---|---|---|---|
| 1 | **Bilingual UI (zh/en at minimum)**, Chinese default | owner: "你这ui不是纯英文吗要至少双语" | i18n dictionary layer, all views; language switch persisted |
| 2 | **Token accounting per session/model**: input, output, reasoning, cache write/read, calls, avg TTFT, tokens/s | owner: "每条消息的模型和努力程度和token（输入输出缓存），计费或者额度" `token速度` | Parser-level `usage()` protocol — ZCode reads its `model_usage` table, dsh reads `assistant/chunk` usage records, others return None honestly. No cost math without a user-supplied price file |
| 3 | **Project/domain grouping without hardcoding** — owner's domains (h3, webgal, rustwebgal, mixed) must come from config, not code | owner: "你能确定哪些是h3,哪些是webgal…" + ADR-009 | cwd is the default domain (universal); optional rules file `~/.agenthandoff/domains.toml` (`pattern → domain`) lets any user subdivide; mixed sessions already carry topic segments |
| 4 | **Full-text search** across titles, message bodies, file paths | owner: "查询功能考虑了吗" | backend `/api/search` over parsed transcripts, cached; UI search box searches everything, not just titles |
| 5 | **Transcript view** — read the actual message history of a session | owner: "历史消息…考虑了吗" | detail view gains a messages pane (user/assistant stream) |

## Next — the relay loop end-to-end

| # | Requirement | Source | Design |
|---|---|---|---|
| 6 | **One-key relay flow**: interrupted session → brief → new session started in target CLI with the brief attached | owner: "真实工程怎么靠这个接力" | launcher registry grows a `dispatch` action per verified CLI (headless flags); cockpit button runs it; no manual copy-paste |
| 7 | **Multi-agent collaboration board**: published handoffs, claims, results — the cockpit as coordination surface | owner: "协作" | inbox grows result reporting; per-thread view shows the whole relay chain |
| 8 | **Quota/billing view**: spend per account/provider over time | owner: "计费或者额度之类" | optional price file (user-provided, any format documented) × usage data; ADR-009: prices never hardcoded |
| 9 | **Backup management**: session stores are irreplaceable user assets | owner: "备份管理" | `handoff backup` — export stores/bundles to an archive; scheduled snapshots; restore tooling |
| 10 | **New-session launcher inside the cockpit** | owner: "新开考虑了吗" | open a fresh session in a chosen CLI with cwd + optional seed prompt |

## Later — scale and trust

| # | Requirement | Source |
|---|---|---|
| 11 | Effort/reasoning-effort display per turn | owner: "努力程度" |
| 12 | Store schema-version drift monitoring (`doctor` warns when an upstream format changed) | engineering |
| 13 | Packaging: PyPI + wheel with bundled frontend dist | release |
| 14 | GitHub release hygiene (identity rewrite, badges, topics) — blocked on #1–5 | owner: "不要发质量很差的东西" |

## Status

Done so far: deterministic engine (11 CLIs), interruption awareness, threads,
exchange, cockpit skeleton with 5 views, dogfooding fix batch.
In progress: #1, #2, #3 (this batch). Everything else queued in order.
