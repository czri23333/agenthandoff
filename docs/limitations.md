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
5. **The international QoderWake's own half has no store to sample here.**
   QoderWake reads two stores — team-group chats in SQLite under `~/.qoderwake*`,
   worker transcripts in the shared qoder store (`~/.qoder/projects`,
   `~/.qoder-cn/…`). The fixture writer mirrors both now, keeping the relative
   shape the parser derives them from, and `qoderwake-cn` is fixture-proven.
   `qoderwake` is not, and the reason is narrower than this item used to say:
   re-measured 2026-09-20, `~/.qoder/projects` **does** exist on this machine and
   holds **4,211** `.jsonl` transcripts — this item previously claimed it did
   not, which was simply stale. Those transcripts are not lost to the product:
   the `qoder-ide` reader lists **2,259** sessions out of that same directory.
   What is missing is the daemon half — `~/.qoderwake/data/store` is absent — so
   `qoderwake` itself yields 0 sessions and there is nothing to sanitize. One
   reading to keep in mind: `doctor` prints `readable yes · parses yes (0)` for
   it, because `readable` measures *either* half (the shared one has content) and
   `parses` measures what the wake reader itself returns (nothing). Neither field
   is false; together they are easy to misread as a contradiction.
6. **`claude` parser has never parsed Claude Code data.** Written against
   documented JSONL shapes; the family parser is shared by five CLIs that *are*
   proven, so it probably works — "probably" is what this list exists to expose.
   `codebuddy-cn` is the same case: probed 2026-09-20, this machine has no store
   for it, so there is nothing to parse. `qwenwork-app` is a different shape of
   the same gap — its store exists, opens, and holds **0** message rows, so the
   reader has been run against the real file and found nothing in it to prove.
   This item also used to name `qoder-ide`, with "its sessions live in an
   Electron leveldb" as the reason. Measured 2026-09-20 that was stale twice
   over: the reader points at `~/.qoder/projects`, lists **2,259** `.jsonl`
   sessions, and **25 of 25** sampled ones load with dialogue (**14,487**
   messages between them). What `qoder-ide` still lacks is a *fixture* — the
   shipped set carries `qodercn-ide` and no `qoder-ide`, so CI cannot re-run what
   this machine proves.
