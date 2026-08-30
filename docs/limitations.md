# What this project has verified — and what it has not

Kept deliberately blunt. Every claim in this repo must be attributable to one of
three evidence levels, and anything that cannot be is labelled as unproven
rather than quietly upgraded to "supported".

| Level | Meaning | Reproducible by you? |
|---|---|---|
| **proven** | a sanitized fixture in `tests/fixtures/sanitized/` is parsed by our code in CI, with asserted shape | yes — `pytest` on a clean clone |
| **seen** | the parser read a *real* store on the maintainer's machine on the stated date | no — depends on your machine, but `handoff doctor` tells you instantly |
| **claimed** | code exists and looks right; nobody ever fed it real or fixture data | no |

`claimed` is not support. A row that is only `claimed` must never be rendered as
a checkmark.

## Support status, honestly (audited 2026-08-31)

| CLI | level | evidence |
|---|---|---|
| `zcode` | **seen** | 453 sessions listed on the maintainer's machine, SQLite opened read-only |
| `qodercn-ide` | **seen** | 118 session files read |
| `codebuddy` | **seen** | 32 session files read |
| `qoderwork-cn` | **seen** | 11 session files, 2 account configs |
| `qoderwork` | **seen** | 2 session files |
| `qwenwork` | **seen** | 1 session file |
| `dsh` | **seen** | 46 zstd rolls + a WSL-side store read through `\\wsl.localhost` |
| `kimi` | seen (1 session), **experimental** | single session parsed; format undocumented |
| `codex` | **fails** | 19 rollout files detected, none parseable — the parser does not match the current rollout layout |
| `claude` | **claimed** | never verified: no store existed to test against, no fixture shipped |
| `codebuddy-cn` | **claimed** | never verified: same |
| `opencode`, Qoder IDE (intl.), Trae/IDE-family | **roadmap** | not attempted |

**No row is `proven` yet** — `tests/fixtures/sanitized/` does not exist. Until it
does, the whole matrix rests on one person's machine, which is exactly the kind of
claim a reviewer can and should discount.

## Known gaps (this list is the roadmap; it is not complete by definition)

1. **Continuation fidelity in the scenario that matters most.** When a session
   dies on quota — the single most common reason anyone needs this tool — the
   continuation brief is *least* able to carry what it needs: `resume.py` drops
   whole sections by priority and the last-round context section (`digest`) is
   priority 4, i.e. the first thing thrown away. There is no verbatim recent-turn
   section at all. This is a design defect, not a missing feature.
2. **The support matrix is still hand-maintained.** `src/agent_handoff/matrix.py`
   derives statuses from evidence, but it is **not wired in**: it needs a
   `with_root()` hook on the parsers and there are no fixtures to measure. Until
   it lands, README rows can drift from reality again — and one already did
   (`codex` was listed ✅ stable while `doctor` reported it unreadable).
3. **No format-conformance sentinel.** The field-wide failure mode — a vendor
   renames a field, conversion "succeeds" and returns nothing — is not detected by
   anything in this repo today. No fingerprint baselines, no degradation rules,
   no CI gate.
4. **Single-binary cockpit is unverified.** `docs/portable-single-exe.md` gives a
   build recipe that has never been executed (`dist/` does not exist, PyInstaller
   is not installed here). Treat that document as a proposal.
5. **`claude` parser has never parsed Claude Code data.** Written against
   documented JSONL shapes; the family parser is shared by five CLIs that *are*
   seen, so it probably works — "probably" is what this section exists to expose.
6. **Concurrency of the search index is untested.** A background writer thread and
   request threads share one WAL-mode SQLite file; single-flight build and
   cross-process behaviour under two cockpit instances are not covered by tests.
7. **Cockpit performance is measured in one place only.** Search went 15.3 s →
   7 ms (warm, in-process) / 0.39 s (fresh process, warm disk cache). Session-list
   cold start, `detail` generation and first paint have not been profiled; the
   dashboard re-renders every second and re-fetches 453 sessions every 30 s.
8. **Light mode is machine-audited, not human-approved.** All 2,039 text nodes pass
   WCAG AA in both themes by DOM measurement, and the token table is gated by
   `tests/test_tokens_contrast.py` — but no human has looked at the light theme yet
   (screenshot review pending).
9. **No multi-agent collaboration.** `publish/inbox/claim` is one-shot file
   exchange: no lease, no conflict detection, no live channel. "Alternating
   agents on one task" is unimplemented.
10. **No charts/visualisation.** Usage is a table; task threads are text.
11. **No editor-side integration.** No VS Code/Cursor extension, no skill/slash
    command; `handoff` is CLI-plus-local-web only.
12. **Write-back is deliberately absent.** We never inject into another CLI's
    store (Constitution: read-only). That rules out "resume inside the target
    agent natively", which some competing tools do offer. It is a trade, not an
    oversight — but it *is* a functional limitation from a user's point of view.
13. **Bundle format is v0.1 while the schema and spec drift risk is unchecked.** No
    test validates rendered bundles against `schema/handoff-bundle-v0.1.schema.json`.
14. **Everything runs on one machine, one OS family, one user.** CI covers 3 OSes ×
    3 Pythons for code paths that are unit-testable, but "seen" evidence for store
    formats comes from a single Windows host with a specific toolchain installed.
15. **Not published on PyPI** (README badge removed for that reason); install
    instructions work from source only.

## How to check any of this yourself

```bash
handoff doctor                      # what is real on YOUR machine
handoff doctor --markdown           # (not implemented yet — see gap 2)
pytest                              # the proven layer, once fixtures exist
python scripts/gen_readme_matrix.py --check   # README vs reality (not implemented yet)
```

If you fix a gap here, delete its entry. This file is done when it is empty.
