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

* **stable (13)**: `zcode`, `codebuddy`, `qoderwork`, `qoderwork-cn`,
  `qodercn-ide`, `qwenwork`, `workbuddy`, `dsh`, `codex`, `qoderwake-cn`,
  `qoderwork-app`, `qoderwork-cn-app` and `cherrystudio` — each is a sanitized
  sample of a real store that our parsers turn into sessions and messages in CI.
  `kimi` is **shape-only** (its store held one session with no dialogue), and
  `dsh` additionally needs the optional `zstd` extra; without it the matrix says
  `unavailable` instead of pretending the format is broken.
* **unverified (6)**: `claude`, `codebuddy-cn`, `qoder-ide`, `opencode`,
  `qoderwake`, `qwenwork-app`. Each one carries *why* it is unproven on this
  machine and the command that would close it: `matrix.UNPROVEN` is the table,
  `handoff evidence --check` prints every entry, the reasons ride in
  `config/support-matrix.json` as a `notes` field, and
  `tests/test_reader_lockstep.py` fails if an unverified reader has no reason or
  if the reason stops naming `scripts/sanitize_fixtures.py`. Two of the six are
  one machine away from proof rather than one investigation away: `qoderwake`
  reads fine but holds 0 transcripts (its CN sibling has 132 and *is* proven),
  and the `qwenwork-app` store is readable and holds 0 messages.
* **roadmap (1)**: `trae`. The two that used to sit here (`opencode`, Qoder IDE)
  have readers now, so they moved to the unverified list above — which is the
  honest direction: a parser that exists but has never seen a store is not the
  same claim as one that was never written.

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
5. **The international QoderWake has no store to sample here.** QoderWake reads
   two stores — team-group chats in SQLite under `~/.qoderwake*`, worker
   transcripts in the shared qoder store (`~/.qoder/projects`, `~/.qoder-cn/…`).
   The fixture writer mirrors both now, keeping the relative shape the parser
   derives them from, and `qoderwake-cn` is fixture-proven. `qoderwake` is not:
   this machine has no `~/.qoderwake/data/store` and no `~/.qoder/projects`, so
   there is nothing to sample. Its reader is the CN reader with a different store
   name, which is evidence, but "the same code with a different constant" is not
   a fixture.
6. **`claude` parser has never parsed Claude Code data.** Written against
   documented JSONL shapes; the family parser is shared by five CLIs that *are*
   proven, so it probably works — "probably" is what this list exists to expose.
   The same is true of `codebuddy-cn`, `qoder-ide` (roadmap: its sessions live in
   an Electron leveldb) and `qwenwork-app` (the store exists here with zero
   message rows in it).
7. **Cockpit performance is measured in one place only.** Search went 15.3 s →
   7 ms (warm, in-process) / 0.39 s (fresh process, warm disk cache) on the
   maintainer's machine. The 450-row session list takes several seconds to paint
   (observed while measuring layout at six widths), and that wait has not been
   profiled into stages: cold listing, `detail` generation, first paint.
8. **Narrow screens work, degraded.** A 3-page × 6-width × 2-theme sweep found and
   fixed a header whose controls overlapped below ~700px (you could not change
   page without hitting the theme switch), a session title column squeezed to
   zero width at 430px, an 8-column usage table that leaked past the viewport,
   and six 11px text nodes. Those are gone; what remains is that below ~500px the
   usage table scrolls inside its card, the timeline's 72 bins fall to ~4px each,
   and the sweep ran in a Chromium webview with same-origin iframes — not on a
   real phone or a touch browser. The *content* half of that was measured
   afterwards — five routes × seven widths (1600→430px), 0 elements wider than
   the page outside their own scroller, with a positive control so the sweep can
   fail — but it was still a Chromium webview, still one font stack, still a
   pointer rather than a finger.
9. **Collaboration is file-based, not live.** `publish / claim / release` now
   carry a lease (holder, deadline, exclusive claim write, 409 on conflict) so two
   agents cannot work the same handoff unknowingly. There is no push channel: the
   cockpit polls every 30 s, and two agents cannot exchange messages - only
   bundles. "Alternating on one task" works; "watching each other work" does not.
10. **The brief is still a summary; the raw layer is beside it, not in it.**
    `capture --full --raw` carries the vendor's original storage verbatim
    (hash-verifiable, extractable), but the *brief* the next agent reads is a
    rendered summary of that storage — it does not inline the tool calls or
    system rows. A successor that needs the unfiltered truth must ask for the
    raw archive, not rely on the brief.
11. **No editor-side integration.** No VS Code/Cursor extension, no skill/slash
    command; `handoff` is CLI-plus-local-web.
12. **Write-back is deliberately absent.** We never inject into another CLI's
    store (Constitution: read-only). That rules out "resume inside the target
    agent natively", which some competing tools do offer. A trade, not an
    oversight — but a functional limit from a user's point of view.
13. **Everything rests on one user, one OS family, one toolchain.** CI covers
    3 OSes × 3 Pythons for code paths that are unit-testable, and the fixtures
    make that part reproducible — but the store *shapes* were sampled from a
    single machine, and a locale, filesystem or permission model unlike this one
    is still untested ground.