7. **The session list is now profiled into stages, and the first paint is the
   stage that was slow.** Search went 15.3 s → 7 ms (warm, in-process) / 0.39 s
   (fresh process, warm disk cache) on the maintainer's machine. The list was
   measured end to end — a server started in-process, a browser launched the
   moment the port opened — and the breakdown was: **port up 1.06 s**, app shell
   **0.21 s**, `/api/stores` **0.47 s**, `/api/sessions` **5.27 s**, first row
   **6.17 s**, all 187 mounted rows **7.67 s**. Before the work below the same
   measurement read 9.21 s / 10.91 s / 12.43 s. What it found and what was done:
   `peek_status` asked every session for its own files while the file list re-read
   the header of **every** rollout (11,440 header reads, 8.1 s of a 16.2 s build) —
   headers are cached by `(path, mtime, size)` now, because a header cannot change
   once written; the jsonl family re-read 800 lines per file on every rebuild —
   that peek is cached by file version too; the list is warmed at process start
   (`AGENTHANDOFF_PREWARM=0` turns it off) so the browser's own startup overlaps
   the build; and a stale entry used to be rebuilt *synchronously* by whichever
   request won the lock, which cost one caller per TTL a whole build (measured
   4.07 s to first row with everything else warm) — it refreshes in a thread and
   answers with the stale list, which is what "stale answer beats a queue" was
   always supposed to mean. Build times: cold **16.2 s → 5.4 s**, rebuild
   **7.6 s → 2.8–3.4 s**. What is left is attributed: the first build is **1332
   `read_jsonl` calls parsing 91,155 rows** (measured by wrapping the reader), 319
   of those calls the jsonl family's peeks and 110 the rollout headers, the rest
   the other thirteen stores' own head reads. Laziness is not the next win — a peek
   already stops at 800 lines or the end of the file, whichever comes first, and
   most of those files are shorter than the cap. `peek_status` reads the newest
   rollout's tail as well now (spec Round 36): one 64 KB read for a session that
   ends at the last row it wrote, widened ×4 until it holds an end event for the
   two that do not. Measured as three adjacent A/B pairs on the cold list request
   that cost +4.5% / −1.1% / −1.8%, which is nothing this measurement can
   separate from noise; the same sessions' cold build ranged 11.3–13.5 s across
   those runs, so treat the 5.4 s above as a different day's store, not a
   baseline to hold later runs to. That predicted next gain — a cheaper head read
   per rebuild — is now taken (spec Round 50), and the honest way to state it is
   by *work done* rather than seconds, because the two figures in this item are
   different scopes on different days' stores: the number Round 50 moves is
   `_build_session_roots(None, None, None)` — all 20 stores this machine has
   (4,631 `.jsonl` files in the seven the jsonl family reads; 2,638 rows listed)
   — whose steady-state rebuild went from **4,599 distinct files opened through
   the reader to 16**, and from 15 store walks to 9, for **11.3 s → 8.3 s**. The
   seconds are the part this machine cannot measure tightly; the counters are the
   claim, and their scope is stated because a wider one (tracing `open()` itself)
   finds **2,411** calls on the same steady rebuild — 37 from the reader and
   **2,323 from `_tail_rows`**, the per-row probes that read a transcript's end to
   answer "needs an answer" and "how did it end". What the remaining seconds are
   is attributed in the spec (Round 50), and Rounds 51–52 cut what that named: a
   rebuild's `os.stat` calls went **114,728 → 15,556** and its wall clock
   **11.29 s → 3.48 s**. Round 51 walked the store with `os.scandir` (the directory
   entry already carries type, mtime and size, so the id peek, the meta peek, the
   canonical ranking and the fragment scan stopped re-asking) and resolved each
   store root once. Round 52 found the codex store holding 69 % of what was left:
   `_session_files` re-derived the whole rollout list once per session — 103
   sessions × 110 files × 2 stats — and it is now memoised against the file list it
   came from, so a rollout that appears or is renamed still re-derives. Answers held
   fixed both times: four rebuilds with the walk facts on and off, 2,491 rows × 12
   fields, 0 differing rows at the on/off boundary and at the same-configuration
   control; and all 103 codex rows × 8 fields plus both per-row probes, with and
   without the memo, identical. What is left is attributed rather than assumed:
   `_family_of_path`'s per-session `resolve()` (2,320 stats), `dsh`'s own listing
   (1,432), and 2,319 opens per rebuild from the per-row tail probes — a question
   worth re-asking, since the answer is supposed to be current.
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
    make that part reproducible — but the store *shapes* come from one machine.
    That basis is now partly measured instead of sampled: the sweep that asked
    *every* file of one live store (this machine's `qoder-ide`, **4,214 jsonl /
    328,530 rows** — 100 % of the rows that store holds, spec Round 48) found four
    sub-types the 131-session sample had never met, one of which was a real
    under-reporting bug (item 34). The other readers are still sample-backed, and
    "complete" is therefore machine-relative:
    `python scripts/sweep_row_shapes.py --cli <id>` re-asks the question of
    whoever's store you point it at, and exits 1 on any shape nobody classified.
    A locale, filesystem or permission model unlike this one is untested ground.
14. **Not published on PyPI** (the badge was removed for that reason); install
    instructions work from source only.
15. **The focus sweep is synthetic and single-browser.** `--focus` calls
    `element.focus()` on every focusable element and then presses <kbd>Tab</kbd>
    through the same five routes × two themes, reading the computed ring (measured
    today: **~1,230** focusable elements across two themes and one session-detail
    route, 0 defects, 13-18 rings delegated to the box the reader sees; the count
    moves run to run because the sweep measures live stores and rows mount as
    sessions arrive, not because the route moves — it is picked deterministically).
    It takes two readings,
    1400x1000 and 700x900, because the two size classes do not show the same
    controls: the rail is hidden below 1200px and the tab strip comes back, so a
    ring on either one would otherwise have no reading at all. It proves the style, and the review
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
    route, at both size classes (measured today: **24** controls, 8%/12% on every
    one), and it needs `--app` to have routes at all — run alone it reports
    "examined only 0 controls" and fails rather than passing on nothing.
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
    for all 29 families (measured today: **362** values against **151** vendored
    files, pinned in `tests/fixtures/m3spec/PINS.tsv`), and
    `scripts/fetch_m3spec.py` re-derives the corpus. Two of those files are not
    token tables at all — the adaptive pane directive and androidx.window's size
    classes — and their numbers are pinned by `tests/test_official_panes.py`
    instead (see item 25). Item 24 records what that gate does not say.

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

