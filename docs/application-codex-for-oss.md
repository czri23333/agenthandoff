# Codex for OSS — application draft (agenthandoff)

> Draft for the maintainer to adapt to the form's actual prompts. Every factual
> claim below is traceable to something in this repository at the time of writing;
> anything that cannot be proven is labelled, not asserted. Numbers marked
> `(verify)` should be re-confirmed against the live repo before submitting.

---

## 1. What the project is, and why it matters

**agenthandoff** hands off any AI coding CLI session to the next agent —
deterministically, locally, and without touching the source CLI's data.

Every coding agent (Claude Code, Codex, Cursor, Kimi, Qoder, CodeBuddy, …) writes
its conversation to a private store in its own format. When a session dies on a
quota limit, a context overflow, or a crash, the *next* agent starts cold: the
work, the decisions, and the interrupted turn are stranded in a format no other
tool reads. agenthandoff reads those stores **read-only**, distills them into a
diffable handoff bundle, and renders a continuation brief the next agent can paste.

Why this matters beyond convenience:

- **Interrupted work is the common case, not the exception.** Sessions end on
  quota and context limits constantly. `handoff watch` exists precisely for this:
  it snapshots a running session at 20/45/70/90% of its context budget so a
  quota death never loses the most recent turns.
- **No write-back, ever.** The tool never injects into another CLI's store. This
  is a deliberate constraint (documented in `docs/limitations.md`), and it is what
  makes the tool safe to run against live sessions.
- **Zero-dependency core.** The library is stdlib-only; CLI codecs (zstd) and the
  cockpit (FastAPI) are optional extras, so a reviewer can install and run it with
  nothing but Python.

What makes it different from the other session-handoff tools is **verifiability**.
Support claims in this repo are not written by hand; they are *measured*:

- 9 sanitized, privacy-audited fixtures of real session stores live in
  `tests/fixtures/sanitized/`. They preserve each vendor's exact record shapes,
  keys, and enums while replacing every string, and they are parsed in CI.
- The README support matrix is **generated** from those fixtures
  (`python -m agent_handoff.evidence --write`), and CI fails if the published
  matrix or the format fingerprints drift from what the fixtures actually yield.
- A session either parses to real dialogue (status `stable`), has no fixture
  (`unverified`), or its store held nothing to sample (`shape-only`). There is no
  "claimed" tier anymore — a claim that cannot be proven is not shown as support.

## 2. Why Codex, and what we would do with it

The project is at the stage where breadth and honesty are gated on *access to real
data and sustained engineering attention*, both of which Codex directly addresses.

Concretely, the roadmap items that Codex would unblock (each is an open gap in
`docs/limitations.md`):

1. **Prove the unproven parsers.** `claude` and `codebuddy-cn` have readers but no
   fixture, so they are honestly labelled unverified. Turning them `stable` needs
   real Claude Code session data and the same sanitize → fixture → CI loop already
   built for the other nine CLIs. Codex time is what closes that gap.
2. **Live collaboration.** `publish / claim / release` with leases already prevent
   two agents from working one handoff at once, but there is no push channel —
   agents alternate, they do not watch each other. A live channel (SSE or similar)
   is designed but not built.
3. **Editor-side integration.** No VS Code/Cursor extension and no skill/slash
   command exist; the tool is CLI-plus-local-web. An editor surface is the largest
   remaining usability gap.
4. **Portability.** A single-binary cockpit (PyInstaller recipe exists in
   `docs/portable-single-exe.md`) has never been executed. Making `handoff ui`
   install-and-run without Python would remove the biggest adoption friction.
5. **Performance and hardening at scale.** The search index is profiled in one
   place; cold listing, detail generation, and first paint are not. Cross-process
   and multi-thread index writes are tested (and caught two real lost-write bugs),
   but long-running cockpit behavior under load is unverified.

Codex would be used the way the tool itself works: each session handed off with a
bundle, so no context is lost between runs — we would be the project's most
demanding user.

## 3. Current status — honestly

What is true today, with the caveat that all of it is single-machine evidence:

- **Readers for 11 CLIs; 9 proven by fixtures.** Support matrix at the time of
  writing: 8 `stable`, 1 `shape-only` (kimi's store held one empty session),
  2 `unverified` (claude, codebuddy-cn), 3 `roadmap` (opencode, Qoder IDE, Trae).
  `(verify against README before submitting.)`
- **164 tests, all passing**, plus ruff lint and the two evidence gates, on
  Linux/Windows/macOS × Python 3.10/3.12/3.13 in CI. `(verify count.)`
- **Known gaps are written down, not hidden.** `docs/limitations.md` lists the open
  items, including the ones above, the absence of editor integration, and the fact
  that every fixture was sampled from one user's machine.

What we are *not* claiming:

- We do not claim the two unverified parsers work — there is no fixture to prove
  them, and saying otherwise would be exactly the failure this project was built to
  prevent.
- We do not claim multi-user realtime collaboration — leases exist, a live channel
  does not.
- We do not claim portability — the single-binary build has never been run.

---

### Notes for the maintainer

- Keep every number traceable: the support matrix, fixture list, and test count
  should be regenerated (not re-typed) right before submission.
- The form's word limits will likely require cutting; prefer cutting prose over
  cutting the honesty caveats — the caveats are the point.
- If the form asks for links, point at the repository, `tests/fixtures/sanitized/`,
  and `docs/limitations.md`.
