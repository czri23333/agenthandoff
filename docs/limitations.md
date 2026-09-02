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
a checkmark — which is why the README table is no longer written by hand.

## Support status

Generated from the fixtures, on every commit: run `handoff matrix`, or read
[config/support-matrix.json](../config/support-matrix.json). Both README tables
are that same output, and CI fails if they drift from it
(`python -m agent_handoff.evidence --check`).

What that leaves, stated here rather than in the table:

* **proven (9)**: `zcode`, `codebuddy`, `qoderwork`, `qoderwork-cn`,
  `qodercn-ide`, `qwenwork`, `dsh`, `codex`, and `kimi` *shape-only* — each is a
  sanitized sample of a real store that our parsers turn into sessions and
  messages in CI.
* **unverified (2)**: `claude`, `codebuddy-cn`. Readers exist, no store was ever
  available to sample and no fixture ships, so nothing here proves they work.
  `dsh` additionally needs the optional `zstd` extra; without it the matrix says
  `unavailable` instead of pretending the format is broken.
* **roadmap (3)**: `opencode`, Qoder IDE (international, Electron leveldb),
  Trae/IDE-family.

The fixtures were built on one Windows host on 2026-08-31 from
`scripts/sanitize_fixtures.py`, and every `.fixture.json` says how much was
sampled away.

## Known gaps (this list is the roadmap; it is not complete by definition)

1. **A fixture freezes a format at one moment.** The conformance gate compares the
   committed fixtures against a fingerprint baseline, so it catches *our*
   regressions and any drift a maintainer introduces when regenerating. It cannot
   see a vendor rename a field until someone rebuilds the fixtures from a live
   store. Real-world format drift therefore still surfaces first for the person
   whose session comes back empty.
2. **Fixtures are samples, not archives.** 200 records per file and 300-character
   text is what ships, so a quirk that only appears in the 5,000th record of a
   megabyte transcript can stay hidden. Long-tail behaviour is verified where it
   is cheap to (the continuation pack was tested against a real 1,107-round
   session), not everywhere.
3. **Thin proof for two CLIs.** `qoderwork` (2 sessions / 3 messages) and
   `qwenwork` (1 / 2) are proven in the strict sense and weak in the practical
   one: the machine only had that much to give. `kimi` proves layout, not
   dialogue — its store holds one empty "New Session".
4. **Single-binary cockpit is unverified.** `docs/portable-single-exe.md` is a
   build recipe that has never been executed (`dist/` does not exist, PyInstaller
   is not installed here). Treat it as a proposal.
5. **`claude` parser has never parsed Claude Code data.** Written against
   documented JSONL shapes; the family parser is shared by five CLIs that *are*
   proven, so it probably works — "probably" is what this list exists to expose.
6. **Cockpit performance is measured in one place only.** Search went 15.3 s →
   7 ms (warm, in-process) / 0.39 s (fresh process, warm disk cache) on the
   maintainer's machine. The 450-row session list takes several seconds to paint
   (observed while measuring layout at six widths), and that wait has not been
   profiled into stages: cold listing, `detail` generation, first paint.
7. **Narrow screens work, degraded.** A 3-page × 6-width × 2-theme sweep found and
   fixed a header whose controls overlapped below ~700px (you could not change
   page without hitting the theme switch), a session title column squeezed to
   zero width at 430px, an 8-column usage table that leaked past the viewport,
   and six 11px text nodes. Those are gone; what remains is that below ~500px the
   usage table scrolls inside its card, the timeline's 72 bins fall to ~4px each,
   and the sweep ran in a Chromium webview with same-origin iframes — not on a
   real phone or a touch browser.
8. **Collaboration is file-based, not live.** `publish / claim / release` now
   carry a lease (holder, deadline, exclusive claim write, 409 on conflict) so two
   agents cannot work the same handoff unknowingly. There is no push channel: the
   cockpit polls every 30 s, and two agents cannot exchange messages - only
   bundles. "Alternating on one task" works; "watching each other work" does not.
9. **The brief is still a summary; the raw layer is beside it, not in it.**
    `capture --full --raw` carries the vendor's original storage verbatim
    (hash-verifiable, extractable), but the *brief* the next agent reads is a
    rendered summary of that storage — it does not inline the tool calls or
    system rows. A successor that needs the unfiltered truth must ask for the
    raw archive, not rely on the brief.
10. **No editor-side integration.** No VS Code/Cursor extension, no skill/slash
    command; `handoff` is CLI-plus-local-web.
11. **Write-back is deliberately absent.** We never inject into another CLI's
    store (Constitution: read-only). That rules out "resume inside the target
    agent natively", which some competing tools do offer. A trade, not an
    oversight — but a functional limit from a user's point of view.
12. **The bundle schema is documented, not enforced.** No test validates a
    rendered bundle against `schema/handoff-bundle-v0.1.schema.json`; the field
    contract is held by the renderers and their unit tests only.
13. **Everything rests on one user, one OS family, one toolchain.** CI covers
    3 OSes × 3 Pythons for code paths that are unit-testable, and the fixtures
    make that part reproducible — but the store *shapes* were sampled from a
    single machine, and a locale, filesystem or permission model unlike this one
    is still untested ground.
14. **Not published on PyPI** (the badge was removed for that reason); install
    instructions work from source only.

## How to check any of this yourself

```bash
handoff doctor                         # what is real on YOUR machine
handoff matrix                         # the support table, derived from the fixtures
handoff watch --cli codex --once       # one budget-ladder check on a live session
handoff ui                             # the cockpit at http://127.0.0.1:8620
pip install -e ".[dev,zstd,server]"
pytest                                 # parses every fixture, asserts its shape
python -m agent_handoff.evidence --check      # README/JSON vs the fixtures
python -m agent_handoff.conformance --check   # format fingerprints vs the baseline
```

If you close a gap here, delete its entry. This file is done when it is empty.