25. **A forked transcript is linked, not joined.** Codex writes a fork's page
    without the turns it inherited: 26 of the sessions this reader lists carry a
    `subagent_history_start_ordinal` (8 to 1022) naming the thread the earlier turns
    live in, and in 26 of 26 cases that thread *is* in the store. The cockpit now
    says so in the transcript — a `role: "history"` marker at the oldest end whose
    link opens the parent thread — and in the facts list, and it does **not** merge
    the two: joining them would invent a session shape, and the ordinal is not
    countable in the parent's own rows - five candidate units (all rows,
    item_completed, response_item, user messages, assistant messages) were counted
    in the parent up to each child's header timestamp across 8 fork pairs, and
    **none** of them matches the ordinal (the largest pair: ordinal 619 against
    3619 / 502 / 2371 / 2 / 133). The unit is the vendor's own event accounting,
    which it does not publish; until that is known, merging is guesswork. A reader who wants the earlier
    turns reads them where they are. The same rule places a compaction divider by
    position (`after_messages`) rather than by timestamp, because 11 of the 14
    Codex sessions that have a divider put every row inside the same second.
    The IDE family forks *inside* a file instead, and that one the reader is
    shown: a record names the user turn the editor rewrote, and the transcript
    marks both ends of it - the named copy as the abandoned version, the turn
    written under the record as the re-send - without deleting either. Measured
    over 77 such records in 7 real sessions: every record named a user turn in
    the same file, and 63 of them named a turn that was itself a re-send, so
    the two marks are separate flags rather than one label.
26. **The pane geometry is official; the surfaces it frames are ours.** The
    adaptive directive gives the width classes, the partition count and the pane
    width, and `tests/test_official_panes.py` pins those against the vendored files
    — but *which* surfaces sit in the panes is a product decision: the frame is
    `SessionDetail`'s (transcript + brief/meta), and the dashboard is deliberately
    single-pane at every width because its content is a toolbar, a chart and a
    table rather than a list a detail could sit beside. Two published values are
    carried but unspent for the same reason (`preferredHeight` 420dp is the
    *vertical* partition this web layout does not have; the rail's 96dp and 44dp
    describe a container the collapsed form does not render). All three are written
    down beside the tokens rather than dressed up as used.
27. **The first-token split is spent, and only where a store writes one.** A
    codex `task_complete` times both the turn and its first token. Re-measured
    here on 2026-09-20: **179 of 223** rows carry
    `time_to_first_token_ms` (443 ms … 11,262 ms), and **0 of the 179** exceed
    that row's own `duration_ms` — so the reader spends it as a *part* of that
    total, never as a second one. It surfaces in the transcript row's hover
    tip: `+35.1s · 首字 4.3s / 输出 30.8s`, measured in a real browser on a
    live session, where the tip used to say only `+35.1s`. Two boundaries
    stand. (a) The tip is the only surface: render rule #7 keeps billing out
    of the message area, so this rides the same hover as the total and is not
    a new chip. (b) A turn whose completion wrote no split shows the total
    alone, and a total the server *derived* from adjacent timestamps never
    borrows a store-written split — `app.py` requires the store's own
    `duration_ms` beside it, and `test_detail_carries_the_first_token_half_only_of_its_own_total`
    names that case. Of the 14 fixture stores, 3 time a first token at all:
    codex per turn (the tip), zcode and CherryStudio per model (the usage
    table's 首字延迟 / `ttft` column, spent since well before this item — the tip
    deliberately reuses that word so the two surfaces name one thing); the other
    11 write no such number.
