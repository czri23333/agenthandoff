---
feature: divergent-slice-parity-1
status: delivered
updated: 2026-09-10
branch: compose/divergent-slice-parity-1
commits: c033438..HEAD
---

# Divergent Slice Parity 1

## Report

**What was built.** Three things, all of them about the gap between what the parse layer *does* and what the repo *says* it does.

1. **A session title can no longer be markup.** `is_noise()` keeps `data-role="user-context"` reminder turns on purpose (dropping them would hide real conversation), and both session-title paths reused that predicate and took `text[:80]` of whatever survived — so the transcript policy was answering a title question. `BaseParser.title_candidate()` now strips a *leading* paired envelope (an envelope followed by a real question still yields the question), strips the remaining markup and the synthetic `[思考]`/`[工具]`/`[子代理]` prefixes, and requires the result to read as text. Because a sample of the affected sessions showed 25 of 30 had *no* usable user text (billing/connection errors, mostly), skipping alone would have sent 83 % of them to the tool-loop placeholder, which the list filters out — i.e. it would have hidden them. The ladder is therefore the product's own priority order (custom > ai/provisional/fallback > legacy): official ai-title, then the first usable user text, then the first assistant line, then the placeholder.
2. **Three prose claims of verification were corrected.** `README.md` said the repo ships no fixtures (twelve ship). `docs/limitations.md` hand-wrote "proven (9) / unverified (2) / roadmap (3)" beside its own generated 11 / 8 / 1 table, in a file whose opening principle is that the table is not written by hand; the counts are gone in favour of the live command. Four docstrings said "verified live" / "behaves identically" / "100 % key match verified" with nothing behind them; each now says whether it is `seen` or fixture-proven.
3. **The support table stopped lying about ten stores.** Seven shipping readers and three fixture-proven ones rendered their store column as `unknown`, and two of the three roadmap entries ("no reader") named CLIs that have shipped readers — those rows were not stale, they were *silently dropped*, because roadmap rows are appended only for unregistered CLIs. The store kinds are filled in, and `tests/test_matrix.py` now fails on any of the four ways that can go wrong again.

**Verification.** Live-store measurement, before and after, over 771 sessions / 20 readers: sessions whose title is raw markup **124 → 0** (all 124 were workbuddy, out of 156 of its sessions). A 30-session sample of the offenders, before the fix, split 5 with a later usable user turn / 25 with only an assistant turn / 0 with neither — the number that decided the ladder, because 25 would otherwise have been hidden. Three regression tests cover envelope-only, envelope-plus-question in one row, and the placeholder case, plus an assertion that the envelope is still present in `load()`'s transcript. `uv run pytest tests/` → **242 passed**; `ruff check .` → clean; `evidence --check` → README/zh/JSON all regenerated in lockstep and matching; `conformance --check` → 12 CLIs match.

**Journey log.** (1) The title defect was found by looking at a screenshot of the cockpit rather than at its code: eight rows were titled `<system-reminder data-role="user-context"> <user_info> OS Ve…`. (2) My first measurement of it reported **0** offenders, because the probe's markup regex `^<[a-z_]+[\s>]` does not match a tag name containing a hyphen — a reminder that a measurement that agrees with your hope deserves the same suspicion as one that does not. (3) The safest-looking fix would have been worse than the bug: I nearly widened `clean_text()`'s `<system-reminder>` pattern to accept attributes, which would have emptied the *transcript* text of every affected turn (an empty user bubble) instead of fixing the title. The fix is now title-local, and a test pins the body policy separately.

**Disclosures.** Nothing on this branch has run on a GitHub runner (no pull request yet; the workflow triggers on `pull_request` or on `push` to `main`). The four readers with **no test contact at all** — `codebuddy-cn`, `qoder-ide`, `opencode`, and (before this branch) `workbuddy` — are only partly addressed: workbuddy now has title coverage, and the other three are untouched. Making them genuinely fixture-proven is the next slice, and it is now a *provenance* decision rather than a coding one: this machine holds a live opencode store with 222 sessions, so `scripts/sanitize_fixtures.py` could turn that reader from unverified to proven — but that commits content derived from the user's real sessions, so it needs an inspection pass for personal identifiers before anything is staged, which is why it was not rushed into this branch.