14. **Not published on PyPI** (the badge was removed for that reason); install
    instructions work from source only.
15. **The focus sweep is synthetic and single-browser.** `--focus` calls
    `element.focus()` on every focusable element and then presses <kbd>Tab</kbd>
    through the same five routes × two themes, reading the computed ring (540
    nodes, 0 defects on the current build). It proves the style, and the review
    showed how much it missed when it *only* called `focus()` — antd's ring on a
    dropdown item, on a segmented item, and a second indicator on the slider —
    so both channels are now part of the check. What is still uncovered: focus
    trapping inside a dialog (this build renders none), what a screen reader
    announces, no ring has been seen on a second browser or a HiDPI display with
    different rounding, and the `:focus`/`:focus-visible` split means the 12%
    layer is keyboard-only for components that are not text fields (measured: a
    text input does match `:focus-visible` on a pointer click; a button does not).
    `prefers-reduced-motion` was measured on one element (no animations, `3px`
    immediately, against the running pair and a `5px` mid-flight sample with
    motion allowed) rather than across the sweep, which does not run in a
    reduced-motion context.

16. **The thread view reads a bounded slice of the store, and says so.** Clustering
    needs each session's touched files, and the only API that answers that is
    `Parser.load()`, which parses the whole record: measured here at **189ms per
    session over 802 sessions, ~150s**, with the largest single record at 4.6s.
    The pass therefore runs under a 15s budget, newest first, caches what it read
    (per session, keyed by `updated_at`), and reports
    `文件重叠信号覆盖 N/802 个会话（本次 Xs，已达时间预算）` with a *load more*
    action that continues from the cache — 72 sessions in the first pass, 85 after
    one refresh, and the rest cluster on lineage and title tokens alone. The
    honest gaps: the cache is in-memory, so a server restart re-pays; covering all
    802 sessions takes ~10 minutes of repeated passes; and no parser exposes a
    cheaper "which files" probe, so this is a limit of the parser API rather than
    of the view. A disk-backed cache keyed by `(cli, session_id, updated_at)`
    would make the second run free, and that is the follow-up.

17. **The hover/press sweep is a family sample, not a census.** `--states` puts a
    real pointer on one representative of each control *family* it finds on each
    route (44 controls across five routes × two themes on the current build),
    so a defect that only affects, say, the third row's button rather than the
    first would be missed — the sampling exists because a full census is ~700
    controls × four round trips each. It skips disabled and hidden controls (they
    cannot answer a pointer), it measures with one browser's transition timing,
    and its 8%/12% comparison is against the shadow's own alpha rather than
    against a composited screenshot, so a layer that is present but painted over
    by something else would pass. Focus, by contrast, *is* a census.

18. **The disabled-state check measures the gallery, not the product.** The whole
    running cockpit has two disabled controls (the pager's previous button on page
    one and the `<button>` inside it), so `--disabled` runs against the gallery's
    disabled variants — 18 of them, one per family the token file describes. That
    means it proves the *rules* compose the published opacities (and that nothing
    takes focus or answers the pointer), not that every call site in the product
    looks right: a page could disable a control in a way the gallery does not
    model. The two live ones are covered incidentally by the focus and overlap
    sweeps, which walk the session-detail route.

19. **A custom seed has never been refused, and the wall paper is unreadable.**
    The dynamic-colour palette follows whatever seed is stored
    (`localStorage["ah-seed"]`), derived by Google's library in the 2021 spec. Two
    honest limits: the AA gate on that seed has accepted **every** value tried
    (ten seeds, 5.23:1–5.30:1, because the tonal scheme pins tones) — it is
    insurance, not a filter, and its reject path was only ever exercised by
    mutating the threshold; and a browser cannot read the device's wallpaper or
    system accent, so "follow the device" means light/dark only
    (`prefers-color-scheme`). The generated palette is also a *different
    construction* from the shipped baseline — same spec, same roles, but the
    baseline is a published artefact while a seed is derived — so the two are not
    expected to coincide, and a seed set to the baseline's own primary does not
    reproduce the baseline. One browser, one spec version (2025-spec output from
    the same library was measured at 20–25 differing roles and is not what this
    ships).

20. **High-contrast modes are handled, not proven.** `forced-colors: active`
    restores hover/press feedback as a system-coloured outline (the mode drops
    `box-shadow`), and `--states` re-runs under it — but that arm is a *list* of
    families, and the check only covers the families the family-based sample
    reaches on the routes it visits; a control that appears nowhere in those five
    routes is not covered. `prefers-contrast: more` only strengthens separators
    (`--ah-line` → `--ah-line-strong`); it does not raise text contrast, change the
    palette, or thicken the focus ring, because M3 publishes no high-contrast
    variant for any of those and inventing one would be ours, not Google's. Both
    were measured under emulation in one browser — no real Windows high-contrast
    theme, no macOS "increase contrast", and no forced-colors run on the *gallery*
    (which the disabled sweep uses).