31. **Most sessions in the cockpit cannot have their ending proven, and never
    could.** Of the 3,322 sessions on this machine, **2,710** belong to stores
    whose parser never builds an `Interruption` at all - qoder-ide (2,259),
    opencode (222), workbuddy (156) and nine smaller ones. That is not a probe
    that could be written better: qoder-ide's transcript vocabulary is
    `assistant / user / active-leaf / attachment / last-prompt / …` with **no
    end, complete, error or abort row anywhere**, so nothing in the file records
    how the turn stopped. Since spec Round 39 these read `unknown` (labelled
    "结束状态未记录", coloured neutral) where they used to read `clean` by
    falling off the end of a dataclass default. The gap is therefore upstream in
    what those CLIs write, not in the reader - and the honest reading of a grey
    label is "this tool's log does not say", not "the cockpit broke". The one
    inference still available is positional: an un-answered final user message,
    which is how 2 of the 8 sampled opencode sessions surface as `user_pending`.
    That inference was tried as a cheap probe on 2026-09-19 and **measured
    away**: it answered for only **20 of the 2,291** family sessions, and of the
    8 times it did answer, **6 contradicted the detail page** (qodercn-ide 2
    agreeing against 5 conflicting), because `_finalize_interruption` also
    requires that the session has an assistant reply and compares the two
    timestamps - a 16 KB tail scan sees neither. Those 20 sessions already
    surface through `peek_needs_reply`, which drives the "等你回复" count, the
    filter and the tooltip, so the probe would have added a second, drift-prone
    place to say the same thing. It is not in the product.
    Widened on 2026-09-20, because "the transcript has no end row" is a claim
    about one of a store's two artifact kinds: `~/.qoder/projects` also writes
    **2,341** `state.json` sidecars, all of which parse (0 unreadable), and not
    one of them holds a key resembling `status`/`finish`/`error`/`abort`/`exit`
    - the fields are `createdAt`/`revision`/`updatedAt` and a `state` dict of
    client bookkeeping (`replacementDecisions`, `seenFunctionResponseIds`). So
    the ending is unrecorded in **both** places, and `unknown` is the whole of
    what can be said. The same sweep did find 19 session directories holding
    state with no transcript at all - nothing to show, and `doctor` now counts
    them rather than letting them go silently missing (spec Round 47).
32. **A fork record whose link leaves the file says so, and stops there.** The
    transcript marks the two turns a `resend-fork-notice` names, but a claim that
    cannot be placed is not carried onward: if the turn under the record never
    became a turn at all (noise-filtered, or a mirror of one already kept) the
    re-send mark is simply absent, and a record naming a turn this file does not
    contain becomes a `fork_target_missing:N` note. Both happen in the shipped
    fixture, where the sanitizer removed rows - 15 of its 17 records mark a
    re-send, 14 mark the edited turn, and 3 report a missing target.
    The re-send end is inferred from position, and the store's own link was
    checked against that inference rather than trusted: where a record carries
    `parentId` (44 of 77 on this machine, 8 of 27 in the fixture) the record,
    the edited turn and the turn below it share one parent in **44 of 44** and
    **8 of 8** cases, so the two readings of the fork agree wherever both
    exist. The remaining records carry no parent at all, which is why the
    reader keeps the positional rule instead of the id - and `parentId` is a
    request-level group here (one parent shared by up to 41 rows, 21 of them
    user turns), so following it instead of adjacency would mark turns the
    record never introduced. `tests/test_family_fork.py` pins both halves.
33. **The brief carries the abandoned copy of a fork, unannotated.** The cockpit's
    transcript marks both ends of a fork the store records (item 25), but the
    handoff brief is a verbatim surface: `build_full_transcript` quotes every
    turn it kept, so a turn the user retracted rides into the successor's
    context with no marker. Measured on this machine's 7 sessions with fork
    records: **77 of 4,096** turns in the lossless brief and **4 of 109** in the
    budgeted tail are abandoned copies, and **0** of them reach `<rules>` (the
    directives a successor actually obeys). The replacement sits directly below
    each one, oldest-first, so the live instruction is always present; the cost
    is a reader who must notice which of two similar turns came later. Annotating
    it means putting the parser's own words inside quoted dialogue, which is the
    one thing a byte-faithful brief is not allowed to do.