## [S1] Problem

1. **Titles were derived with a transcript predicate.** Measured: 124 of 156 workbuddy sessions in the live store were titled with the raw turn text (`<system-reminder data-role="user-context"> <user_info> OS Version: win32 …`). Root cause: `is_noise()` returns `False` for those turns *by design* (they are real turns in the body), and `jsonl_family.py`'s two title paths then took `text[:80]` of the survivor.
2. **A naive fix hides 83 % of the affected sessions.** Of 30 sampled offenders, 5 had a later usable user turn and 25 had only an assistant turn; a session with no title falls to `_TOOLLOOP_TITLE`, which `list_sessions()` filters out — so "skip and keep scanning" alone converts a visible defect into a silent disappearance.
3. **Documentation claimed evidence the repo does not have.** `README.md:142` ("the repo ships no fixtures yet" — twelve ship); `docs/limitations.md`'s hand-written counts (9/2/3) against its own generated table (11/8/1), in a file that says the table is not written by hand; four docstrings asserting live verification for readers with no fixture and no CI coverage.
4. **The generated support table had `unknown` in ten store cells**, and two of its three roadmap rows named registered CLIs, which are silently dropped rather than flagged.

## [S2] Design

**Separate the two questions.** A transcript predicate answers "does this turn belong in the body?"; a title predicate answers "does this read as a title?". `BaseParser.title_candidate()` is the second one and is title-local by construction: `_LEADING_ENVELOPE` (paired, repeated) → `_ANY_TAG` → synthetic prefixes → must contain an alphanumeric and must not start with `<`. `clean_text()` and `is_noise()` are untouched, so the body policy cannot drift as a side effect — and a test asserts the envelope is still in the transcript.

**Derive the title through the product's own ladder.** `ai-title > first user text that is a candidate > first assistant line > placeholder`. The middle two are the "provisional/fallback" tier the asar rule table documents, and the assistant tier is what keeps 25 of 30 affected sessions visible.

**Make the matrix's human input guarded.** `matrix.py` keeps exactly two hand-written dicts; both are now test-covered: every registered parser needs a store kind (no `unknown` cells), every store kind needs a zh label, no roadmap entry may name a registered parser, and the generated rows are asserted end-to-end to contain no `unknown`.

**Correct claims to the level of evidence they hold.** `seen` (read on a real store, not reproducible by you) and fixture-proven are different things; the docstrings and the limitations page now say which is which, and the rot-prone counts are replaced by the command that produces them.

## [S3] Out of Scope

Building sanitized fixtures for `codebuddy-cn`, `qoder-ide` and `opencode` (the real path to proven, deferred for the PII-inspection reason above); the render-side rule #6 (automation executions should be hidden from the default list, currently shown as a badge) and #7 (our per-message `dur_ms` chips exceed the official client, which bills only in the header); palette, motion, or layout changes; anything that changes what the transcript *content* is.

## Tasks
- [x] T1: A title is never markup — `title_candidate()` in `base.py`, applied to both title paths in `jsonl_family.py`, with the assistant fallback tier. Verified against the live store: 124 → 0 markup titles over 771 sessions; 3 regression tests (envelope-only → assistant line; envelope + question in one row → the question; envelope-only with nothing else → not a title) plus one asserting the envelope survives in `load()` (covers: S1.1, S1.2)
- [x] T2: The honesty pass — README's fixture claim, `limitations.md`'s stale counts replaced by the live command, and four docstrings corrected to say `seen` vs fixture-proven (covers: S1.3)
- [x] T3: The support matrix — ten store kinds filled in from the readers, zh labels added, the two false roadmap entries removed, `tests/test_matrix.py` guarding all four failure modes; README/zh/JSON regenerated in lockstep (`evidence --check` green) (covers: S1.4)
- [ ] T4: Fixture-proven coverage for `codebuddy-cn`, `qoder-ide`, `opencode` — deferred to the next slice, with the reason recorded: it commits content derived from live sessions, so it needs a sanitize-and-inspect pass rather than a rushed one (covers: the remaining half of the coverage gap)