21. **The palette gate proves agreement with a pinned copy, not with upstream.**
    `tests/test_official_palette.py` compares our role→rung map and our rung
    colours against the two v0_192 files vendored under `tests/fixtures/m3spec/`,
    with their sha256 pinned. That proves the transcription is faithful to those
    bytes; it does **not** prove those bytes are still what upstream publishes
    today — the files were fetched on 2026-09-12 and nothing re-fetches them. The
    library's own arithmetic is a separate matter: `themeFromSourceColor` from the
    same repository produces the 2025 spec and differs from the 2021 baseline on
    20 of 29 comparable roles, which is why the runtime seed pins `specVersion`
    explicitly rather than taking the default. The comparison also covers the
    *colour* layer only; the geometry, type and motion layers are checked by their
    own tests against the values the generator cites.

22. **The layer gate has the same shape of limit, and one deliberate absence.**
    `tests/test_official_layers.py` covers the five non-colour layers against
    pinned copies of `_md-sys-shape/sc-elevation/state/typescale.scss`,
    `_md-ref-typeface.scss` and `packages/mdc-elevation/_elevation-theme.scss`:
    corners 12/12, elevation levels 6/6, the dp→shadow recipe 18/18 (three maps ×
    six levels, plus three opacities and the baseline colour), state 4/4, type
    10/10 shared roles — all zero differences, every layer mutation-proved. What
    it does **not** say: that those copies are still upstream (they were fetched on
    2026-09-12 and nothing re-fetches them), and it does not cover the five
    official type roles the cockpit does not carry (`display-large/medium/small`,
    `headline-large/medium`) — they are asserted absent by name, which makes
    *adding* one a deliberate test edit, but it also means the product has no
    display-size typography at all, because no view uses it. One fixture is MIT
    rather than Apache-2.0 (MDC-Web), and the tests assert both headers so the
    distinction cannot be lost in a re-vendor.

23. **The springs are checked; the curve built from them is ours.** The twelve
    damping/stiffness pairs are compared against androidx's two motion token files
    and `MotionScheme.kt` (12 pairs, 0 differences, plus each scheme referencing
    only its own file), but everything after the pair is a conversion this repo
    owns rather than a value Google publishes: 24 samples into a `linear()`
    easing, a settle tolerance of 0.001, and a cubic-bezier fallback chosen from
    the official curve set. The sampling is deterministic and regenerates with the
    tokens, but no official artefact says "M3E fast-spatial is *this* CSS curve",
    because M3E is not a CSS system — so the shape of the spring (overshoot for
    spatial, critical damping for effects) is checked by its own tests rather than
    against a file. Also unchecked against a file: the **component-level** token
    families (27 of them, from `ButtonSmallTokens` to `DockedToolbarTokens`). Each
    carries a `_source` naming the files it came from and an independent review
    once compared them by hand against 53 fetched files. That hand review is
    superseded now: `tests/test_official_components.py` is the repeatable gate
    for all 28 families (341 values against 148 vendored files, pinned in
    `tests/fixtures/m3spec/PINS.tsv`), and `scripts/fetch_m3spec.py` re-derives
    the corpus. Item 24 records what that gate does not say.

24. **The component gate proves agreement with pinned copies, and one popup is
    checked per property rather than all of them.** It compares our ~370
    authored values against the vendored androidx/material-web files, so it has
    the same limit as items 21 and 22: the copies were fetched on 2026-09-12,
    nothing re-fetches them, and a value that both we and the copy get wrong is
    invisible. Three things it deliberately does not do. It compares a
    *composed* corner by name rather than resolving the four radii (the radii
    are checked in their own layer test, and the five names are pinned). It does
    not re-check the layer values a component refers to (`@shape:lg`,
    `@role:primary`) — those belong to their own gates, and the field's
    `56 = 16 + 24 + 16` is the one composed number it does add up. And the
    `--eclipse` gate reads the popups the cockpit actually mounts (a Dropdown, a
    Select); a future view that mounts a component antd also paints would need
    its own entry in `ECLIPSED` before anything checked that our rule wins. The
    gallery's `.ah-field` and `.ah-mchip` families are measured in the audit
    gallery rather than in the product, because no view mounts them yet.

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

Two checks need more than a checkout, and are therefore commands a maintainer
runs rather than tests CI runs:

```bash
python scripts/sanitize_fixtures.py --cli <id>   # needs that CLI's live store
python scripts/audit_component_rules.py          # needs playwright + `npm ci`
python scripts/audit_component_rules.py --app http://127.0.0.1:8620/ \
  --route '#/' --route '#/memory' --focus          # the ring, in both themes
```

The second one asks the browser whether each Material rule in `web/src/m3.css`
reaches an element at all. Its absence is what let five families of dead CSS ship
— including a white snackbar on the dark theme — while every static gate was
green, because a rule can read every token it names and still apply to nothing.
`--focus` is the third question: not whether a rule matches, but what a keyboard
user sees when it does.

If you close a gap here, delete its entry. This file is done when it is empty.