34. **Nothing shows which skills a session invoked, and `plan_mode` siblings
    were only half-read until now.** Two findings from the first sweep that asked
    every file in a live store instead of a sample (spec Round 48; this machine's
    `qoder-ide` store, **4,214 jsonl / 328,530 rows**, run
    `python scripts/sweep_row_shapes.py --cli qoder-ide` to reproduce it on yours):

    - `attachment/invoked_skills` (**2 rows**) names the skills a session ran,
      with each `SKILL.md` path and its text. No surface renders that, and the
      product's model has nowhere honest to put it: a skill file the harness
      loaded is not a file the session worked on, so it is excluded from
      touched-paths rather than inflating that list with the toolchain's own
      files. It is therefore excused in the parser and named here, which is the
      difference between a gap and a silence.
    - `attachment/plan_mode_reentry` was reading as *unread* while its three
      `plan_*` siblings were read, so a plan opened on re-entry did not count
      toward the files a session touched. Fixed in the same round
      (`FILE_BEARING_ATTACHMENTS`), verified against the live session that
      carried it.

    The deeper limit is the one item 13 already states: the shape lists were
    derived from this machine. `scripts/sweep_row_shapes.py` exists so "complete"
    is a question any user can ask of their own store rather than something this
    file asserts.

35. **The keyboard cursor is real in flat mode and partial in grouped mode, and
    the productivity-tool research is only 1/12 spent.** Spec Round 53 added
    `↑`/`↓`/`j`/`k`/`PageUp`/`PageDown`/`Home`/`End`/`Enter`, a shortcut strip, and
    a poll that holds while a row or a field has focus (measured: 0 `/api/sessions`
    requests in a 62.4 s window with a row focused, 2 in the same-length control
    window; `python scripts/audit_component_rules.py --app-only --keys --app
    http://127.0.0.1:8620` re-asks it). What is still open, in the words the
    research used:

    - **Grouped paging.** `↓` at the end of a truncated group moves to the next
      group rather than paging that group in, so keyboard paging is proven only in
      flat mode (50 → 100 rows). The expander stays Tab-reachable and `↑` from it
      returns to the last row. Which reading a reader wants is unmeasured: there is
      one user of this app and they have not tried it yet.
    - **Not shipped from the twelve**: pinyin-initial matching for CJK titles
      (PowerToys Run's *Use Pinyin*; the title filter is a substring match, so a
      session named 回答两个字：可以 has nothing latin to type), frequency×recency
      ranking (Raycast's ordering, PowerToys' *Selected item weight*), the density
      toggle with `tabular-nums`, column
      visibility and sort persistence, the contextual action zone (Tab through
      per-row buttons), ⌘K with multi-select cross-CLI handoff, the preview pane
      (Space / ⌘Y), ⌘1-9 source switch, undo toasts, and `overflow-anchor: none`
      with a self-managed scroll offset once the list is virtualised.
    - **Shipped from the twelve, differently: absolute time.** The research's
      "Today/This week" buckets became a cutoff in `relTime()` — 30 days and under
      keep the relative label, older rows show `07-21` (`25-03-09` across a year
      boundary), because the column is 64 px of mono in a list that is scanned
      rather than hovered and "Today 14:07" does not fit. What the same look found
      is a bug rather than a nicety: `relTime()` was also used for a *future*
      timestamp — the Inbox lease expiry — and returned "now" for anything ahead of
      us, so a lease with 40 minutes left read as already up. It says `in 40m`
      now. Measured on the 246 rows rendered in the browser at the time of writing:
      123 labels changed to a date, the longest new form measures 52.8 px against
      its 64 px cell (identical to the old `412d ago`), and the old and new
      functions disagree on exactly those rows — the check that this changed
      anything is the diff, not the build passing.
    - **A hold is not a queue.** While the pause is on, the list is exactly as
      stale as it was when focus arrived. The badge says 自动更新已暂停 rather than
      keeping its live dot, but nothing yet shows *how* stale: the age label only
      updates when a refresh actually lands.
    - **Fuzzy matching is substring-only**, so the highlight component shows a
      contiguous run; the character-subsequence highlight the research describes
      would need the matcher to report which characters it used.

36. **The hidden-row chip counts by a rule that is a title, not a fact.** Spec
    Round 54 made the cockpit's silent drops countable: `hidden_sessions()`
    receipts, the server shipping them with `hidden_reason`, and a chip that says
    126 on this machine (93 `qodercn-ide`, 14 `qoder-ide`, 19 `codebuddy`) and
    reveals them on click. Three things are still true:

    - **The rule is `title == "工具循环会话（无用户消息）"`.** A conversation whose
      title happens to be exactly that string would be dropped from the list. It
      would then also appear on the receipt, so it is countable and revealable
      rather than gone — but the rule should ask whether the transcript holds a
      user turn, not what its label says. No such session exists on this machine:
      the audit classifies all 126 as `EMPTY`, and every one of those 126 lines
      reads `0 msgs, none a user turn`.
    - **The number is not the number of rows that appear.** Revealing 126 added
      19 rendered rows in grouped mode and left flat mode at its 50-row page
      while 4 revealed rows moved into it, because a group renders 50 at a time.
      The tooltip says so; a reader who expects +126 will think the chip lies.
    - **The census was blind to 19 of them until this round.** The gate that
      asks "is any conversation invisible?" built its id universe from each
      parser's file index, and codebuddy keeps its tool loops outside that index
      — so it reported 107 where the truth is 126. It now reads the receipts and
      fails if any hidden id is neither listed elsewhere nor classified. That is
      the same failure shape as everything else in this file: a check whose
      producer cannot see the thing it names passes green while saying nothing.

37. **Which fragments the list absorbs moves within minutes, without a code
    change.** The absorb rule proves "some real session contains this exact user
    text", searched newest-first under a 60 MB byte budget, so membership depends
    on which carrier files happen to rank inside the budget *right now*. Measured
    on `qodercn-ide`: 2 fragments absorbed at 04:01 and 0 at 04:31, with the
    pre-Round-55 algorithm in the same process agreeing with the new one both
    times — the quest-task transcripts that carry those texts get rewritten, which
    re-ranks them. An exhaustive search with no budget (`r55_truth.py`, all 132
    files, 105 MB) finds 1 carrier for a text the budgeted scan cannot reach, and
    **37** carriers for the fragment whose text is `继续`. Consequences: the row
    count a user sees for one chat is not reproducible from a transcript alone,
    and a common short phrase absorbed against an unrelated session hides a
    conversation whose text is "visible" only in a chat it was never part of.
    The rule should key on where the vendor writes the echo — the same project
    directory measured as the carrier location for every absorbed fragment here —
    rather than on text identity across the store.

38. **The discovery-pass window is opened by one caller.** `base.discovery_pass()`
    freezes a store's file list for its duration, and only
    `server/app.py::_build_session_roots` opens one. Every other path — `handoff
    list`, the evidence and conformance tools, the detail endpoint — walks per
    question exactly as before, which is correct but still costs what it always
    cost. Two rebuilds in one process also each walk once, so a caller that loops
    rebuilds itself pays per rebuild; the pass is a per-window coherence boundary,
    not a cache with a lifetime.

39. **`Needs input` still says nothing for 207 listed rows.** The 745 rows Round 56
    counted without a probe are down to 65: `zcode` (458 rows) and `opencode` (222)
    got their probes in Round 58, and both now answer every row the store lists —
    458/458 and 222/222 agreeing with their own detail page (全量, not sampled).
    What is left, measured on this machine 2026-09-22:
    * **No probe yet** — `dsh` 51 rows, `cherrystudio` 10, `qoderwork-app` 1,
      `qoderwork-cn-app` 2, `kimi` 1. Each is a different read: `dsh` stores zstd
      rolls, so there is no seekable tail and a probe costs a full decompress of
      the newest roll (~5 ms per row cold, which the version memo makes once per
      change); `cherrystudio`'s `session_messages` has no index on the
      conversation key — `EXPLAIN QUERY PLAN` says `SCAN`, so a probe is
      affordable only behind a memo, and the memo's key must carry SQLite's
      change counter (see Round 58's note in the spec); `kimi`'s `wire.jsonl`
      holds no dialogue rows on this machine today, so `unknown` is the honest
      answer even with a probe written.
    * **142 rows inside the JSONL family** — 95 of them `qodercn-ide`, 22
      `qoder-ide`, 22 `codebuddy`, and 3 elsewhere. Not yet split by mechanism,
      and the split matters: item 39's earlier "14 declines" counted *listed*
      rows at the parser, while this number is the list page's own rows, which
      include the `hidden_sessions()` transcripts Round 54 started shipping. A
      tool-loop transcript that ends on its delegated task row is the shape that
      Round 56 measured as unreadable-by-design, so some part of these 142 is
      that, and some may be the 64 KB window. Measure before choosing between a
      second, larger window (1 MB, head file only, memoised by version) and
      nothing at all. Reading every row's whole transcript stays off the table:
      144 MB per rebuild for the rows already answered. Round 56's memo makes
      even that a per-store-change price rather than a per-poll one (measured: 2
      reads, 0.1 MB on a warm rebuild), which is what makes the smaller retry
      affordable at all.
    Round 56's date guard stays: 8 "not waiting" answers silenced, 7 of them ones
    the window had right, and the 8th is that round's only known contradiction
    with a detail page. The same guard was tried on `zcode` in Round 58 and
    **rejected**: it removed 399 answers the detail page agreed with and caught
    none it disagreed with, because a zcode session record is dated by events that
    add no message.

40. **One row per store shape can still be answered wrongly, and only the detail
    page knows.** `load()` sorts a session's messages by their recorded timestamp,
    so "what the reader sees last" is the *newest* turn, not the last row in the
    file or in the store's append order. The probes read the end of their window.
    Measured across 2,485 live JSONL rows: a window's newest turn is its last
    physical turn in every case (0 divergences), so the two definitions agree
    *inside* a window — but the newest turn can sit above the window entirely,
    which is how `codebuddy`'s `5771fa81` produced Round 56's only known
    contradiction. The guard catches that instance; it cannot catch a store that
    both appends out of order and keeps its newest turn beyond 64 KB.
    Round 58 removed one way this could bite silently: `zcode`'s `load()` sorted
    its messages **only when the session ran a sub-agent** (`if agent_msgs:`), so
    one page had two orderings — append order for 441 sessions, chronological for
    17. Measured before the sort was made uniform: 0 of 458 sessions change
    rendering, and no message lacks a timestamp, so the branch was invisible here
    and load-bearing on a store that re-appends a row with an older stamp.
    `scripts/probe_audit.py` is the check that notices either way: it reports 0
    contradictions for either probe today (sampled 40 per store; the two stores
    this round added were checked over all 680 of their rows), and inverting a
    probe on purpose makes it report 37 `needs: lying` and exit 1 — so the 0 is
    reachable-but-not-hit, not unreachable. Two things the gate cannot catch are
    named by that sentence: a wrong turn predicate (it is the probe's own, so its
    tests carry that), and a store whose messages arrive without timestamps, where
    the two definitions coincide again.

## How to check any of this yourself

```bash
handoff doctor                         # what is real on YOUR machine
handoff matrix                         # the support table, derived from the fixtures
handoff watch --cli codex --once       # one budget-ladder check on a live session
handoff ui                             # the cockpit at http://127.0.0.1:8620
python scripts/probe_audit.py          # do the cheap list probes contradict
                                       # the detail page, on your own stores
pip install -e ".[dev,zstd,server]"
pytest                                 # parses every fixture, asserts its shape
python -m agent_handoff.evidence --check      # README/JSON vs the fixtures
python -m agent_handoff.conformance --check   # format fingerprints vs the baseline
```

Four checks need more than a checkout, and are therefore commands a maintainer
runs rather than tests CI runs:

```bash
python scripts/sanitize_fixtures.py --cli <id>   # needs that CLI's live store
python scripts/sweep_row_shapes.py --cli <id>    # same, and exits 1 on a shape
                                                 # no list accounts for
python scripts/audit_hidden_sessions.py          # same: every id the stores name,
                                                 # classified, LOST exits 1
python scripts/audit_component_rules.py          # needs playwright + `npm ci`
python scripts/audit_component_rules.py --app http://127.0.0.1:8620/ \
  --route '#/' --route '#/memory' --focus          # the ring, in both themes
python scripts/audit_component_rules.py --app-only --keys \
  --app http://127.0.0.1:8620                      # the row cursor, with real keys
```

The last of those asks the browser whether each Material rule in `web/src/m3.css`
reaches an element at all. Its absence is what let five families of dead CSS ship
— including a white snackbar on the dark theme — while every static gate was
green, because a rule can read every token it names and still apply to nothing.
`--focus` is the third question: not whether a rule matches, but what a keyboard
user sees when it does. `--keys` is the fourth: whether the keys the strip
advertises move the cursor to the row they claim — asked of the running cockpit,
never of the audit's own gallery, because a mock has no 247-row list to walk off
the end of.

If you close a gap here, delete its entry. This file is done when it is empty.
