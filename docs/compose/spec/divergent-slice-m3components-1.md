---
feature: divergent-slice-m3components-1
status: delivered
updated: 2026-09-11
branch: compose/divergent-slice-m3components-1
commits: 0cb9eb1..HEAD
---

# Divergent Slice M3 Components 1

## Report

**What was built.** `scripts/gen_tokens.py` gained a `component` block: 28
families of per-component anatomy, transcribed from Google's own token files
(androidx material3 v0_14_0) and cross-checked against material-web (design
system v0_192). A value is a *reference*, not a copy — `@shape:`, `@corner:`,
`@role:`, `@type:`, `@elev:`, `@spring:`, `@dur:`, `@ease:` — and `build()`
refuses to run if a reference does not resolve, so renaming a rung of the shape
scale cannot leave a component pointing at nothing. `theme.ts` flattens the block
into 446 `--ah-c-*`
custom properties and hands antd the same numbers through `ConfigProvider`.
`web/src/m3.css` and `web/src/index.css` spend all 446 of them and write no
length, colour or curve of
their own. Also generated, and also `--check`-gated: `web/src/firstpaint.css`, two
declarations that close the screenshot anomaly (below).

**Verification.** `uv run python scripts/gen_tokens.py --check` → `tokens.json
and firstpaint.css match the generator (21 CLI identities)` · `uv run pytest
tests/` → **414 passed, 2 skipped** · `uv run ruff check .` → clean · `evidence
--check` → 21 rows, README and `support-matrix.json` match the fixtures ·
`conformance --check` → 14 CLIs match their baselines · `npx tsc -b` → exit 0 ·
`npm run build` → clean, dist rebuilt and committed.

Browser-measured on the built bundle in headless Chromium (dark unless noted):

| Claim | Measured |
|---|---|
| token consumption, at runtime | injected `446` = referenced `446`, **0** read-but-never-injected, **0** injected-but-never-read |
| rule reachability, at runtime | of 302 rules that read a component token, **247 match an element** in a gallery mounting every antd family and every `.ah-*` class, **0 unverified** — the dot Badge, vertical Divider and `type="link"` Button that used to sit in the "knowingly not mounted" list are mounted now, and so is a disabled variant of every family with disabled tokens. The rest are `:hover`/`:active`/`:disabled`/`:focus-*` or animation-only. Before the review's finding: 34 matched |
| disabled states, gated | `--disabled` checks 18 gallery variants: none fades itself, none takes focus, none answers the pointer. The expected opacity comes from `tokens.json` (`checkbox`/`radio` publish `disabled.opacity: 0.38`; switch, field, segmented and slider publish per-part opacities and must stay at 1). It found a disabled FAB and a disabled filter chip falling through to `button:disabled { opacity: 0.38 }`, which fades container, content and the FAB's elevation together. Mutation proof: renaming both new rules made it report `opacity 0.38, want 1.00` for each |
| device colour scheme | a fresh profile resolves to `auto` and follows the emulated OS scheme (`dark` → primary `#d0bcff`, `light` → `#6750a4`); flipping the OS scheme **while the page is open** re-themes without a reload and without writing a stored key; a stored `dark`/`light` still wins. Browsers expose no wallpaper/accent colour, so this is the whole of "follow the device" on the web |
| custom seed | seed `#006a6a` → light `primary #006a6a` / `surface #f4fbfa`, dark `primary #80d5d4` / `surface #0e1514`, generated at runtime by `@material/material-color-utilities` (`SchemeTonalSpot`, 2021 spec) for all 49 roles plus the cockpit's aliases; survives a reload; composes with `auto` (the OS flip still switches palettes). Lazy: with no stored seed **0** module chunks are fetched, and the library is a 129.7 KB chunk instead of +96.4 KB on the entry. AA gate: refused a seed only under a mutated 10.0 threshold (`light accent/surface-2 = 5.23:1`, seed not stored, palette unchanged) — every real seed tried passes at 5.23–5.30:1 |
| high-contrast modes | under `forced-colors: active` the mode drops every `box-shadow` (measured: `sh: none` on hover and press), so feedback moves to a system-coloured outline — hover `solid 1px` `CanvasText`, press `solid 2px` `Highlight` inset by 2px, measured on a real pointer. The focus ring survives at `rgb(55, 0, 110) solid 3px @2px`, the tab indicator as a 3px system bar, a selected segment by its forced fill. `prefers-contrast: more` re-points `--ah-line` at `--ah-line-strong` (`#cac4d0` → `#79747e` light, `#49454f` → `#938f99` dark). `--states` repeats under forced colours: five routes × two themes × both modes = **88 controls**, 0 defects. Mutation proof: removing `.ant-btn` from that arm made it report `no visible hover feedback in forced-colors` in both themes |
| the palette's official status | our 49 role→rung mappings and 89 rung colours were compared against copies of `tokens/versions/v0_192/_md-sys-color.scss` and `_md-ref-palette.scss` fetched first-hand: **0 differences in either layer, in either theme** (the only upstream names we do not carry are `black` and `white`). The copies are vendored under `tests/fixtures/m3spec/` with pinned sha256 and Google's Apache-2.0 headers, so the gate runs offline. Mutation proof: both layers were changed on purpose — `primary40` → `#6750a5`, role `primary` → `primary50` — and each was reported by name |
| the other four layers | `tests/test_official_layers.py` does the same for shape, elevation, state and type against five first-hand v0_192 files: corners **12/12**, elevation **6/6** (`0/1/3/6/8/12` dp), state layers **4/4** (`0.08/0.12/0.12/0.16`), type **10/10 shared roles** (size, line, tracking and weight; rem converted at 16px) — every one zero differences. The five official roles we do not carry (`display-large/medium/small`, `headline-large/medium`) are asserted absent *by name*, so adding one is a deliberate edit. Mutation proof: one value per layer (`lg` 16→15, `level2` 3→4, `dragged` 0.16→0.17, `body-small.tracking` 0.4→0.3) and all four tests failed, naming the values — the `lg` change also moved `corner-large-top`, `-start` and `-end`, because those are composed from the scale |
| the dp→shadow recipe | the same gate now covers the one file that was still cited-but-unchecked: MDC-Web's `packages/mdc-elevation/_elevation-theme.scss` (**MIT**, not Apache-2.0 — header kept verbatim). Three maps × our six levels = 18 shadow values, plus the three opacities (`0.2/0.14/0.12`) and the black baseline: **0 differences**. Mutation proof: `penumbra[1]` `0px 1px 1px 0px` → `0px 1px 2px 0px` reported `penumbra at 1dp`; the opacity `0.14 → 0.15` reported `penumbra`. This is the layer where a wrong value is least visible — an `11px` blur instead of `10px` renders, looks like elevation, and is not Google's |
| M3E springs | the third source repository. `ExpressiveMotionTokens.kt` + `StandardMotionTokens.kt` + `MotionScheme.kt` (androidx material3 v0_14_0) are vendored and compared: **12 damping/stiffness pairs, 0 differences**, no key missing or extra, and each scheme impl asserted to reference *only* its own token file (so `standard-*` and `expressive-*` cannot be swapped). Mutation proof: `expressive-fast-spatial.damping` 0.6 → 0.65 and `standard-slow-effects.stiffness` 800 → 900, reported by name with both values. What remains ours is the step after the pair — 24-sample `linear()` easing, settle tolerance 0.001, cubic-bezier fallback — recorded in the deviation register and in `docs/limitations.md` item 23, along with the one layer still without a gate: the 27 component-token families |
| forced colours, second pass | `--focus` and `--disabled` now also run under `forced-colors: active`: **1631 focusable elements** (up from 808) and **72 disabled variants** (up from 36), 0 defects. Two of the first failures were the *check's* own: it dropped the outline style keyword when composing the string (`"3px rgb(...)"` has nothing for the parser to match), and it demanded a composed `on-surface` in a mode whose whole purpose is to replace the ink |
| keyboard focus, swept | `--focus` over **5 routes × 2 themes, 540 nodes** — 98 by synthetic `focus()`, 406 by <kbd>Tab</kbd>, an open dropdown included — **0 defects**: every ring is `3px` of `#625b71` (light) / `#ccc2dc` (dark) at a `2px` offset, choreography timed at `150ms` + `450ms` after a `150ms` delay, **0** elements whose own radius changes on focus, 44 ring-delegated, 26 skipped by the synthetic pass because they have no box and judged by the keyboard pass instead. Before: antd's derived grey on 17 of 49 the old sweep could see, a `border-radius: 4px` rewritten on 4, and a 12% layer that never landed on our own buttons. `rgb(194,189,201)` is the light value; the review measured `rgb(76,70,91)` on a dark menu item, so "the same in both themes" was wrong and is corrected in `docs/theming.md` |
| keyboard focus, swept | `--focus` over **the five list routes plus a session-detail route, both themes, 796 nodes** — synthetic `focus()` and a real <kbd>Tab</kbd> walk, an open dropdown included — **0 defects**: every ring is `3px` of `#625b71` (light) / `#ccc2dc` (dark) at a `2px` offset, choreography timed at `150ms` + `450ms` after a `150ms` delay, **0** elements whose own radius changes on focus, 22 ring-delegated where the focusable node is not the visible box, box-less nodes judged by the keyboard pass, and disabled controls skipped (the pager's inner button on page 1 cannot take focus at all). Before: antd's derived grey on 17 of 49 the old sweep could see, a `border-radius: 4px` rewritten on 4, a 12% layer that never landed on our own buttons, plus — found by widening the sweep — antd's ring on three keyboard-reachable cases the review named and on the session-detail `Pagination` |
| focus under `prefers-reduced-motion` | the pulse is skipped and the ring is not: with motion allowed the element reports two running animations (`150ms`, `450ms` after a `150ms` delay) and `5px` mid-flight; with `reduce` it reports **no** animations and `3px` of `secondary` at a `2px` offset immediately |
| hover, with a real pointer | 5 routes × 2 themes, every button, link, row, tab, chip and select-chip: **0** elements change `background-color` on hover — the 8% layer is the only hover mechanism — and the published press morphs still run (an icon button sampled mid-flight at `47.96px` between its full corner and its pressed corner) |
| hover and press, gated | `--states` puts a real pointer on one representative of every control **family** on each route, both themes: **44 controls**, every one with a token-coloured layer at **8% hover / 12% press**, 0 colour swaps, 0 filters. It found two live defects: every icon button had *no* hover feedback (alpha `0.000` on all ten), and a hovered segment was painted with the selected `secondary-container` — hover wearing the selection colour. Mutation proof: renaming the icon-button hover rule made the gate report `hover layer is 0.000, want 0.08` in both themes |
| control overlap, swept | `--overlap` compares every rendered interactive pair on every route, in both themes, **and on a session-detail route** (the one surface the focus sweep never visited, discovered from `/api/sessions`): **718 controls, 0 pairs overlap**. It exists because a `.zip` button was painting over the 摘要/全文 switch (x 1081–1187 against 1109–1213) and every other gate passed that page. Mutation proof: a negative margin on the second body button made it report `74x40px` of overlap in both themes, and removing it went green again |
| the cockpit's own loading state | the dashboard now paints **187 rows in 2.4s**; before this round it never left its skeleton, and the server behind it was measured burning **115% of one core** with `/api/stores` at 8.7s and `/api/sessions` timing out at 150s |
| the thread view's loading state | it answered in **15.4s** with `{sessions: 802, with_files: 72, budget_hit: true}`, 0.0s from cache, and 15.7s for a *load more* that continued to 85 without re-reading the first 72. Before: still `聚类中…` after **121s**, because the pass called `Parser.load()` for all 802 sessions — measured at 189ms each, ~150s |
| the rendered product, swept | across five routes: **2 font weights, 4 sizes, 7 radii, 15 colours** distinct, **none of them off-token**, and every weight is 400 or 500 |
| the dialog scrim | `rgba(0,0,0,0)` before (a `calc(percent * percent)`, invalid at computed-value time, discarding every candidate); the token alone after |
| top app bar | `64px`, `rgb(33,31,38)`, 16px inline padding; title **22px / 28px / weight 400** (`title-large`, `AppBarSmallTokens.TitleFont`) |
| filled button | `40px`, radius `9999px`, `min-width 64px`, padding `16px`, `14px/20px/500`, `rgb(208,188,255)` on `rgb(56,30,114)`, no shadow; transitions `0.16s, 0.24s, …` from the springs |
| …hovered / pressed | 8% layer; then radius **`8px`** (`ButtonSmallTokens.PressedContainerShape`) + 12% layer + level 0, `transform: none` |
| outlined button | transparent, `rgb(202,196,208)`, radius `9999px`, **no** hover shadow; pressed radius `8px` |
| tonal / elevated button | `rgb(74,68,88)` on `rgb(232,222,248)`; `surface-container-low rgb(29,27,32)` in primary ink with the level-1 recipe |
| list row | rest `4px` → hover `12px` + 8% layer → pressed `16px` + 12% layer, `transform: none` (was `scale(0.97)`) |
| segmented | `40px`, `9999px`, 1px `rgb(147,143,153)`; selected `rgb(74,68,88)` on `rgb(232,222,248)` |
| switch | `52×32`, 2px outline, handle `16px` off / **`24px`** on at `inset-inline-start: 20px`; checked track `rgb(208,188,255)` |
| chip | off `32px`/`12px`/1px `outline-variant`/8px block margin (the 48px touch target); on `9999px`, 0 border, `secondary-container`, checkmark `display: flex` |
| linear progress | track `4px` `secondary-container`, `padding-inline-end: 8px` (4 gap + 4 stop), fill `4px` `primary` on the 320ms spring, stop indicator **4×4** `primary` |
| text field | `56px`, `4px 4px 0px 0px`, `surface-container-highest`; indicator 1px `on-surface-variant`; input 16/24 |
| tooltip | `inverse-surface` on `inverse-on-surface`, 4px corner, body-small — verified in **both** themes |
| FAB / icon button | `56×56` `corner-large` on `primary-container` with the level-3 recipe / `40×40` `corner-full` |
| first paint | **0/8** white cold captures, 8/8 at the exact `rgb(20,18,24)` (was 7/8 white) |
| narrow widths | six widths (1600/1280/1100/900/760/430px): document scroll width == viewport at every one, **0** header controls whose own centre hit-tests to something else, **0** outside the viewport, title stays 22px and the bar wraps 69 → 115 → 161px |
| content overflow, every route | **5 routes × 7 widths (1600→430px) = 35 combinations, 0 offenders**: no element is wider than the page unless it is inside its own scroller, which is what the scroller is for. The check has a positive control — an injected 2000px element is reported — because a sweep that cannot fail is not evidence |

The width check is a **hit test**, not a bounding-box intersection, and the first
version of it was wrong: it reported two overlaps at 900px that were a tab
scrolled out of the tab row's `overflow-x: auto` strip — clipped, invisible and
unclickable — and two more at 760/430px that were a `display: none` responsive
label with a zero-area box. Both are now skipped by construction. What the
usability bug this check exists for actually was is the *hit test* going to the
wrong control, so that is what is measured.

**Journey log.** (1) The audit that opened this slice measured the shipped
controls and found antd's anatomy everywhere: a 32px button at `border-radius:
12px`, a switch with a knob, a 3px progress bar with square ends, a list row that
lifted on hover. (2) Google publishes this layer in two places that are not the
same place — androidx has the token files, material-web has the CSS geometry —
so every family is cited to at least one and often cross-checked against the
other. Where they disagree the disagreement is in the deviation register, not
sanded off: the filled field's focus indicator is 3px in material-web's current
field token set and 2px in its own pinned `v0_192` copy, and the list item's
disabled label is 0.38 in androidx and 0.3 in material-web. (3) Three defects were
found by the new gates rather than by reading: the consumption gate caught three
keys written `icon_colour` where the CSS read `icon-color`; the browser probe
caught an outlined antd button painted with the filled container; and the second
probe round caught the filled-container block sitting *after* the tonal and
elevated variants, where all three are (0,1,0) and the later one wins. (4) The
tooltip rule was dead CSS — `.ant-tooltip-inner` is a v5 class and v6 renders
`.ant-tooltip-container` — and it satisfied the consumption gate while applying
to nothing, which is the argument for a browser-side mirror of a static check.
(5) The previous slice's row-lift is corrected: `ListTokens` gives a list item
level 0 at rest and level 4 only while *dragged*, so a hovered row now widens its
corner instead of rising.

**The screenshot anomaly is closed.** §8.7 of the brief recorded a dark theme
whose `getComputedStyle` reports the right colours while `page.screenshot()`
renders light. An independent, read-only probe reproduced it (**7/8** cold
captures white) and localised it: `--ah-surface-0` only exists once the JS bundle
runs, so between `commit` and `theme.ts` — a window measured at **44–99 ms** —
`body { background: var(--ah-surface-0) }` is a guaranteed-invalid substitution,
the page has *no canvas paint at all*, and the capture is composited onto the
compositor's base colour. The DOM read that reported dark values happened one
round-trip after the capture. Background propagation, `color-scheme`, stylesheet
order, a stale frame and "an element painted over the DOM" were each falsified by
measurement. The fix is two generated declarations; after it, **0/8** white.

**The rounds after the review, and why they were needed.** The first delivery
tokenised every control and the verdict came back "not Google's level". That was
right, and it produced six more rounds, each driven by a measurement rather than
by a look:

1. **The page, not just its controls.** Four surfaces had no M3 structure at all:
   navigation was a full-width antd `Segmented` (now `PrimaryNavigationTabTokens`),
   search was `Input.Search` (now `SearchBarTokens`, 56dp corner-full), 118 rows
   were bordered cards (now `ListTokens` items with no border), and the filter
   controls were two `Select`s and a `Button` (now `FilterChipTokens` over a
   `MenuTokens` dropdown, on a `DockedToolbarTokens` strip).
2. **A computed-value sweep**, which found what no source scan can: `th` at
   `font-weight: 600` (M3 publishes no 600 — antd's rule, antd's stylesheet), a
   status tag at **3.37:1** in the light theme while the same tag passed dark, and
   a spinner drawn in `rgb(180,163,220)`, a colour in no token anywhere. All
   three fixed; the sweep is now part of the audit tool.
3. **Four identical pills became one icon button and a menu.** Theme and language
   are settings, not filters.
4. **The loading indicator was a static dot.** It rotated a circle, which is a
   no-op; it now morphs its corner four times per revolution — measured, 28
   distinct radii in 1.2s.
5. **The empty state was the vendor's.** A 184×152 SVG at a fixed 140px with a
   `<title>` in the library's words, announcing the state a second time to a
   screen reader. Ours is a 48dp mark; replacing it exposed a *second* empty
   state underneath, which `List` had been drawing all along.
6. **The tab indicator now travels** rather than popping, on the spatial spring,
   with 7 measured intermediate positions between the first tab and the last.
7. **The focus indicator was ours, and it lost to antd's.** "Google-official
   level" is decided by the keyboard, and that is where the sheet was weakest:
   the ring was 2px of `primary` where material-web publishes 3px of `secondary`
   with a grow/settle choreography, and on 17 of the 49 focusable elements the
   old sweep could see, antd's `--ant-color-primary-border` won the cascade
   outright — the same `rgb(194,189,201)` in both themes, equal to no token. Two
   more defects were sitting in the same rule: a `border-radius: 4px` that
   rewrote the geometry of whatever took focus, and a 12% layer that never landed
   on our own buttons because `.ah-btn, :root .ant-btn.ant-btn` (0,2,0) beat
   `:focus-visible` (0,1,0) to `box-shadow`. `focusRing` is now a token family
   cited to material-web's `tokens/_md-comp-focus-ring.scss` and
   `focus/internal/_focus-ring.scss` (androidx publishes no focus-indicator token
   file — 120 files listed, none matching `Focus|Indicator`), the selector arms
   match antd's specificity, and the check is
   `scripts/audit_component_rules.py --focus`. 98 elements, both themes, 0
   defects; then made to fail for real by pointing the ring at `primary`, which
   it reported as `rgb(103,80,164)` against `rgb(98,91,113)`.
   The independent review then falsified "everywhere, and the only one on screen"
   in three keyboard-reachable places (a dropdown item, a segmented control whose
   focus node is a 0×0 invisible input, and a slider handle with a second
   indicator on its `::after`), and corrected two disclosures. All three are
   fixed, the gate grew a keyboard channel and an overlay pass so it can see
   them, and each was re-introduced on purpose to watch it fail. The round ends
   at 540 nodes examined and 0 defects.
8. **The cockpit could not load, and nothing in the repo was looking.** Opening
   the built product on this machine showed ten skeletons and never a row — for
   minutes. The server was at **115% of one core** with `/api/stores` taking
   8.7s and `/api/sessions` timing out at 150s, while an in-process build of the
   same call was 5.7s. Two defects, both measured: every request that arrived
   while a build was in flight started *its own* build (a 30s poll per tab is
   enough to pile them up until the thread pool is saturated), and 2.03s of each
   build was two `git` processes per session cwd. Fixed with one build per key
   plus a stale-while-revalidate answer, and with the branch read off
   `.git/HEAD` (2.03s → 0.01s, 53 of 53 cwds agreeing with `git`, one of them
   caught disagreeing first because a *relative* cwd was walking into this
   worktree). After: cold 3.1s, cached 0.01s, six concurrent requests after
   expiry = one 3.64s rebuild and five answers in 0.11–0.13s, dashboard paints
   187 rows in 2.4s. The same round added the gate that would have found the
   other visible defect of this session: `--overlap`, which compares every pair
   of rendered controls and reported the `.zip` button painted over the
   摘要/全文 switch in the session rail (670 controls examined, 0 pairs after the
   fix, `74x40px` under a deliberate mutation).
9. **Two more views answered a spinner instead of a number.** The dashboard was
   not the only one: the thread view sat on `聚类中…` for **121 measured seconds**
   because it calls `Parser.load()` for every session to learn which files it
   touched — measured at 189ms each over 802 sessions, ~150s, and the largest
   single record at 4.6s. The pass now runs under a 15s budget, newest first,
   caches each session's file set (keyed by `updated_at`), and reports what it
   covered: `文件重叠信号覆盖 72/802 个会话（本次 15.4s，已达时间预算）`, with a
   *load more* action that continues from the cache (85 after one refresh, no
   re-reads). The rest clusters on lineage and title tokens. The in-memory cache
   and the ~10 minutes of repeated passes needed to cover a 802-session store are
   in `docs/limitations.md` item 16, with the disk-backed cache named as the
   follow-up.
10. **The pointer states were only weakly verified, and that is where two more
    defects were living.** The previous round's hover evidence was a substring
    test over a probe that finished only the element's own animations, so it
    could not see a layer on `::before` and never asked whether the *opacity* was
    the published one. `--states` asks four questions per control (layer present,
    opacity 8%/12%, colour in the token table, no colour swap and no filter) with
    a real pointer, a settled transition and a family-based sample. It found:
    every icon button answered the pointer with **nothing** (alpha `0.000` on all
    ten — the family spent its layer colour on `:active` only), and a **hovered
    segment was painted with the selected `secondary-container`**, i.e. hover that
    looks like selection. Both fixed, both re-verified, and the icon-button rule
    was renamed afterwards to watch the gate fail with
    `hover layer is 0.000, want 0.08` in both themes. The sweep's sample size and
    its remaining blind spots are in `docs/limitations.md` item 17.
11. **Disabled states, and three families nobody had mounted.** The last
    interaction state without a gate was disabled, and it lived in a place the
    audit could not see: the gallery had no disabled variants and the whole
    running product has two disabled controls. Eighteen variants later (one per
    family the token file describes) the check found a disabled **FAB** and a
    disabled **filter chip** falling through to the global
    `button:disabled { opacity: 0.38 }` — a blanket fade that takes the container,
    the content and the FAB's elevation shadow together, where the tokens publish
    a 0.12 container and a 0.38 content. The expectation is read from
    `tokens.json` rather than asserted in the tool, because checkbox and radio
    publish a whole-element `disabled.opacity` and the other families publish
    parts. Mounting the disabled variants also forced the three remaining
    unmounted families into the gallery — a dot Badge, a vertical Divider and a
    link Button — so the reachability audit now reports **247/302 rules matched
    and 0 unverified**, against 235/301 and 3 before. Two probe bugs surfaced with
    them: a baseline read before the entry animation settled, and a `.ah-select-chip`
    click that landed on a newly-mounted *disabled* select and turned a live rule
    into a phantom dead one.
12. **Following the device, and a colour of your own.** Two questions from the
    reader, both answered with measurements rather than assurances. *Device*: the
    platform exposes `prefers-color-scheme` and nothing else — no wallpaper, no
    system accent — and the `auto` mode already followed it, including a live flip
    while the page is open (`dark` → `#d0bcff`, `light` → `#6750a4`, no stored key
    written). *Custom*: a seed in the header menu now derives all 49 roles at
    runtime through Google's own `@material/material-color-utilities`
    (`SchemeTonalSpot`, 2021 spec), aliases included, with `ok`/`warn`, the CLI
    identity inks and every length deliberately untouched. The library is behind a
    dynamic import because eager loading cost **+96.4 KB** on the entry chunk
    (measured), and a probe confirms **zero** module chunks are fetched without a
    seed. A seed is held to the same 4.5:1 gate as the hand-authored palette; ten
    seeds all pass (5.23–5.30:1, because tones are pinned), so the reject path was
    proven by mutation instead — raising the threshold to 10.0 made the menu warn,
    refuse to store the seed and keep the baseline palette. Both limits are in
    `docs/limitations.md` item 19.
13. **The device's other two requests.** Light/dark is not the only signal a
    platform sends. Under `forced-colors: active` every state layer vanished —
    the mode forces `box-shadow: none`, measured on a real pointer — so hover and
    press became "nothing happens". Feedback now moves to a system-coloured
    outline (`CanvasText` on hover, `Highlight` on press), while the focus ring
    (`rgb(55, 0, 110) solid 3px @2px`), the tab indicator and the selected segment
    were each measured to survive as system colours. `prefers-contrast: more` had
    no effect at all before this round; it now re-points the separator token at the
    published rung above it. Both arms are checked, not asserted: `--states` runs a
    second pass under forced colours (88 controls across both modes) and a mutation — dropping
    `.ant-btn` from the arm — made it report `no visible hover feedback in
    forced-colors` in both themes. That mutation also caught a bug in the check
    itself: `"rgb(0, 0, 0) none 3px".split(" ")[1]` is `"0,"`, so the first version
    read every invisible outline as visible.
14. **Where the colours actually come from.** The palette has claimed to be the
    published M3 baseline since the first colour commit, and that claim had never
    been checked against Google's own file — only against values a human had
    transcribed. It is now two comparisons, both first-hand: our role→rung map
    against `_md-sys-color.scss`'s `values-light()`/`values-dark()`, and our rung
    colours against `_md-ref-palette.scss`. Both are **0 differences** in both
    themes, the two upstream utility entries (`black`, `white`) excepted. The
    copies are vendored with pinned sha256 so the gate runs offline, and both
    layers were mutated afterwards — a rung colour and a role's rung — to watch it
    report the change by name. Forced colours also stopped being a claim: `--focus`
    and `--disabled` repeat under it (1631 elements, 72 variants), and the two
    failures that showed up first were in the checks rather than the app.
15. **The same treatment for the four layers that are not colours.** Shape,
    elevation, state and type had the same weakness the palette had: values
    transcribed by a human, cited in comments, and never compared against the
    file they came from. All five official v0_192 files are now vendored with
    pinned hashes and compared value by value — corners 12/12, elevation 6/6,
    state 4/4, type 10/10 shared roles, zero differences in each. Two conventions
    had to be handled rather than assumed: the official typescale publishes sizes
    and tracking in rem, and the composed corners are four-value lists where the
    generator keeps named tuples. One absence is deliberate and asserted by name:
    the five display/headline roles the cockpit does not use. Each layer was
    mutated afterwards to watch the gate name the change.
16. **The last cited-but-unchecked value in the design system.** Elevation had a
    level gate but not a *recipe* gate: the dp→box-shadow step came from MDC-Web's
    `packages/mdc-elevation/_elevation-theme.scss` and was cited in a comment only.
    It is now vendored (the one MIT fixture — material-web is Apache-2.0, and the
    tests assert both headers so a re-vendor cannot quietly lose the distinction)
    and compared value by value: three maps × six levels, three opacities and the
    black baseline, **0 differences**. Mutated in both directions afterwards — a
    penumbra offset and a penumbra opacity — and reported as `penumbra at 1dp` and
    `penumbra`. With that, every number the generator takes from Google is
    compared against a first-hand file rather than against a comment.
17. **The springs, and the one layer that is still ours.** M3E's motion is
    published in androidx rather than material-web, and it had the same
    citation-only status: twelve damping/stiffness pairs, transcribed. They are
    now vendored (`ExpressiveMotionTokens.kt`, `StandardMotionTokens.kt`,
    `MotionScheme.kt`, all Apache-2.0 with the `v0_14_0` banner asserted) and
    compared: **12/12, 0 differences**, with the extra structural check that
    `MotionScheme`'s standard impl references only the standard file and its
    expressive impl only the expressive one. Mutated both a damping and a
    stiffness afterwards and the test named both keys with their values. The
    honest remainder is written down rather than glossed: everything after the
    pair — the 24-sample `linear()`, the 0.001 settle tolerance, the bezier
    fallback — is this repo's conversion, because M3E is not a CSS system; and the
    **27 component-token families** still have citations and a one-off manual
    review but no repeatable gate, which is the next layer to build.

Each round is in `docs/theming.md` with its evidence, and the ones that cost
something are in the deviation register rather than in a commit message.

**Disclosures.** No screenshot of a real dialogue exists in this slice's
evidence: the stores on this machine carry sessions but no transcripts, so the
message-transcript roles were re-measured only by token and by gate. The
`progress`, `chip`, `text field`, `FAB` and `icon button` families are measured
from instances constructed in the page with the app's own classes and stylesheet,
because no view in the cockpit currently mounts them — the *rule* is under test,
not a call site, and the harness is removed immediately after measurement. One
browser only (chrome-headless-shell 153.0.8010.12, driven by Playwright 1.62 with
an explicit `executable_path`, since the wheel's expected rev 1234 is absent).
**Nothing on this branch has run on a GitHub runner** — the workflow triggers on
`pull_request` or on `push` to `main`, and this branch has no pull request.

**Independent verification (round 7).** A read-only reviewer was pointed at the
focus work and told to falsify it. Its verdict: **partly falsified.** It confirmed
the six token values against files it fetched itself (five first-hand; the
`easing-emphasized` curve line was truncated in its fetch, so it says so), and it
confirmed the ring on 108 nodes walked with <kbd>Tab</kbd> — and then broke the
claim "everywhere, and the only one on screen" three times:

1. **A dropdown menu item.** Reached by keyboard (Tab to an icon button, Enter,
   Tab), its ring was antd's: `rgb(194,189,201)` at offset 1px in light,
   `rgb(76,70,91)` in dark, with zero pixels of `secondary` in either. The rule
   is `.ant-dropdown .ant-dropdown-menu .ant-dropdown-menu-item:focus-visible` —
   (0,4,0), because `:where()` only removes the hash class from the count.
2. **A segmented control.** Focus lands on `.ant-segmented-item-input`, which is
   **0×0 with `opacity: 0`**: our ring computed on it and was invisible, and the
   visible 52×38 item carried antd's grey. Worse for the gate, antd only adds
   `ant-segmented-item-focused` for a *real* key focus, so a sweep built on
   `element.focus()` passes it.
3. **The slider handle** showed two indicators at once — ours round, antd's
   square (`outline: 6px solid`, `box-shadow: 0 0 0 2.5px`, both derived) on the
   handle's `::after`, which nothing that reads only the element's own `outline`
   can see.

It also falsified two of the author's disclosures, and both corrections are in
`docs/theming.md`: the ring's corner is **not** 2px tighter than the published
geometry (Chromium grows an outline's radius by its offset; re-measured here as
`IoU` **0.9985**, 15 differing pixels against material-web's sibling-element
structure), and the 12% focus layer is **not** missing on every pointer click (a
text input matches `:focus-visible` on a click by itself).

All three defects are fixed, all three are covered by the gate above, and each
was re-introduced on purpose afterwards to watch the gate fail: renaming the
segmented arm produced `ring is 3px rgb(194,189,201) at 1px` in light and
`rgb(76,70,91)` in dark; renaming the menu arm did the same on the menu items;
removing the slider rule produced `a second focus indicator is painted by
::after outline`.

**Independent verification (rounds 1–6).** The first review subagent was orphaned
by a process restart and produced **no result** — it verified nothing. The second
ran to completion and is recorded here in full, because it found more than the
author did.

*What it confirmed by its own measurement, not by reading our files:* the
consumption arithmetic (375 = 375 read from the live injected `<style>` and the
CSSOM, on all five views); the token numbers family by family against 53 files it
fetched itself — buttons, icon buttons, FABs, chips, list items, text fields,
switch, checkbox, radio, segmented, dialog, scrim, progress, tooltip, badge,
divider, snackbar, app bar, navigation, slider — with every value matching but
one; the row morph (`4px` → `12px` + 8% → `16px` + 12%, `transform: none`); the
button morph (after a warm-up click, because a fresh page's *first* synthetic
`mousedown` does not set `:active` — its first two attempts were invalid and it
said so); `firstpaint.css` in six OS × stored-theme combinations, with the
media-query branch and the in-app theme switch; and that `--check` fails when one
hex in that file is mutated.

*What it falsified, and what changed because of it.*

1. **The token-consumption gate is necessary and not sufficient.** A rule can
   read every token it names and apply to nothing. `.ant-tooltip-inner` was a v5
   name; v6 renders `.ant-tooltip-container`. Four more of the same shape existed
   (`.ant-modal-content`, `.ant-progress-bg`/`-inner`, `.ant-checkbox-inner`,
   `.ant-radio-inner`, `.ant-message-notice-content`) and **one was live: the
   snackbar rendered as a white box with black text over the dark surface**,
   because v6's `message` is `.ant-message-notice`. All five are retargeted
   against antd's real markup, and the check that finds this class of defect is
   now written down: a gallery outside the repo that mounts every antd family
   *and* every `.ah-*` class against this worktree's own theme and stylesheet,
   and a probe that asks of every `--ah-c-*`-reading rule whether it matches an
   element. 152 of 222 match; the 70 that do not are state, animation-only, or a
   component the gallery does not mount. The tooltip is re-measured as
   `inverse-surface` on `inverse-on-surface`, 4px corner, body-small, in both
   themes.
2. **The dialog scrim computed to nothing.** `calc(var(--…-opacity) * 100%)` is
   percentage × percentage — not a valid calc type — so the declaration was
   invalid at computed-value time and the mask painted `rgba(0,0,0,0)`. The
   number was Google's; the CSS that spent it was not. Fixed to the token alone,
   and the deviation register now records why a fallback declaration would not
   have helped.
3. **The 80dp FAB's corner is not Google's.** `FabMediumTokens.kt` has
   `ContainerShape` commented out behind a TODO, and no published token set gives
   `corner-large-increased` a dp value. 16px is our inference and is now marked
   `shapeOurs` in `tokens.json`, asserted by the test, and in the register.
4. **Two of the three literal gates were enforcing less than they said.**
   Mutation showed `13PX`, `13vh`, `13pt`, `gold`, `White` and `rebeccapurple`
   all passing. The scanners are now case-insensitive, carry CSS's full length
   unit set, and match against the complete named-colour keyword set rather than
   six words — with every one of those mutations added to the positive control.
5. **`"no property with two owners"` was false**, and the documented
   `size="large"` → 56px mapping had never worked, because `:root .ant-btn.ant-btn`
   outranks antd's own `.ant-btn-lg`. The rule now exists and the claim in
   `docs/theming.md` is rewritten to what is actually checkable.
6. **A boolean token leaf** made the Python test and `theme.ts` disagree
   (`isinstance(True, int)` in Python). The test now skips booleans, and the
   `shapeOurs` marker from (3) exercises that path on every run.
7. **The list-item anatomy was a claim about a stylesheet, not about the
   product.** The heights, the leading icon and the three type roles lived under
   `.ah-li`, which no view emits; the app's rows are `.ah-row`. `.ah-row` now
   takes ListTokens' 16px leading and trailing space and its 12px gap as well as
   the corners — and one `!important` Tailwind class in `Inbox.tsx` was removed,
   because it had been silently holding that row at 12px while every other row
   moved.
8. **Two rules on one pseudo-element, and a minifier that merged them.**
   `:root .ant-checkbox::after` appeared twice — once for CheckboxTokens' 18dp
   icon size, once for the 40px state layer — and the build kept only the last
   declarations, so the icon size vanished from the emitted stylesheet. Both
   *static* gates still passed: the literal/consumption one because the file's
   text names the token, and the probe because it read the file rather than the
   output. The two jobs now belong to two pseudo-elements (`::after` is the tick,
   `::before` the layer), and this is the second defect the browser-side rule
   check caught that nothing else could.

*What it could not verify:* `Modal.confirm`'s inner rules beyond the two the
gallery now mounts, the exit animation's class, any colour but first paint in the
light theme, the 28px pressed switch handle, and any component whose only
instance needs an interaction it did not trigger. Those are named here rather
than folded into the claims above.

### Round 18 鈥?the component layer has a gate, and it found four defects

**Why this round exists.** Round 17 could still say, truthfully, that the 28
component families rested on a `_source` comment and one hand review: every value
in them is *plausible*, so a wrong one renders and looks like Material. This
round gives that layer the same treatment the five system layers already had.

**What was built.** `scripts/fetch_m3spec.py` fetches and re-fetches the corpus
from names URLs (with a mirror fallback); 148 files are vendored under
`tests/fixtures/m3spec/{androidx,materialweb}/` and pinned by sha256 in
`PINS.tsv`. `tests/test_official_components.py` carries an explicit
path 鈫?(file, member) mapping and compares **341 values** across all 28 families,
plus three anti-rot rules: every leaf of a Google-cited family must be mapped or
excused by name with a reason, an excuse for a path that no longer exists fails,
and a `None` is checked as a claim about Google's file (the variant with no
container colour must still have no such member). Four disagreements between
Google's own files are pinned on both sides in `CONFLICTS`, so a documented
choice cannot become a description of nothing.

**What the gate found, and what was done about it.**

| Finding | Evidence | Change |
|---|---|---|
| the assist and input chips rested at 8px and morphed to 8px 鈥?a press that changed nothing | `Chip.kt` builds the morphing chip in `Shapes.defaultChipShapes` from `ChipsTokens.UnselectedShape / SelectedShape / PressedShape`; the per-variant `ContainerShape` is only what `AssistChipDefaults.shape` reports | all three variants now rest at corner-medium 12px, press to 8px; `Chip.kt` is vendored and the wiring is asserted |
| an error field painted `on-error-container` where Google says `on-surface` | `_md-comp-filled-text-field.scss`: `error-input-text-color` is `on-surface`; only the label and supporting text turn `error` | `textField.error.content` 鈫?`on-surface`, mapped instead of excused |
| a menu item's type was label-large | `ListTokens.ItemLabelTextFont` is body-large, which is where M3 puts the item's type | `menu.typeRole` 鈫?`body-large` |
| the display-settings menu rendered at antd's 14px/22px and antd's 8px item corner while every token said otherwise | antd's rule is `:where(.css-hash).ant-dropdown .ant-dropdown-menu .ant-dropdown-menu-item` 鈥?(0,3,0) once `:where()` drops the hash 鈥?and its stylesheet is injected after this bundle, so our (0,2,0) arm matched and lost | our arm is (0,4,0); measured `14px/22px` 鈫?`16px/24px` and item corner `8px` 鈫?`4px` |
| Markdown links kept antd's ring 鈥?`rgb(194,189,201)` at a 1px offset, both themes | antd's reset paints `a:focus-visible` at (0,1,1), one class more than the bare `:focus-visible`; the app focus sweep reported 16 defects on one route | `.ah-md a.ah-link:focus-visible` at (0,3,1); the sweep is 0 defects |

The fourth and fifth are the class no token comparison can see: the token was
right and the *pixels* were antd's, because a matching rule has to **win**.
`scripts/audit_component_rules.py --eclipse` is the new gate 鈥?it opens each antd
popup the cockpit mounts and asserts the computed value on the rendered element
equals the token it names.

**Verification.** `gen_tokens.py --check` 鈫?`tokens.json and firstpaint.css match
the generator (21 CLI identities)` 路 `pytest tests/` 鈫?**425 passed, 2 skipped**
(+11 tests) 路 `ruff check .` 鈫?clean 路 `evidence --check` 鈫?21 rows 路
`conformance --check` 鈫?14 CLIs 路 `tsc -b` 鈫?exit 0 路 `npm run build` 鈫?clean,
dist rebuilt and committed.

| Claim | Measured |
|---|---|
| the vendored corpus | 148 files, **148 sha256 rows** in `PINS.tsv`, compared in both directions (changed / added / deleted all fail) |
| the comparison | **341 values** compared, **0 differences**, 28/28 families mapped; `compared >= 150` guards a shrinking table |
| the anti-rot rules can fail | `chip.iconRadius = 3` added without a mapping 鈫?`AssertionError: {'chip.iconRadius': 3}`; a one-byte fixture edit 鈫?the pin test names the file with both hashes 鈥?and the value test names `chip.height` `32.0 鈫?33.0`; the list disabled ink changed to 0.38 鈫?the conflict test says `now says ('num', 0.38), not ('num', 0.3)` |
| the changed values, in the browser | gallery, both themes: chip rest **12px** for all three variants, pressed **8px** (dark `7.997px` mid-morph), selected **9999px**; error field input `rgb(29,27,32)` light / `rgb(230,224,233)` dark (= the theme's `on-surface`), label `rgb(179,38,30)` / `rgb(242,184,181)` (= `error`); app menu item **16px/24px** in both themes |
| the rule-reachability sweep | `249/305` rules match an element, **0 unverified**, 0 dead |
| focus / overlap / states / disabled | **822** focusable elements across 2 themes (ring `#625b71` / `#ccc2dc`, 3px @2px, 16 delegated) 路 **652** controls compared, no overlaps 路 **16** hovered+pressed with a real pointer at 8%/12% 路 **72** disabled variants, none fades, none takes focus |
| the new eclipse gate | **7/7** popup properties equal their token; with the specificity fix reverted it fails and names three (`14.0px` vs `16.0px`, `8.0px` vs `4.0px`, and the ink) |

**What this round did not verify.** The corpus is a snapshot (fetched
2026-09-12); nothing re-fetches it, so the gate proves agreement with these bytes
and not with upstream today 鈥?the same limit as items 21/22 of
`docs/limitations.md`, now recorded there as item 24 along with the two families
the product itself does not mount (`.ah-field`, `.ah-mchip`: measured in the
audit gallery) and the fact that `--eclipse` covers the popups this app mounts
rather than every antd family a future view might add. A composed corner is
compared by name, not by resolving its four radii (those are checked in the shape
layer's own test). Measurement was briefly blocked by the machine's C: volume
reaching 0 bytes free 鈥?node died with a V8 allocation failure mid-build 鈥?so the
browser runs were re-taken with `TEMP` and the npm cache pointed at D:; the
numbers above are from runs that completed after that.

### Round 19 鈥?the eclipse gate covers every antd family the product mounts

Round 18's `--eclipse` sweep read the three popups the cockpit opens. The
mounted families are more than that, so the sweep was extended to the surfaces a
real route draws, and the list is measured rather than guessed: a family
inventory of the running app (five routes, both themes) says the dashboard draws
segmented controls and a Select, the inbox draws switches and the empty state,
the threads view draws the sliders, and the two table views are the doctor's and
the memory export's.

| Claim | Measured |
|---|---|
| coverage | **17 entries** over **5 routes** 鈥?segmented item type and corner, switch track width and corner, slider rail height and ink, table head weight, and the nine popup entries from round 18 | 
| readings per run | **25** (a route-scoped entry is read on its own route, the popups once) 鈥?every one computes the value its token names |
| the gate is not vacuous | an entry whose element never appears is a defect, not a skip (`nothing matched 鈥?on any of the N route(s) swept`), and the run fails if fewer entries were read than exist |
| it can fail | `theme.ts`'s slider `railSize` moved to 8 against a 16px token 鈫?`slider rail height: .ant-slider .ant-slider-rail computes 8px, but --ah-c-slider-track-height is 16px` |

Two findings from writing it. The progress-bar family has **no** eclipse entry:
no view mounts a progress bar (the product shows spinners), so its rules are
gallery-only 鈥?which is exactly what the reachability sweep exists to state, and
adding an entry for it would have produced a permanent false defect. And one
entry cannot be proved by editing our stylesheet at all: the slider rail's height
is painted by antd's `--ant-slider-rail-size`, which `theme.ts` sets from the
same token, so the mutation had to move that number rather than our declaration.
That is the honest description of "who paints this pixel" 鈥?the gate checks the
pixel, not the authorship.

### Round 20 鈥?the app sweep found four more, and the gate learned to locate them

Round 19's `--eclipse` work exposed a gap in the *other* app checks: the
off-token sweep only ever ran on `#/` plus one discovered session, so a defect
that needs a code block, a pager or a table was invisible. This round pointed
the sweep at all five routes plus a chosen session, and — because the machine
was down to 1.3 GB of free RAM (a training job was using 15 GB) — added
`--app-only`, which skips the Vite build and says so in its report instead of
implying the gallery checks passed.

| Finding | Measured before | Fix |
|---|---|---|
| the code-block **copy button was hover-only** (`opacity-0` + `group-hover`), so a keyboard user tabbed to an invisible control with an invisible ring — a WCAG 2.4.7/2.4.11 failure | 8 defect lines across two themes on the session route (`the focused node has no visible box and nothing around it draws the ring`) | `focus:opacity-100` + `group-focus-within/code:opacity-100` + an `aria-label`; the same route is 0 defects |
| the pager kept **antd's link ink**: `rgb(22, 104, 220)` in light (antd's own blue) and `rgb(180, 163, 220)` in dark (its derived primary) | both reported by the off-token sweep, on `a`/`span.anticon`/`svg`/`path` | token rules for items, links, the active item (`secondary-container` + `on-secondary-container`) and the disabled link (38% of on-surface). The **jump** buttons needed a four-class chain: antd paints `.ant-pagination-item-container`, and its `:where()` prefix still leaves three classes |
| Tailwind's `rounded-full` is `calc(infinity * 1px)` in v4, which the browser reports as `33554432px` 鈥?a literal the shape gate cannot see and the radius sweep could not match to any token | 15 occurrences on the 1脳1 bullet | `.ah-round { border-radius: var(--ah-shape-full) }`, used by the bullet and the expert avatar |
| the off-token report said `path.[object` 鈥?true, and useless: the value is inherited from an ancestor's rule | 4 of the 12 rows were unlocatable | the sweep now reports the element **and three ancestors**, which is what identified the jump-button container in one run |

The gate also stopped conflating two different things. A computed value that is
*a token at reduced alpha* (`color-mix(in srgb, <token> N%, transparent)`, the
form every disabled ink and state layer takes) was being reported as "in no
token"; it is now accepted by **un-mixing** it 鈥?the channels have to equal a
token's and the alpha has to say N% 鈥?which is a stronger statement than a list
of selector names. The three things that genuinely are not tokens (the vendored
highlight.js syntax palette, its `code.hljs` ink, and the 45% zebra stripe inside
rendered Markdown) are allowed **by name with a reason**, printed with the run,
and anything that does not match stays a defect.

| Claim | Measured |
|---|---|
| the app-only run | `--focus --eclipse`, 6 routes 脳 2 themes: **2086** focusable elements, 0 ring defects, **27/17** eclipse readings equal to their tokens, **9** values allowed with reasons |
| the full run (gallery included) | 249/**309** rules reach an element with 0 unverified 路 focus **832** elements 0 defects 路 overlap **664** controls 路 states **16** 路 disabled **72** 路 eclipse **25/17** |
| the copy-button fix | the same session route reports 0 focus defects in both themes (it reported 8 before), with the button visible when focused |
| the pager fix | no off-token colour remains on the pager in either theme |
| `--app-only` is honest | the summary prints `gallery skipped (--app-only): rule reachability and the disabled sweep were NOT measured this run` and the JSON carries `gallery_skipped: true`; it cannot be mistaken for a green gallery run |

### Round 21 鈥?the top app bar is the official 64dp where it can be

The shell's own chrome had never been measured against the layout families it
claims. It was: `min-height: 64px` plus Tailwind's `!h-auto !py-2.5 !flex-wrap`,
which rendered **69px** at every width 鈥?a number that is in no token.

| Claim | Measured |
|---|---|
| before | header **69px** at 1440 (padding `10px 16px`, content-driven) |
| after | **64px** at 1440, 1280 and 1200 鈥?exactly `AppBarSmallTokens.ContainerHeight` 鈥?and **65px** at 1024 and 900, where the bar's search field, two Selects and display menu cannot fit on one row |
| the narrow case is a recorded deviation, not a silent one | M3 would put those controls in a *docked toolbar* under the app bar (`DockedToolbarTokens`: 64dp, 16dp leading/trailing, 4鈥?2dp spacing); this cockpit keeps them in the bar and lets it wrap below 1200px. The rule says so in `m3.css`, and `docs/theming.md`'s register carries the row |

The bar's own padding is `16px` (the spacing scale's `lg`) and its title is
title-large, both already token-driven; what was wrong was the height, and the
fix is one declaration plus the removal of two Tailwind overrides.

### Round 22 鈥?the bar is 64dp at every width, and the tabs scroll

Round 21 made the top app bar 64px down to 1200px and recorded a deviation below
that. The deviation was mine, not the layout's: the media query let the bar grow
and the Tailwind `!flex-wrap` let its contents wrap. Both are gone.

| Claim | Measured |
|---|---|
| the bar, six widths | 1440, 1280, 1200, 1024, 800, 600 鈫?**64px each**, `scrollHeight` equal to the rendered height, and `0` children outside the bar |
| what gives way instead | the tab row keeps its own scroll container: at 600px it is 378px visible of 401 scrollable, and at 800px and above everything fits (519px visible of 519) |
| the compact rule | the title truncates (`min-width: 0; overflow: hidden; text-overflow: ellipsis`), which is what M3's compact app bar does; before this rule, 600px put **13** children outside a 64px box |
| the one arrangement deviation that stays | M3 draws a primary tab row as its own 48dp band under the app bar. This cockpit keeps the tabs in the bar row 鈥?a second band would cost 48px of transcript height on every screen 鈥?and `docs/theming.md` records it as an arrangement choice rather than a height one |

One more thing this round found, in the tool rather than the product: a run on a
loaded machine reported `:root .ant-select-item` and
`:root .ant-tooltip .ant-tooltip-container` as **dead rules**. They are not 鈥?a
direct probe of the product in the same minute found both, matching their rules,
with `font-size: 16px` against the menu token and `border-radius: 4px` against
the tooltip token. What happened is that the gallery sweep clicks the Select and
hovers the tooltip to open them; under load both attempts timed out, its
`except: pass` swallowed that, and `reachable()` then called the rules dead. The
sweep now retries each surface twice (three attempts, 4s each), checks for the
popup it was supposed to open, and reports a surface it could not open as
**unverified** 鈥?`the sweep could not open the surface it lives in: a click or
hover timed out, so this run does not know` 鈥?rather than as a defect. The
re-run after the change: `249/309 reach an element; 0 are unverified`.

### Round 23 鈥?the press morph is measured, not asserted

M3E's press feedback is geometry: the corner leaves its resting rung, holds the
pressed one and comes back, on a spatial spring. The stylesheet has said so in
seven places since this slice started, and `--states` has been recording the
radius on every press since it was written 鈥?without ever comparing it to the
token it names. `scripts/audit_component_rules.py --morph` is that comparison.

| Claim | Measured |
|---|---|
| coverage | **8 families** (small, medium and large button, icon button, assist, filter and input chip, list item) 脳 **2 themes** = **16 readings** |
| the corners | at rest, while held (hovered, for a list item) and after release, the computed `border-top-left-radius` equals the token the component names 鈥?`--ah-c-button-sizes-*-shape` / `-shape-pressed`, `--ah-c-icon-button-small-shape(-pressed)`, `--ah-c-chip-variant-*-shape(-pressed)`, `--ah-c-list-item-shape-rest`/`-hover` |
| the curve | the `border-radius` entry of the computed transition carries the **sampled `linear()` of `--ah-ease-fast-spatial`** (its sample values match the token's to 1e-3), and its duration is `--ah-dur-fast-spatial` (`0.24s` == `240ms`) |
| not a vacuous pass | the sweep settles every finite animation before reading, so a value read mid-transition cannot pass; and a family whose selector matches nothing is a defect rather than a skip |
| it can fail | replacing the corner's curve with `ease` in two rules made it report, in both themes: `list item: the corner runs on 'ease', not the --ah-ease-fast-spatial samples [0.0, 0.056, 0.18, 0.325, 0.467, 0.594]` |

Two mistakes in the *check* were found by running it, and both are the kind that
would have made it a false green: reading `transition` as one string compared the
first property (`box-shadow`, on the **effects** curve) against the spatial one,
and splitting a CSS list on commas cut `linear(0 0%, 0.5 50%)` in half 鈥?the
third attempt takes the index of `border-radius` from `transition-property` and
splits at paren depth 0. The computed duration also arrives as `0.24s` where the
token says `240ms`, so the comparison is in seconds.

### Round 24 鈥?the dialog's two springs are read while they run

`DialogTokens` publishes both halves of a dialog's motion 鈥?enter on the
expressive default spatial spring, exit on the fast one 鈥?and the stylesheet has
claimed both since this slice started. The claim is now a measurement, taken at
the one moment each animation exists.

| Claim | Measured (confirm dialog, gallery, both themes) |
|---|---|
| enter | `.ant-modal-container` runs `ah-dialog-in` for **0.44s** with the sampled `linear()` of `--ah-c-dialog-enter-easing` |
| exit | 60ms after the OK button, the same node runs `ah-dialog-out` for **0.36s** with `--ah-c-dialog-exit-easing`'s samples; antd unmounts it at about 240ms, which is why the read happens *inside* the animation rather than after it |
| antd's own zoom is not competing | `.ant-modal` and `.ant-modal-wrap` compute `animation-name: none` in both themes 鈥?the zoom classes are present in the DOM but nothing animates on them |
| it can fail | replacing the exit curve with `ease` made it report, in both themes: `dialog (light): the exit runs on 'ease', not the sampled exitEasing [0.0, 0.075, 0.249, 0.458...]` |

One wording fix came out of that proof: the first version said "the exit curve
could not be read", which sounds like a limitation of the check. It is not 鈥?a
dialog that leaves on `ease` is the defect 鈥?so the message now names the curve
it actually found.

### Round 25 鈥?the snackbar enters on M3 motion, not on antd's curve

The snackbar had our colours, our corner and our elevation, and antd's *motion*:
measured on the gallery, `.ant-message-notice` transitioned `transform`, `inset`,
`clip-path` and `opacity` over `0.2s` on `cubic-bezier(0.645, 0.045, 0.355, 1)`
鈥?antd's own curve, in both themes, with no token anywhere near it. That is the
same "half antd" shape as round 20's menu item, one layer down: the paint was
ours and the movement was not.

`SnackbarTokens.kt` publishes no motion (the vendored file has no
Motion/Duration/Easing entry at all), so there is no official snackbar curve to
adopt. What the sheet spends instead is the **system** token pair that says what
it means 鈥?a surface that arrives and is dismissed:

| Phase | Now | Was |
|---|---|---|
| appear | `--ah-motion-duration-medium2` (300ms) on `--ah-motion-easing-emphasized-decelerate` | antd's `0.2s` on `cubic-bezier(0.645, 0.045, 0.355, 1)` |
| leave | `--ah-motion-duration-short4` (200ms) on `--ah-motion-easing-emphasized-accelerate` | the same antd curve |

All four of antd's properties keep a transition, because `inset` and `clip-path`
are what makes a second snackbar slide into place rather than jump.

| Claim | Measured |
|---|---|
| both phases, both themes | `--morph` raises a message and waits for antd's own dismiss: **appear `0.3s` + `cubic-bezier(0.05, 0.7, 0.1, 1)`, leave `0.2s` + `cubic-bezier(0.3, 0, 0.8, 0.15)`**, in light and dark |
| the gate reads the running phase | the appear phase is read 120ms in; the leave phase is polled for by class (`ant-message-fade-leave`) rather than by guessing antd's timer, and "never observed" is itself a defect |
| it can fail | disabling the appear override made it report, in both themes: `snackbar (light): the appear takes 0.2s, but the token says 300ms` and `the appear runs on 'cubic-bezier(0.645, 0.045, 0.355, 1)', not enterCurve 'cubic-bezier(0.05, 0.7, 0.1, 1)'` |

### Round 26 鈥?the tooltip moves on our keyframes, not on antd's zoom

Same shape as round 25, one component over. The tooltip's paint has been ours
since the slice started; its motion was antd's: hovering the gallery's anchor
put `.ant-tooltip` on `ant-zoom-big-fast-appear` and ran
`css-wgezi7-antZoomBigIn` for **200ms** on
`cubic-bezier(0.08, 0.82, 0.17, 1)`. `PlainTooltipTokens.kt` publishes no motion
either (the vendored file has no Motion/Duration/Easing entry), so there is no
official curve to adopt 鈥?what there is, is a pair of system tokens that says
what a tooltip is: something that arrives promptly and is dismissed sooner.

| Phase | Now | Was |
|---|---|---|
| appear | `ah-tooltip-in` 鈥?`--ah-motion-duration-short4` (200ms) on `--ah-motion-easing-emphasized-decelerate` | `antZoomBigIn`, 200ms on `cubic-bezier(0.08, 0.82, 0.17, 1)` |
| leave | `ah-tooltip-out` 鈥?`--ah-motion-duration-short3` (150ms) on `--ah-motion-easing-emphasized-accelerate` | the same antd curve |

The two keyframes keep antd's shape (a 0.96 scale and a fade) because that part
is not wrong 鈥?the *curve and duration* were. antd's own transform-origin is left
alone so the bubble still grows from the anchor rather than from its middle.

| Claim | Measured (both themes) |
|---|---|
| appear | `ah-tooltip-in`, `0.2s`, `cubic-bezier(0.05, 0.7, 0.1, 1)` |
| leave | `ah-tooltip-out`, `0.15s`, `cubic-bezier(0.3, 0, 0.8, 0.15)` |
| the gate reads each phase while it runs | the appear phase is polled for its class, then the anchor is left and the leave phase polled for `ant-zoom-big-fast-leave`; "never observed" is a defect, so deleting the motion cannot pass |
| it can fail | disabling the appear override reported, in both themes: `tooltip (light): the appear runs 'css-wgezi7-antZoomBigIn' (0.2s 'cubic-bezier(0.08, 0.82, 0.17, 1)'), not ah-tooltip-in on the system tokens` |

### Round 27 — the Codex reader read one file of eight, and eight record types of twenty-three

**Why this round exists.** `scripts/codex_session_stats.py` (added in `9a9bb78`)
asks the store and the reader the same question and prints both answers. On this
machine (2026-09-12) it answers:

```
root: C:\Users\c'zh\.codex\sessions
96 rollout file(s) -> 89 session(s); 1 span more than one file
list_sessions() rows: 89  (one per session); a session read short says so below

session                                files  msgs on disk  read back
01a08bc6-754b-78e1-9a1c-b9ba74f8354f       8           800          1  <- short
```

One session is eight rollout files — `rollout-<ts>-<id>.jsonl` plus seven
`rollout-<ts>-<id>_<continuation>.jsonl` — all carrying the same
`session_meta.payload.id`. The reader returned on the first header match, so 799
of 800 messages were invisible. The same first-match shortcut took `updated_at`
and `source_path` from the *oldest* file, returned one `raw_archive` entry out of
eight, and read `_usage_for` from whichever file it met first.

**The census that followed.** Counting `(record.type, payload.type)` over those 96
files and asking of every one of them "would the official client show this?".
`event_msg` rows *are* the product's own UI notifications and `response_item` rows
are the API items it renders, so a record type with no reader is a record the
cockpit drops in silence:

| Record | Count | Client shows | Decision |
|---|---:|---|---|
| `event_msg/item_completed` | 9907 | the timeline card of every finished item | read — sub-census below |
| `event_msg/token_count` | 9425 | usage | already read |
| `response_item/function_call` | 6058 | a tool card | counted before; now also a transcript row |
| `response_item/function_call_output` | 6047 | the card's body | exit code and slow-call analysis, already |
| `response_item/reasoning` | 4512 | the folded thinking block | **was ignored; now a `[思考]` row** |
| `token_usage_record` | 3489 | usage | the same numbers in a second spelling; read, never alongside `token_count` |
| `response_item/message` | 2891 | the message | already read |
| `response_item/custom_tool_call` | 1918 | a tool card | counted before; now also a transcript row |
| `response_item/custom_tool_call_output` | 1918 | the card's body | **was ignored — the exit code and wall clock of every custom tool call** |
| `turn_context` | 273 | model and permission posture | already read |
| `event_msg/task_started` | 264 | the run header | already read |
| `world_state` | 216 | collaboration state | already read |
| `inter_agent_communication_metadata` | 196 | nothing | ignored, shape recorded: `{"trigger_turn": bool}` and no other key |
| `response_item/agent_message` | 196 | the message | already read |
| `event_msg/task_complete` | 195 | a clean finish | already read |
| `session_meta` | 104 | the session header | already read |
| `response_item/web_search_call` | 101 | the search card | **was ignored; now a `[工具 web_search]` row carrying the queries** |
| `event_msg/thread_settings_applied` | 87 | the model chip | **was ignored; the model and provider of record** |
| `event_msg/thread_goal_updated` | 57 | the goal banner | **was ignored; now a `goal:` note** |
| `event_msg/turn_aborted` | 29 | the interrupted marker | **was ignored; the end state the transcript was guessing at** |
| `compacted` | 23 | the compaction divider | **was ignored; now a `CompactionEvent` with measured pre/post tokens** |
| `response_item/tool_search_call` | 12 | the tool-search card | **was ignored; now a `[工具 tool_search]` row** |
| `response_item/tool_search_output` | 12 | its result | nothing to show: no exit code, no wall clock |

`event_msg/item_completed` is not an item but a *container* of items, so it got its
own census. Five of its thirteen item kinds are duplicates of a record already
read, and the duplication is measured rather than assumed:

| Item | Count | Decision |
|---|---:|---|
| `AgentMessage` | 2942 | duplicate of `response_item/message` + `agent_message`; ignored |
| `CommandExecution` | 2242 | the same command, exit code and duration as the `*_tool_call_output` pair; the pair stays the source |
| `FileChange` | 2234 | the changed paths, each with a unified diff — read into `files_touched` |
| `Reasoning` | 1686 | duplicate: 1645 of 1645 non-empty `raw_content[0]` strings appear verbatim in a `response_item/reasoning` row |
| `UserMessage` | 267 | duplicate of `response_item/message`; ignored |
| `WebSearch` | 246 | its `query` is what the `web_search_call` row shows |
| `SubAgentActivity` | 163 | `started` 69 / `interacted` 71 / `completed` 21 / `interrupted` 2 — the `[子代理]` row |
| `ImageView` | 49 | a path the model actually looked at; read into `files_touched` |
| `CollabAgentToolCall` | 48 | 48 of 48 ids are already a `response_item` call id; ignored |
| `ContextCompaction` | 22 | 0 files carry one without a `compacted` record; the record is the source |
| `McpToolCall` | 5 | 4 of the 4 ids seen are already a `response_item` call id; ignored |
| `Plan` | 2 | a plan document; two rows in the whole store is not a category yet |
| `FunctionCallOutput` | 1 | the item spelling of the output row already read |

**The wiring is the house convention, not a new one.** `[思考]` / `[工具 name]` / `[子代理]` rows are what `dsh`,
`jsonl_family`, `cherrystudio`, `qoderapp` and `zcode` already emit for exactly
these three concepts, and `web/src/views/SessionDetail.tsx` already folds them —
a folded thinking block, a tool card whose body is the arguments, a sub-agent
block that links to the child session. A Codex reasoning row or tool call was
simply never turned into one.

**Measured after the change.** Same commands, same machine, 2026-09-13. The
aggregation is proved on the eight-file session; everything else is the twelve
largest rollouts (which between them hold the `FileChange` and `CommandExecution`
items this round is about), read twice: once by `HEAD:src/.../codex.py` loaded as
a module, once by the worktree parser.

| Claim | Before | After |
|---|---:|---:|
| the eight-file session, read back | 1 of 800 | **4913 turns** (the tool no longer flags it) |
| changed paths absent from `files_touched` | 284 of 284 | **0 of 284** |
| `exit:` / `slow_call` keys the reader reported | 499 | **827** |
| of the 334 failures spelled `Process exited with code N` | 0 read | **328 read** (6 have no output row at all) |
| message rows across those 12 files | 1343 | 13629 |
| — of which thinking rows (`[思考]`) | 0 | 4075 |
| — of which tool cards (`[工具`) | 0 | 7415 |
| — of which sub-agent blocks (`[子代理]`) | 0 | 47 |
| compactions read | 0 | 15 in those files, **23** store-wide |
| end states | `user_pending` × 2 of 12 | 1 `clean`, 1 `cancelled` |

That session now returns **4913** turns against the 800 `message` records on disk,
because the reader also returns the thinking blocks and tool cards the client
shows - rows the store writes as `response_item/reasoning` and `function_call`,
not as messages. `scripts/codex_session_stats.py` compares turns to `message`
records, so it stopped flagging the session as short; the two numbers measure
different things and the tool says so in its own header.

| Claim | Measured (2026-09-13) |
|---|---|
| thinking rows, whole store | **4581** `[思考]` turns over the 100 sessions the reader now lists (the 96-file census above found 4512 `response_item/reasoning` rows, 4456 of them carrying readable text) |
| tool cards, whole store | **8238** `[工具]` turns |
| the exit code that was spelled differently | the desktop build writes `Process exited with code 1`, not `Exit code: 1` — 267 of the eight-file session's 271 failures were invisible for that reason, and a synthetic test pins the second spelling |
| end states, whole store | **7 sessions `cancelled`** (from `turn_aborted`, `reason: interrupted`), 78 `clean`, 9 `user_pending`, 6 `unknown` |
| store facts now visible | 11 sessions carry a `goal:` note, 24 a `provider:`, 18 a `service_tier:`, 19 a `world_state:` |
| what the reader costs | the eight-file session now returns **4913** turns and **7.0 MB** of transcript JSON; the tool-card body is capped at 600 characters |
| the fixture baseline | codex `nonempty_messages` 439 → **558** in `conformance/codex.json`, `config/support-matrix.json` and both READMEs — the gate counts the turns the reader returns, so more of them is a baseline move, not drift |
| fixture selection, codex | `select_files` for six sessions: **24 files / 7,714,469 bytes → 6 files / 3,813,812 bytes**, 0 dropped, `tests/fixtures/**` untouched |

Browser-measured on the built bundle (headless Chromium, the served cockpit):
on the eight-file session the first page mounts **106 tool cards** and **45 folded
thinking blocks**; clicking a thinking header opens `.ah-reasoning-content` with the
model's own words, clicking a tool head expands `.ah-toolcall-args` with the
arguments JSON (▸ 🔧 navigate_to_codex_page · {"threadId": "01a0949d…"}), the
session shows 3 compaction mentions, and the new store-facts list renders
`context_window 950000`. On a session that spawned one, **2 sub-agent blocks**
render with a working child link (▸ 👥 子代理 · completed /root/echo_check … → 01a09918…).
0 page errors in either run. Gates: `pytest tests/` **459 passed, 2 skipped** ·
`ruff check .` clean · `gen_tokens.py --check` · `evidence --check` ·
`conformance --check` 14 CLIs · `npx tsc -b` · `npm run build`.

Dropped on purpose, with the measurement that justifies it: `item_completed`'s
`AgentMessage`/`UserMessage`/`Reasoning`/`CommandExecution`/`CollabAgentToolCall`/
`ContextCompaction`/`McpToolCall`/`Plan` kinds and the `inter_agent_communication_metadata`
row repeat a record already read above, and the round-27 census shows the overlap
item by item rather than assuming it: 4 of 4 `McpToolCall` ids, 48 of 48
`CollabAgentToolCall` ids and 1645 of 1645 `Reasoning` strings are already a row
somewhere else.

### Round 28 — the loader's rhythm, and the rail nobody ever mounted

**Why this round exists.** Round 26 finished the motion work and left two items on
the list: the loading indicator had an anatomy but no gate on its *rhythm*, and the
navigation rail's geometry existed in `m3.css` with nothing mounting it.

| Claim | Evidence |
|---|---|
| the loader's contract is written down | `web/src/m3.css`, the comment above `.ah-loading`: the container turns once per `--ah-motion-duration-extra-long4` on the linear easing, the `::after` shape morphs at a quarter of that period on the standard easing, both forever. `LoadingIndicatorTokens.kt` (vendored, consumed) publishes the anatomy: a 48dp corner-full container in `primary-container` around a 38dp active shape in `on-primary-container` |
| nothing measured that rhythm | the audit's gates were `--focus`, `--overlap`, `--states`, `--disabled`, `--eclipse` and `--morph`; the gallery has mounted `#g-ah-loading` and `#g-ah-loading-u` all along |
| the rail rules are measured, but only against a mock | `grep` for `ah-navrail` / `ah-navbar` over the product's own sources (`web/src`, `m3.css` aside) returns **nothing**; the only elements carrying those classes are the audit's own gallery (`scripts/audit_component_rules.py`, lines 414-429: `#g-ah-navrail-item`, `#g-ah-navrail-indicator`, `#g-ah-navbar`). So the geometry passes a check no user ever sees, and the comment above the rules still calls them "for a future shell that uses them" |
| the tokens that geometry needs are vendored and unconsumed | `tests/fixtures/m3spec/androidx/NavigationRailCollapsedTokens.kt` publishes `ContainerWidth` 96dp, `NarrowContainerWidth` 80dp, `ItemVerticalSpace` 4dp, `TopSpace` 44dp, `ContainerShape` corner-none, `ContainerElevation` level0. `scripts/gen_tokens.py` reads only `NavigationRailBaselineItemTokens.kt` (item height 64, item vertical space 6, leading/trailing 16, icon-label 8, header space 40, 24dp icon, corner-full indicator) |
| the two vendored rail files disagree | baseline says the item's vertical space is **6dp**, collapsed says **4dp**. The generator took the baseline value; the conflict is recorded here rather than silently resolved |

**What was built.** `--loading`, a gate that reads the M3E indicator's two
animations off the Web Animations API *while they run* and samples the shape's
computed `border-radius` half a morph period apart, so a loader that stands still
cannot pass; and a real navigation rail in the shell, built from three vendored
androidx files instead of the two the generator was reading.

| Claim | Measured |
|---|---|
| the loader's rhythm, read while running | `--loading` in both themes, both variants: the container turns in **1000ms** against `--ah-motion-duration-extra-long4` **1000ms**, the `::after` shape morphs in **250ms** (a quarter), both `Infinity` iterations, and the border-radius differs between the two samples in all four readings |
| the gate can fail | on a `%TEMP%` copy whose morph duration was changed to the full turn period, `--loading` exits 1 with `the morph period is 1000ms, not a quarter of the 1000ms turn` for all four readings |
| the 4dp/6dp argument, settled from the sources | both files are official (v0_11_0). `NavigationRailCollapsedTokens.ItemVerticalSpace` is the **4dp** the collapsed rail puts between items, and the upstream implementation agrees: `NavigationRail.kt` on `androidx-main` sets `internal val NavigationRailVerticalPadding = 4.dp` and uses it both as the rail's padding and as `Arrangement.spacedBy(NavigationRailVerticalPadding)`, with `NavigationRailItemWidth = NavigationRailCollapsedTokens.NarrowContainerWidth`. The baseline file's 6dp is `ContainerVerticalSpace` for the baseline item variant this rail does not render |
| a third file the generator was missing | the implementation reads `NavigationRailVerticalItemTokens` for the indicator (`ActiveIndicatorWidth` 56dp, `ActiveIndicatorHeight` 32dp, `IconLabelSpace` 4dp, `LeadingSpace`/`TrailingSpace` 16dp, `LabelTextFont` label-medium). It is now vendored through `scripts/fetch_m3spec.py` and pinned in `PINS.tsv` |
| the rail in the product | at 1440px: **80px** wide (the narrow container), **5** items of **80x56px** with **4px** between them and 4px of rail padding, an indicator of **56x32px** at `corner-full`, labels **12px/16px** (label-medium), the active indicator `rgb(232, 222, 248)` = `secondary-container`, and the top tab strip `display: none` |
| the rail below the breakpoint | at 900px the rail is `display: none` and the tab strip is back; `--rail` fails if the rail renders below 1200px, if the tab strip renders above it, if the two disagree about how many views exist, or if any measured box differs from the token it declares |
| what the gate cost the gallery | the reachability sweep is gallery-only, and the gallery had mounted `.ah-navrail__item` as a bare div with no wrapper, no label and no active variant — so the product's own selectors reached nothing. The gallery now mounts the rail in the shape `App.tsx` renders, and the sweep reports **253/316 rules reach an element, 0 unverified, no dead rules** |

**Three gate defects this round had to fix first**, each found by measurement and
each proven able to fail afterwards:

| Gate | What it was doing | What it does now |
|---|---|---|
| `--overlap` | compared raw `getBoundingClientRect()`s, so a link 9000px down inside a scrolled transcript "overlapped" a 原文 button in a row that was itself scrolled out of view — `12x16px` of a pair nobody can see, on the live zcode session `sess_839f73cd` | intersects every box with its clipping ancestors and skips a control whose visible box is empty. Proof: on the unchanged page it reports **0 pairs over 18 visible controls**, two synthetic controls placed 40px apart are still reported (`40x30px`), and a third clipped 5000px inside an `overflow: hidden` box is not |
| `--states` | clicked its way through the page and left the display-settings Dropdown open; the next sample's cursor landed on `LI.ant-dropdown-menu-item`, so the rail's first item read `hover layer is 0.000` while answering the pointer correctly (verified by hand: `color(srgb 0.11 0.098 0.169 / 0.08)`) | presses Escape before each sample, so every control is measured from a clean page. The same leak explained a second failure it reported in the same run (`ant-btn ... hover swaps bd to #79747e`), which is gone |
| the rail's own state layer | — | the rail item answers the pointer with the layer `NavigationRailColorTokens` publishes (`ItemActive/InactiveHovered` and `-Pressed` are all `on-secondary-container`), composed at 8%/12% on a `::before` shaped like the indicator, plus the system-coloured outline the forced-colours pass needs. `--states` now reads 16 controls with a token-coloured layer at 8%/12% |

**What is still ours.** `ContainerWidth` 96dp and `TopSpace` 44dp are published values
the collapsed rail does not spend (upstream narrows to 80dp and pads 4dp), so they
are carried as the landmark's `max-width` and `scroll-margin-block-start` with that
reason written beside them rather than silently dropped. The rail "turns" nothing:
its only motion is the state layer's 150ms fade, so the table above has no curve to
report. Gates: `pytest tests/` **459 passed, 2 skipped** · `ruff check .` clean ·
`gen_tokens.py --check` · `evidence --check` · `conformance --check` 14 CLIs ·
`npx tsc -b` · `npm run build`. Full audit, exit 0: focus **862** elements with the
ring at 3px/2px in both themes, overlap **112** controls with none hit-testing
another, states **16**, disabled **72**, eclipse **25/17**, morph **16** readings,
loading **4**, rail **2** window sizes.
### Round 29 — the pane frame was 400px because someone typed 400

**Why this round exists.** Round 28 closed the first half of the leftover item
(`loading indicator` rhythm, `navigation rail` heights and arrangement). The other
half was "pane layout, official heights and arrangement", and the measurement that
starts it is what the cockpit's pane frame actually renders:

| Claim | Evidence |
|---|---|
| the pane frame exists, and only `SessionDetail` uses it | `web/src/views/SessionDetail.tsx:551` renders `.ah-shell` with `.ah-main` (the transcript) and `.ah-side` (brief and meta). `grep` for `ah-shell|ah-main|ah-side` finds no other caller |
| both of its numbers were invented | `web/src/index.css`: at `min-width: 1200px` the side column is `minmax(0, 1fr) 400px`, at `min-width: 1700px` it is `460px`; below 1200px the layout stacks. None of 400, 460, 1200 or 1700 is published anywhere |
| so were three other breakpoints | `web/src/index.css`: `max-width: 860px` hides medium chrome, `max-width: 1100px` hides tertiary chrome, `min-width: 1700px` widens the shell. androidx.window's width size classes begin at 600 / 840 / 1200 / 1600 |
| the official numbers were one fetch away | `PaneScaffoldDirective.kt` on `androidx-main` publishes `DefaultPreferredWidth` 360dp, `DefaultPreferredWidthXL` 412dp, `DefaultPreferredHeight` 420dp, and `calculatePaneScaffoldDirective` gives Compact and Medium **1** partition with a 0dp spacer, Expanded **2** with **24dp**, Large and Extra Large up to **3** with 24dp. The bounds it branches on are `WindowSizeClass.kt`'s 600 / 840 / 1200 / 1600dp |
| neither file was vendored | they are now, through `scripts/fetch_m3spec.py` (`_androidx_adaptive_layout`, `_androidx_window_core`), with their sha256 in `PINS.tsv` — the tree is 151 pinned files |

**What was built.** The pane frame moved out of `index.css`'s hand-typed numbers
and into `m3.css` keyed on androidx.window's size classes, spending the three
`pane` tokens; the two other invented breakpoints were aligned to the bounds they
were approximating; and `--pane` measures the frame at three widths.

| Claim | Measured |
|---|---|
| the pane frame at Large | 1440px: **2 columns**, side pane **412px** against a token that declares 412px, partitions **24px** apart, both panes **740px** tall |
| the pane frame at Expanded | 1000px: **2 columns**, side pane **360px** against a token that declares 360px, partitions **24px** apart |
| below Expanded | 700px: **1 column**, the panes stacked, the detail filling the whole content width |
| the invented breakpoints | `max-width: 860px` → **839px**, `max-width: 1100px` → **1199px**, and the `min-width: 1700px` rule is gone: Large and Extra Large share the same pane width and spacer, so there is nothing Extra-Large-specific left to say |
| a gate that finds the next one | `tests/test_official_panes.py`, 5 cases. It parses both vendored files, compares the three published values, asserts the partition counts (Compact and Medium 1, Expanded 2, Large up to 3) and fails on **any** width breakpoint in `m3.css` or `index.css` that is not one of 600 / 840 / 1200 / 1600 (or one below one for `max-width`) |
| it can fail, two ways | a `%TEMP%`-free in-place mutation of `min-width: 840px` → `841px` fails with `m3.css: [841] is not one of androidx.window's width size class bounds [600, 840, 1200, 1600]` **and** `m3.css has no breakpoint at the Expanded bound (840px)`; changing `tokens.json`'s `preferredWidth` 360 → 361 fails with `assert 361 == 360`. Both files were restored byte-for-byte afterwards (`m3.css` and `tokens.json` compare equal to the pre-mutation bytes) |
| what it cost the mapping table | two new `MAPPING` rows (`pane.preferredWidth`, `pane.preferredWidthXL` → `PaneScaffoldDirective.DefaultPreferredWidth`/`XL`) and one excuse by name for the spacer, which is a value inside a `when` branch rather than a member. That needed one parser addition: the token files declare `internal object XTokens`, while the directive declares `class PaneScaffoldDirective` with an unnamed `companion object`, so `_kotlin_class_members` walks class bodies and only adds keys the object walker did not already find |
| the corpus | **151** pinned files (83 androidx, 68 material-web) — the two new ones came through `scripts/fetch_m3spec.py`, not by hand |

**A blind spot the pane work exposed.** Every interaction gate ran at one width
(1400px), so the sheet's compact branch — the one the frame *changes* at 839px —
was measured by nobody, and the single overlap `--overlap` has ever caught (a
`.zip` button over the 摘要/全文 switch) was on a narrow column. All three sweeps
now take two readings per route, **1400x1000 and 700x900**, and a failure line
names which one it came from (`light at 700px #/`).

| Gate | One width | Two widths | Why the second reading is not a duplicate |
|---|---:|---:|---|
| `--overlap` | 112 controls | **216** | the compact pass found 0 pairs on all six routes today (34 / 8 / 9 / 20 / 7 / 18 controls examined), so the size was clean — the reading is there so a regression has somewhere to fail |
| `--states` | 16 controls | **24** | the rail is hidden below 1200px and the tab strip comes back, so the tab's state layer had no reading at any width once the rail existed |
| `--focus` | 851 elements | **~1,230** (1211–1260 across runs) | same reason, and the compact routes expose more focusable nodes than the wide ones: 13–18 rings were delegated to the box the reader sees, against 8 before. The spread is the *store* (rows mount as sessions arrive), not the gate — the session-detail route is picked deterministically now, so the wobble is content, not which surface was measured |

All three are green at both sizes.

**What is still ours.** `preferredHeight` (420dp) is the directive's value for a
*vertical* partition — a tabletop split this web layout does not have — so it is
deliberately not spent and the test reads it out of the vendored file instead. The
pane frame is `SessionDetail`'s: the dashboard stays a single pane at every width,
because its content is a toolbar, a chart and a table rather than a list that a
detail could sit beside. Gates: `pytest tests/` **464 passed, 2 skipped** ·
`ruff check .` clean · `gen_tokens.py --check` · `evidence --check` ·
`conformance --check` 14 CLIs · `npx tsc -b` · `npm run build`. Full audit, exit 0,
now nine gates: focus **862** elements at 3px/2px, overlap **110** controls with
none hit-testing another, states **16** at 8%/12%, disabled **72**, eclipse
**25/17**, morph **16** readings, loading **4**, rail **2** window sizes, panes
**3**.
### Round 30 — the header knew the revision, the task kind and where the page started

**Why this round exists.** Round 27 read the *event stream* and left `session_meta`
alone: the reader took `id`, `session_id`, `cwd`, `originator`, `source` and the
spawn block, and ignored everything else the header publishes. Counting the
header's own fields with a value over this store — **118** `session_meta` rows in
**110** rollout files (**8** files append a second header mid-file) over **103**
threads:

| Field | Rows | What it says | Was |
|---|---:|---|---|
| `git: {branch, commit_hash}` | 118 | `feat/product-v7` ×99, `webgal` ×19 — the revision the session actually ran on | ignored. The cockpit's git chip probes the *live* cwd instead, which is a different fact and moves after the session ends |
| `thread_source` | 118 | `user` 53, `subagent` 64, `agent_created_thread` 1 — the product's own classification | ignored, so Codex sessions had no `task_type` while zcode's had one |
| `history_mode` | 118 | `paginated` on every row | ignored (and harmless on its own: it is the store's storage mode, not a claim about this file) |
| `subagent_history_start_ordinal` | 26 | this transcript **begins at turn N** of the thread it was forked from | ignored, so 26 sub-agent transcripts read as complete conversations |
| `forked_from_id` | 21 | the thread this one was cut from | ignored (`parent_thread_id` covered it — the two agree on 21 of 21 rows) |
| `history_base: {thread_id, end_ordinal_exclusive, end_byte_offset}` | 6 | the previous page of a paginated thread | ignored. It is the chain round 27's aggregation already rebuilds from the filenames |

**What was built.** `_meta_from_header` now maps `thread_source` onto
`SessionMeta.task_type` (`user` says nothing, the other two are what the app groups
child runs by) and falls back to `forked_from_id` for the parent; `_build` reads the
header row for the two facts no later row repeats and writes them as notes, deduped
because a thread with several pages repeats its header.

| Claim | Measured |
|---|---|
| the task kind the store publishes | over the 103 listed sessions: **40** ordinary conversations, **62** `subagent`, **1** `agent_created_thread` — rendered by the session-info card that already showed this field for other CLIs |
| the revision the session ran on | a `git:` note on **103 of 103** sessions (`git:webgal@cd1bc06`), deduped from 118 header rows |
| the transcripts that start mid-history | a `history_start:` note on **28** sessions naming the ordinal and the thread the earlier turns live in. In **26 of 26** cases that thread is in the store, so the missing turns are reachable |
| the fork link | `forked_from_id` is the parent fallback; on this store it equals `parent_thread_id` on 21 of 21 rows, so the cockpit's lineage did not change — the fallback covers a fork whose spawn block is absent |
| tests | 5 new cases in `tests/test_codex_gaps.py` (23 there now): the revision note, the page-start note naming the parent, silence when there is no ordinal, the three `thread_source` mappings, and the fork fallback |
| a defect the browser found on the way | the facts list rendered `sandbox_policy | {'type': 'danger-full-access'}` — a **Python repr** in the UI, because the policy is a nested dict and the parser called `str()` on it. Dicts and lists are now `json.dumps`'d (same bytes, a notation the reader does not have to translate): measured in the same session, `{"type":"danger-full-access"}`, and a test pins it |
| the census after this round | **22 of the 23** `(record.type, payload.type)` kinds on disk have a branch. The two that do not are documented rather than forgotten: `inter_agent_communication_metadata` (`{"trigger_turn": bool}`, no user-visible content) and `response_item/tool_search_output` (the *result* of the tool-search call whose card we already draw) |
| the duplicates, re-measured on the grown store | `McpToolCall` is now 84 rows and `CollabAgentToolCall` 56, so the round-27 "already a `response_item` call id" verdict was re-checked at that size: **84 of 84** and **56 of 56** still match, so ignoring them stays right |
| gates | `pytest tests/` **469 passed, 2 skipped** · `ruff check .` clean · full audit **exit 0** with nine gates (focus 851 elements, overlap 112 controls, states 16, disabled 72, eclipse 25/17, morph 16, loading 4, rail 2 widths, panes 3) |

**The page start is a first-class marker, not just a note.** `RawSession.history_start`
(ordinal, parent, timestamp) is set by the parser; the server inserts a
`role: "history"` marker carrying the ordinal and the parent id; the cockpit renders
it as `⚠ 记录从半途开始 619 · → 019fb863…` and the id is a link. Two decisions worth
recording, both measured:

* **It is placed by position, not by timestamp.** A session on this store has every
  row inside one second, and `sorted(..., key=at)` put the marker at the *newest*
  end (index 1 of 102). By definition the marker precedes the first turn of its own
  page, so the server inserts it at the start of the oldest-first stream: measured
  again, index **101 of 101** — the oldest end.
* **Clicking it works.** Measured: the link navigates to
  `#/session/codex/019fb863-138f-7f01-8f1f-716c90c789ac`, the parent thread the
  earlier 619 turns live in, in the same tab with 0 page errors.

What is still ours: the earlier turns are **linked, not merged**. A reader who wants
them reads them in the parent thread, which is where the store keeps them. Merging
was measured before it was declined: for 8 fork pairs, five counts in the parent
(all rows, item_completed, response_item, user messages, assistant messages) were
taken up to each child's header timestamp and **none** matches the ordinal (the
largest pair: ordinal 619 against 3619 / 502 / 2371 / 2 / 133). The ordinal is the
vendor's own event accounting, which the store does not publish, so a merge would be
guesswork dressed as history.
### Round 31 — the task-kind chip was printing translation keys

**Why this round exists.** Round 30 taught the Codex parser to report
`thread_source` as `SessionMeta.task_type`, which is the field the session list's
kind chip is written for. Checking that the chip actually rendered turned up a
defect that had nothing to do with Codex: `t()` is `dict[lang][key] ?? key`, so a
kind the dictionary does not carry renders as **its own key name**. The dictionary
carried `playground`, `background`, `working`, `craft`, `design` and `coding` — and
nothing else, while the stores on this machine report:

| Kind | Rows | Had a label |
|---|---:|---|
| `subagent_child` (zcode) | **318** | no — would have printed `⬣ kind_subagent_child` |
| `subagent` (codex) | **62** | no |
| `agent_created_thread` (codex) | 1 | no |
| `background` / `playground` / `working` / `craft` / `design` / `coding` (workbuddy) | 110 / 23 / 11 / 7 / 2 / 2 | yes |
| `interactive` (zcode), `quest-task` (qodercn-ide) | 32 / 18 | deliberately unlabelled: the first is an ordinary conversation, the second has its own chip and hint |

**What was built.** Three labels in both languages (`子代理` / `sub-agent`, and
`智能体创建` / `agent-created`), a `hasKey()` export so a caller can tell "no
translation" from "the store's word", and a chip that shows the store's own value
when the dictionary has no entry — a vocabulary the store owns cannot be enumerated
in advance, and printing a key is never the honest fallback.

| Claim | Measured |
|---|---|
| the chip renders | in the served cockpit at 1600px, after expanding the 28 parents that have children: **144** `⬣ 子代理`, **1** `⬣ 智能体创建`, and the workbuddy kinds (45 后台, 23 试玩, 4 手工, 3 工作, 2 编程, 2 设计) — **0** raw `kind_*` strings anywhere in the body |
| the gate | `tests/test_task_kinds.py`, three cases: every kind the parsers write or the fixtures/the measured stores report has a label; every label exists in both languages; the chip checks the dictionary first. Proof it can fail: deleting the Chinese `kind_subagent` line fails with `kind_subagent appears 1 time(s): every label needs zh and en`, and the file was restored byte-for-byte |
| what the gate can and cannot cover | it reads the parsers' literals, the values the shipped fixtures produce (`subagent`, `interactive`) and the list measured on this machine, so a *new* store vocabulary outside those three is caught by the runtime fallback rather than by the test |
| gates | `pytest tests/` **475 passed, 2 skipped** · `ruff check .` clean · `gen_tokens.py --check` · `evidence --check` · `conformance --check` 14 CLIs · `npx tsc -b` · `npm run build` · full audit exit 0 with nine gates (focus 802, overlap 216 across two widths, states 16, disabled 72, eclipse 25/17, morph 16, loading 4, rail 2 widths, panes 3) |
### Round 32 — the list's git chip was about the directory, not the session

**Why this round exists.** Round 30 gave `SessionMeta` the store's own record of
the revision a Codex session ran on (`session_meta.git` = branch + commit hash, on
118 of 118 header rows). The list already had a git chip — fed by a *live* probe of
the session's cwd, cached 30 seconds. Those are two different facts, and on this
machine they disagree:

| Claim | Measured |
|---|---|
| the store and the probe disagree | of the 95 Codex sessions that have both a store git and a list row, **19** ran on a branch the working tree has since left — the rows said `feat/product-v7` for sessions whose header says `webgal` |
| the store has the commit, the probe does not | `session_meta.git` is `{"branch": ..., "commit_hash": ...}` on every row; the live probe reports a branch and a worktree count, i.e. about the directory *today*, not about the session |

**What was built.** `SessionMeta` gained `git_branch` and `git_commit` (also in the
bundle's meta), the Codex parser fills them from the header, and the sessions
endpoint prefers them:

| Surface | Before | After |
|---|---|---|
| the row's `git` | `{branch, worktree_count}` from the live probe, always | `{branch, commit, source: "session"}` when the store records one, otherwise the live probe tagged `source: "cwd"` |
| the chip | `⎇ feat/product-v7` | `⎇ feat/product-v7@b015082`, with a tooltip that says which of the two it is (`gitSession` / `gitLive`) |

Measured on the served cockpit: **95** rows now carry `source: "session"` (the 19
`webgal` sessions among them) and every other CLI keeps `source: "cwd"` — zcode
338, dsh 48, qodercn-ide 19, codebuddy 14, workbuddy 13, opencode 5, qoderwake-cn 2.
In the browser, 84 chips rendered with the session title after expanding the tree,
e.g. `⎇ feat/product-v7@b015082`.

**What is still ours.** The live probe stays, because most stores do not record a
revision and "which branch is this directory on now" is still worth showing — it is
now labelled as the directory's, not the session's. Nothing merges the two: a
session that ran on `webgal` and whose tree is now on `feat/product-v7` shows one
chip, and it is the session's.
### Round 33 — the compaction divider was drawn at the wrong end

**Why this round exists.** Round 30 gave the *history* marker a position instead of
a timestamp, because a session whose rows share one second has nothing for a
timestamp sort to go on. The compaction divider had the same hole, and it is worse:
the divider's whole meaning is *where* it sits — everything before it exists only as
a model summary — and on this store it was being drawn at the newest end of most
sessions that have one.

| Claim | Measured |
|---|---|
| how many sessions have a divider | **14** of the Codex sessions the reader lists |
| how many of those give the sort nothing to work with | **11** put every row inside the same second, and **12** have a divider sharing its timestamp with a turn — one has all 331 rows on the divider's second |
| what that produced | the markers were appended after the turns and sorted with them, so a stable sort over equal keys put them at the newest end: the sample session showed its divider at index **0 of 102** |

**What was built.** `CompactionEvent` gained `after_messages` — how many turns had
been written when the divider appeared — the Codex parser records it, and the
endpoint places those markers by position (largest index first, so earlier
insertions stay valid) instead of sorting them by time. Events without a position
keep the timestamp ordering, which is what the other parsers have always used.

| Claim | Measured |
|---|---|
| the divider sits after its own turns | for the 8-file session: two dividers, `after_messages` **1719** and **3524**; in the served API they sit **1719** and **3525** rows from the oldest end — the second is one further because the first divider is itself a row above it |
| the history marker is still first | inserted at the start of the oldest-first stream after the anchored dividers, so it stays the oldest row |
| tests | the compaction case in `tests/test_codex_gaps.py` now writes two turns before the divider and asserts `after_messages == 2`, so a divider that loses its position fails |
### Round 34 — a failed turn was reported as a clean end

**Why this round exists.** The cockpit's promise is that it tells the next session
how this one actually ended. For Codex the reader only asked whether `task_complete`
existed — any completion meant "clean" — but the record itself carries the store's
own `error`. On this machine (2026-09-13: 110 rollout files, 103 sessions): 218
completions, **40 of them carrying a non-empty error** (a 402 quota death, a 502 from a local gateway, "The supported API model
names are deepseek-flash, deepseek-v4-pro, but you passed gpt-6-astra"), and in
**25 sessions the newest end event is one of those failures**. All 25 were reported
as a clean end (17) or as an unanswered user message (8).

| Claim | Measured |
|---|---|
| completions that carry an error | **40** of 218 |
| sessions whose newest end event is an errored completion | **25** |
| what those 25 sessions reported before | `clean` **17**, `user_pending` **8** |
| what they report now | `error` **25**, each carrying the store's own message text |
| the wall clock the reader dropped | `duration_ms` on 204 completions (176 ms … 10,949,490 ms) |
| how that clock is attributed | the row's `internal_chat_message_metadata_passthrough.turn_id`: **203** of 218 completions match a message row; the rest are dropped, never guessed |
| the client's own collaboration posture | `task_started.collaboration_mode_kind` (default 282, plan 3) becomes a `collaboration_mode:` fact when it is not `default` |

**What was built.** `task_complete.error` is read in both shapes the store writes
(a dict with a `message` beside a `codex_error_info`, or a bare string). The newest
end event decides the kind, and the order is now explicit-record-first: a user
`turn_aborted` still wins, then the store's error, and only then the 95%-of-window
inference — two of the 25 sessions also trip that heuristic and now report the
recorded error instead of our guess. `duration_ms` lands on that turn's own
assistant message as `dur_ms` (the transcript already renders it as `+1.2s`), and a
`failed_turns:<n>` fact counts the failures a session survived.

An error is not the whole story: the instruction that turn died on is still un-run.
The parser fills `pending_user_text` for exactly that case, `summarize` promotes it
to `next_steps[0]`, and the banner, the markdown and the continuation brief now show
pending text for **any** kind, not only `user_pending` — why a session stopped and
what it still owes are two different facts.

| Claim | Measured |
|---|---|
| the store's failure text survives verbatim | the 25 details carry the store's own bytes, e.g. `unexpected status 402 Payment Required: Insufficient Balance, url: https://api.deepseek.com/responses (codex_error_info: other)` |
| the pending instruction still reaches the brief | a synthetic rollout in `tests/test_codex_gaps.py`: kind `error` with a dangling user turn ⇒ `next_steps[0]` starts with `[pending from interrupted session]`; a session that is already `user_pending` does not get the line twice |
| tests | `tests/test_codex_gaps.py` gained 11 cases (dict and bare errors, a later success staying clean, an abort outranking an error, duration attribution and its refusal to overwrite, unmatched turn ids dropped, both notes); suite **486 passed, 2 skipped**, `ruff` clean |

### Round 35 — the reader looked for the wrong key

**Why this round exists.** Round 34 taught the reader to believe the store about
*how* a session ended. The same audit of what the store actually holds found two
fields it was still reading past, and one of them was a whole record type.
`response_item/agent_message` is the parent/child traffic of a multi-agent
thread - `author` `/root/nav_rail` to `recipient` `/root`, with the text under
`content` - and the reader asked those rows for `text`/`message`, which they do
not have. **218 rows across 66 of the 103 sessions** were read into nothing.

| Claim | Measured |
|---|---|
| agent_message rows read past | **218** rows, in **66** of 103 sessions |
| what the reader asked for | `payload.text` / `payload.message`; the rows carry `content` blocks |
| what the rows are | who said what to whom inside one thread (`author` / `recipient`) |
| the other ignored field | `phase` on assistant `response_item/message` rows: **2,226** `commentary`, **172** `final_answer`, 4 absent |
| what the phase picks today | nothing - `summarize` still takes whatever assistant row came last, which is a tool card in **23** sessions and a reasoning block in **1** |

**What was built.** Both `agent_message` branches read `content` through the same
block flattener the message branch already used, with `text`/`message` kept as the
fallback for the older spelling, and a row whose `author` differs from its
`recipient` is emitted with `[多代理 author → recipient]` as its first line. The
transcript renders those rows as their own block - `⇄ 多代理消息 ·
/root/nav_rail → /root`, body verbatim underneath - rather than letting a
bracket marker sit in the prose, and `[多代理` joins the hint prefixes that
per-request billing never settles onto.

`Message` gained `phase`, filled only when the store wrote it. Nothing consumes
it yet: what it should change, and by how much, is measured in
`docs/limitations.md` rather than guessed at here.

| Claim | Measured |
|---|---|
| messages gained on the live store | **+218**, sessions holding them **0 → 66** |
| fixtures | codex non-empty messages **558 → 560** (`conformance --write`, `evidence --write`) |
| tests | `tests/test_codex_agent_message.py`: content blocks, the old spelling, `author == recipient`, all three phase shapes; suite **490 passed, 2 skipped**, `ruff` clean, `scripts/ci_local.py --with-frontend` 10/10 |

### Round 36 — the list page was never given the reader the detail page got

**Why this round exists.** Round 34 taught the detail page to believe the store
about how a session ended. The list page runs a cheaper probe instead -
`peek_status`, because it answers for every session on one screen - and that
probe asked a question with a shape it cannot answer: "do any of this session's
files mention `task_complete` in their first 400 rows". A turn that fails writes
its end event at the *end* of the rollout, past row 400. So on one store, in one
request, the row and the page disagreed about the same session. This is the same
defect Round 34 fixed, one layer up, and it was reported as closed.

| Claim | Measured (2026-09-19, 103 codex sessions) |
|---|---|
| where the two pages disagreed | **45** of 103 (58 agreed) |
| what the list could say | `clean` **88**, nothing **15** - no shape of "failed" existed to report |
| what the detail said about those same sessions | `clean` 62, `error` 27, `cancelled` 7, `unknown` 6, `user_pending` 1 |

**What was built.** The newest rollout's tail decides: its newest end event wins
over any older completion, and the "any completion means clean" rule only answers
when the newest file holds no end event at all, which is the resumed-session case
it was written for.

One tail read was not enough, and the measurement said so before the commit: two
sessions (`019fb930-cd8f…`, `019fb930-9540…`) still reported `clean` on the list
while the detail reported `cancelled`. Both wrote ~540 KB more after their last
`turn_aborted`, so the 64 KB tail held no end event, the fallback fired, and the
head scan answered with a completion 540 KB above it - the probe fell back into
exactly the lie Round 34 removed. The window now quadruples until it holds an end
event or has covered the file: one read for the sessions that end at the last row
they wrote, a few for the two that do not.

| Claim | Measured |
|---|---|
| disagreements left | **45 → 7**, exact agreement **58 → 96** of 103 |
| list distribution now | `clean` **62**, `error` **27**, `cancelled` **7**, nothing **7** - the `clean`/`error`/`cancelled` counts match the detail exactly |
| what the 7 left are | the probe stays silent (`None`) where only a full parse can name a kind: `unknown` 6, `user_pending` 1. Silence, not a wrong claim |
| sessions whose reported state moved | **38** of 103 |
| what the tail read costs | three adjacent A/B pairs, `/api/sessions` cold, `AGENTHANDOFF_PREWARM=0`: **+4.5%, −1.1%, −1.8%** - no regression against the 20% gate. The cold build itself measured 11.3–13.5 s across these runs; that is not comparable to the 5.4 s in `docs/limitations.md` item 7, which was a different day and a different store size |
| how the widened read is locked | `test_end_event_above_a_full_tail_window` fails against a fixed 64 KB window (`clean`) and passes against the widening one (`cancelled`) |
| tests | `tests/test_codex_peek.py`: 8 cases (tail beats an older completion, an abort outranks a success, an event past row 400, an event above a full window, the resumed-session fallback, silence without either); suite **504 passed, 2 skipped**, `ruff check .` clean, `scripts/ci_local.py --with-frontend` 10/10 |
| not run | the nine-rule component audit: this slice touches no `web/` file and no CSS, so there is no rendered rule for it to re-measure |

### Round 37 — the phase was read, kept, and then never used

**Why this round exists.** Round 35 taught the reader to keep `phase` and stopped
there, writing down in `docs/limitations.md` what consuming it *would* change -
**by simulation**, on the fixtures, not on this machine's store. (That entry has
since been closed and deleted, as that file asks you to do; the simulation's
numbers are reproduced below because two of its three were wrong.)

| Claim | Measured (2026-09-19, against `summarize` as of HEAD) |
|---|---|
| `context_notes` differ for | **67** of 103 sessions - the simulation said 67, and was right |
| the "last answer" text differs for | **34** - the simulation said **49**, over-counting by 15 |
| `unfinished` differs for | **2** (`01a094bc-e0f1…`, `019fb90d-d5b3…`) - the simulation said 1 |
| what the 34 actually are | the sessions whose last note *was* a scaffolding row: measured as a set, all 34 overlap and neither side has an extra member, so this is one fact, not two |

**What was built.** `_assistant_conclusions` is the one selector `summarize`
draws conclusions from. It drops the rows the parser itself synthesised -
`[思考]`, `[工具`, `[子代理`, `[多代理` - because those are transcript structure,
not an answer; and when the store stamped any row `phase == final_answer`, those
rows win, because the store is saying which text is the reply. When no row
carries the stamp - an older CLI, or a run that died before the answer - every
remaining assistant row stays in play, so the absence of a field never reads as
the absence of a conclusion.

The two callers want opposite things from it, and say so in their argument.
`context_notes` asks for the conclusion, so it takes final answers first.
`_unfinished` asks what the session was *doing* when it stopped, so it takes the
literal last non-scaffolding row instead: a commentary truncated mid-sentence is
exactly the reply attempt that got cut off, and preferring an older
`final_answer` over it would hide the cut.

| Claim | Measured |
|---|---|
| sessions whose last note was a scaffolding row before | **34**, now **0** with any scaffolding note at all |
| fixtures | untouched - no `conformance --write` / `evidence --write` needed, the byte fingerprints do not change |
| tests | `tests/test_codex_phase.py`: 6 cases (final answer beats commentary, falls back when none exists, a tool card is not a conclusion, `unfinished` reports a truncated commentary and prefers it over an older final answer, no assistant text does not crash); suite **504 passed, 2 skipped**, `ruff check .` clean, `scripts/ci_local.py --with-frontend` 10/10 |
| not run | the nine-rule component audit: no `web/` file and no CSS in either slice of this round pair |

### Round 38 — the Dashboard's "等你回复" filter never saw Codex

**Why this round exists.** The store already answers "does this session end on a
user message nothing replied to": `peek_needs_reply` is that probe, Claude Code
implements it, and the Dashboard counts its `true` rows, gates a filter on them
and lists up to eight titles in the tooltip. `CodexParser` never implemented it,
so it inherited the base stub - which returns *unknown*, honestly - for all
**103** Codex sessions, the single largest store in the list. Every Codex session
was silently excluded from a control whose whole job is "go answer these".

Round 36 and the limitations entry it left behind are corrected here, and the
correction is mine, not a discovery about the store: that round counted 7 sessions
as a residual disagreement, of which one was this missing probe. The other 6 are
not a gap - `peek_status` returning nothing *is* the contract for "unknown"
(`parsers/base.py`, and the server's own row comment says "never faked as clean"),
so counting them as disagreements used a stricter ruler than the product has.

**What was built.** Codex gets the probe. It reads the newest rollout's tail and
answers on the newest real message row, with the filters the full parse applies -
developer and system rows are harness injections, injected context and noise are
not turns - and walks back through a resumed session's older files, because the
newest one can hold nothing but the tail of a tool run.

The first version looked only at `response_item/message` and reported unknown for
**12** sessions whose last recorded turn is an `agent_message` - a parent
dispatching a sub-agent. `_build` pushes those as assistant rows, so the session
had spoken last and is not waiting for anyone; an `agent_message` counts as an
assistant row in the probe too, for the same reason.

| Claim | Measured |
|---|---|
| Codex sessions the probe answers | **0 → 103** of 103, through `/api/sessions` (not in-process) |
| of those, actually waiting on a reply | **13** |
| probe vs full parse, session by session | **103/103** agree that "the newest real message row is a user one" |
| sessions that hinge on the dispatch-row rule | **12** - each answered unknown by the first version |
| what it costs | the probe is 872 ms across 103 sessions (mean 8.5 ms, worst 26.5 ms) - 24% of what parsing those sessions takes. Two adjacent cold-build A/B pairs measured −17.7% then +13.4%, i.e. the cost sits under the noise floor of a 14–17 s build and inside the 20% gate either way |
| what Round 36's "7 left" really was | 1 missing probe (fixed here) + 6 non-gaps (contract says nothing means unknown); the item-30 entry written beside 03b606c is deleted as wrong on both counts |
| tests | `tests/test_codex_peek.py` gained 6 cases (user last ⇒ True, assistant answered ⇒ False, a sub-agent dispatch is the parent having spoken, widening past a full tail window, looking back through a resumed session's files, harness rows are not a turn); suite **510 passed, 2 skipped**, `ruff check .` clean, `scripts/ci_local.py --with-frontend` 10/10 |
| not run | the nine-rule component audit: no `web/` file changed, so there is no rendered rule this moves |

### Round 39 — "clean" was the default value of a field, not a finding

**Why this round exists.** The cockpit's founding promise is that it tells the
next session how this one actually ended. For most of the store it has never done
that: `Interruption.kind` **defaulted to `"clean"`**, and a parser that recorded
nothing about the ending got the strongest claim in the product for free. Of the
3,322 sessions on this machine, **2,710** belong to parsers that never construct
an `Interruption` at all - qoder-ide 2,259, opencode 222, workbuddy 156 and nine
smaller ones. Every one of them reported a normal completion.

This is the defect the rest of this round pair has been chasing, at its source,
and pointed the other way: Round 34 and 36 fixed probes that *invented* a clean
end while the store recorded a failure; the model itself was inventing one when
the store recorded nothing. `parsers/base.py` already states the rule for the
cheap probe - "callers must treat None as unknown, never as clean" - and the
detail page was not held to it.

The store cannot always be blamed: qoder-ide's transcript vocabulary is
`assistant / user / active-leaf / attachment / workspace-directories /
runtime-config / last-prompt / worktree-state / file-history-snapshot / system`,
and a sweep of 60 sessions found **no row of the type end|complete|error|abort|
stop|finish at all**. There is nothing to read. `unknown` is the only answer that
is not invented.

| Claim | Measured (2026-09-19) |
|---|---|
| sessions claiming a clean end with no record behind it | **2,710** of 3,322 |
| stores that can prove an ending at all (their source constructs `Interruption`) | 3 of 16 populated: codex, zcode, dsh |
| qoder-ide end-marker rows, 60 sessions swept | **none** (types above; last row of a file is `active-leaf` 34×, `last-prompt` 25×, `assistant` 1×) |
| bundle kinds after the change, 8-session samples | qoder-ide **8 unknown**; opencode 6 unknown + **2 still `user_pending`** (the positional inference survives); codex **6 clean + 2 error** (proven claims untouched); zcode 1 cancelled + 1 error + 2 user_pending + 4 unknown |

**What was built.** The default is `unknown`, with a detail that says why ("the
store records no end marker, so how this ended is not proven"), and `detected`
no longer conflates "not clean" with "the store proved something" - without that
the flip would have switched off the `user_pending` inference entirely, which is
how it was found: the first run failed 4 tests, and one of the 4 was that
inference, not a stale assertion.

Flipping the default exposed a second bug, which had been invisible only because
the fallback and the claim were the same string: `_finalize_interruption` copies
the parser's record into the bundle **when `raw.interruption.detected`**, so a
store that proved a clean finish had its proof thrown away and replaced by the
default. It keys on "the store said something" now. The two remaining failing
tests were assertions that had encoded the default as evidence; both now supply
the evidence they assume.

Two consequences had to be handled in the UI rather than the model, and the
audit trail for them is this: `StatusTag` chose its colour with a chain of
`kind === "clean" || kind === "completed" ? ... : "ah-err"`, so a word the chain
never heard of - which `unknown` now is - rendered as **a failed session**. The
chain is a `STATUS_TONES` table now, unlisted words fall back to the neutral
tone and are shown as the store's own word, and `it_unknown` was relabelled from
"异常结束"/"abrupt end" (a claim that something went wrong) to "结束状态未记录"/
"end not recorded" - the label that would otherwise have been applied to 2,710
sessions by this very change.

| Claim | Measured |
|---|---|
| word list held as data, checked from both ends | `model.END_STATE_WORDS` (12) ↔ `STATUS_TONES` keys ↔ `it_*` labels in zh and en; 4 new tests fail on drift, on a missing label in either locale, or if the fallback colour ever becomes the error one |
| resume-pack cost of treating an unproven ending as one worth padding | 6 qoder-ide sessions measured against the same sessions forced to proven-clean: **+2,046 chars on average**, 0 for the three short sessions and +2,605 / +3,625 / +6,048 for the long ones (`_RECENT_BUDGET` 6,000 → `_RECENT_BUDGET_DEAD` 10,000) |
| what this does NOT fix | nothing recovers these endings - the CLIs do not write them. See `docs/limitations.md` item 31 |
| gates | suite **515 passed, 2 skipped**, `ruff check .` clean, `scripts/ci_local.py --with-frontend` 10/10 |
| browser audit | all nine rules run against the rebuilt app: **0 rules read component tokens and reach nothing**. Two of its own notes are not passes: the eclipse sweep reached 12 of 17 entries ("the ones it never reached are not evidence"), and the pane rule found no pane frame at 1440 / 1000 / 700 px. `web/` changed here, so the dist in this commit is the built output the audit looked at |

### Round 40 — the probe and the page now ask the same question once

**Why this round exists.** Round 39 stopped the model from claiming an ending it
had no record of. Measuring that change with a corrected ruler - comparing the
probe against the **bundle** the detail page actually renders, where the earlier
audit had compared it against the raw parse - found 23 of 225 sampled rows where
the two disagreed, and that Round 39 had caused some of it.

Three different causes, all fixed here:

**A recorded ending was being hidden.** WorkBuddy keeps `sessions.status` and
CodeBuddy keeps `state.json`. Round 39 made the detail page silent unless a
parser proved something, and neither parser had ever passed its own status
column along - so 156 + 16 sessions had the fact in the store, showed it on the
row, and refused to say it in the handoff. `STORE_END_STATES` now translates the
store's word into an `Interruption` at build time, and it lists terminal words
only: `working` and `idle` describe a live job and `archived` describes the task
board, none of which is an ending, and none of them is allowed to become
"clean".

**The same row read twice, with two standards.** ZCode's `peek_status` asked
`turn_usage` for failure flags and answered **`clean` when none were set**, while
`_interruption` - reading the same tables, and carrying a comment saying absence
of evidence is not evidence of a clean end - answered nothing. 7 of 12 sampled
rows carried a badge the detail page refused to claim. The probe now calls
`_interruption`, so there is one derivation; the store's `finish_reason=length`
signal reaches the list for free.

**Two vocabularies for one field.** The probes forwarded store words (`completed`,
`failed`, `working`) into a field the detail page fills with canonical kinds, so
the strings could never match even when the meaning did. `peek_status` for these
stores now returns the canonical kind, which is also what makes the comparison
below possible at all.

| Claim | Measured (2026-09-19, `python scripts/probe_audit.py --per-store 12`) |
|---|---|
| rows where a probe contradicts the detail page | **23 → 0** of 225 sampled |
| workbuddy | 12 lying → **0**; its `completed` is now evidence on both sides |
| codebuddy | 11 → **0** (`failed` reports `error`; `working` reports nothing) |
| zcode | 7 → **0** (458 sessions; the probe asks `_interruption` now) |
| words the probes emit afterwards | `None` 107, `clean` 19, `error` 5, `cancelled` 1 - every one a word `STATUS_TONES` and both locales already carry |
| what that costs on the list | zcode's green badge disappears where its store holds only an absence of failure flags (2 of 12 sampled went from a claim to blank), the same trade Round 39 made at model level |
| the instrument | `scripts/probe_audit.py` is in the repo and in the self-check block of `docs/limitations.md`, so this is re-runnable on any machine's stores instead of a claim about mine |
| gates | suite **516 passed, 2 skipped**, `ruff check .` clean, `scripts/ci_local.py --with-frontend` 10/10 |
| browser audit | not run: this slice touches no `web/` file, and `dist` is unchanged from 947921e |

### Round 41 — a row nobody can read now says so on the session

**Why this round exists.** Every parser walks a store's rows and reads the ones
it knows. A row whose shape it has never seen carries no role, falls out of the
loop at the `if not role: continue`, and leaves **no trace anywhere** - not a
count, not a note, not a fact in the export. So "the CLI started writing a new
record type" and "this session contained nothing extra" look identical from
outside the process, which is the one pair of states the cockpit exists to tell
apart.

That was confirmed by feeding the live code exactly that case before writing
any fix: a JSONL with a known user turn, a bookkeeping row and two rows of an
invented type came back with `notes == []`. Nothing was reported.

**What was built.** The fall-through now counts by row type, and anything that
is not a declared bookkeeping type becomes `unhandled_row:<type>=<count>` in the
session's notes - visible in the UI, carried in the memory export, and bounded
(5 kinds, biggest first, plus an `unhandled_row_kinds:<n>` total) the same way
`row_error` already is.

The allowlist is data, and it is data from this machine, not a guess:
`ROLELESS_ROW_TYPES` is the set of types the store actually produced over 131
sampled family sessions, with the number of sessions each appeared in written
beside it - runtime-config 54, last-prompt 49, workspace-directories 47,
active-leaf 46, attachment 43, worktree-state 35, ai-title 24, session_meta 18,
progress 14, system 8, session-meta 7, resend-fork-notice 7, custom-title 4.

**Two of those are deliberately not in the list.** `attachment` and
`resend-fork-notice` both look like they carry something a session depended on
- a file, or the fact that a turn was re-sent as a fork - and the parser reads
neither. Filing them under "bookkeeping" would have made the sweep quiet and
buried the finding, so they stay reported.

| Claim | Measured (2026-09-19, live store) |
|---|---|
| rows reported after the change, 104 sampled sessions across 5 stores | `attachment` **33**, `resend-fork-notice` **7** - and nothing else |
| report noise from the 11 declared bookkeeping types | **0** |
| retention | `raw_archive()` hands out the file byte-faithfully (path/encoding/sha256/text), so an unread row is a row not yet interpreted, not a row that is gone - asserted in the new test |
| closure test | `test_an_unseen_row_shape_is_reported_not_swallowed`: an invented type is reported, a declared one is silent, the turn list is unchanged, and the bytes are still exportable |
| gates | suite **517 passed, 2 skipped**, `ruff check .` clean, `scripts/ci_local.py --with-frontend` 10/10 |
| not run | the nine-rule browser audit: no `web/` file and no CSS here; `dist` is byte-identical to 947921e |
| what it does not do | it does not read `attachment`. That is the follow-up this round exists to make visible - see `docs/limitations.md` item 32 |

### Round 42 — reporting by sub-type found what the blob hid, so it reads them

**Why this round exists.** Round 41 reported an unread row under its `type`, and
the first thing the report showed was `attachment` on 33 of 104 sampled sessions.
Two things about that were wrong. The count was a sweep artifact - across the
family stores the real figure is **6,313 rows in 1,283 sessions**, ~39% of
everything on this machine - and the label lumped together things with very
different business. `attachment` is not one kind of row: it is twelve, named by
`attachment.type`.

Split by sub-type and the blob fell apart usefully. Nine kinds are injected
context - `task_reminder` 3136 rows, `skill_listing` 1460, `agent_listing_delta`
1286, `hook_output` 190, `queued_command` 87, `hook_non_blocking_error` 55,
`critical_system_reminder` 37, `goal_state` 18, `relevant_memories` 11,
`hook_error_during_execution` - correctly unread, and now declared per kind
rather than excused as a class. Three kinds name a file: `file` and
`edited_text_file` carry `filename`, `post_compact_restored_files` carries
`filePath` per entry. And three more - `plan_mode`, `plan_mode_exit`,
`plan_file_reference` - carry `planFilePath`, which is **the point of the
exercise**: under the `attachment` label they were indistinguishable from
reminder noise, and the report that was supposed to be a temporary telescope
would have been averaged away inside a blob of 6,313 rows.

**What was built.** The shape a row is reported under is now `type/sub-type`
where the store names one (`_row_shape`), the six file-bearing kinds are read
into `files_touched` through the paths the store spells out - `filename`,
`planFilePath`, `files[].filePath`, including the list serialised as JSON text
in some rolls - and nothing is inferred: a path the product had to guess is a
path it should not claim.

| Claim | Measured (2026-09-19) |
|---|---|
| attachment rows / sessions on this machine | **6,313** rows in **1,283** sessions (Round 41's "33 of 104" was a capped-sample artifact; corrected here, not retro-edited) |
| attachment sub-types found | 12; 9 injected context, 6 file-bearing (`file`, `edited_text_file`, `post_compact_restored_files`, `plan_mode`, `plan_mode_exit`, `plan_file_reference`) |
| paths newly recorded over 94 sampled sessions from the attachment-heavy stores | **47 distinct, 93 occurrences** - including `wgal-math/src/color.rs` and `wgal-export/src/renderer.rs`, which the file view never showed before |
| what the report surface is now | **only `resend-fork-notice` (7 sessions)** - every other shape is either read or declared, so a new one stands out instead of joining a blob |
| tests | `test_attachment_is_reported_by_its_own_kind_not_as_one_blob`: injected context silent, `filename`/`filePath`/`planFilePath` read into the record, an invented sub-type reported by its own name; suite **518 passed, 2 skipped**, `ruff check .` clean, `scripts/ci_local.py --with-frontend` 10/10 |
| not run | the nine-rule browser audit: no `web/` file here, `dist` byte-identical to 947921e |
| still open | `resend-fork-notice` is reported and still unread - it is the fork fact limitations item 25 wants, and reading it is a parser change with its own design question |

### Round 43 — the last unread row shape turned out to be a fork the file keeps

Round 42 left one name on the report surface, and the plan was to read it:
`resend-fork-notice`. It appears in 7 of the 131 sessions probed across the
family stores, carries no role, and is what limitations item 25's "a forked
transcript is linked, not joined" needed from the other side.

**What the row actually says** — measured over all 77 records on this machine,
in 7 workbuddy sessions, before any code was written:

| Question | Answer (2026-09-20) |
|---|---|
| fields it carries | `id`, `timestamp`, `type`, `cwd`, `editedUserItemId`, and `parentId` on 44 of 77 — nothing else, in either the fixtures or the live store |
| does `editedUserItemId` name a turn in the same file | **77 of 77**, and always a `role: user` message |
| what sits directly below the record | a user message, **77 of 77**; its text differs from the named turn's in **77 of 77** — this is an edited re-send, not a repeat |
| is a turn ever edited twice | no: 0 of 77 targets named twice in one file |
| does the 3-of-27 dangling links in the fixture mean something | no — the sanitizer deleted those rows. The live store has no dangling link. A fixture-only inference would have been wrong here, so the shape was re-measured on real data before designing |

So the fact is: the user rewrote a turn they had already sent; the abandoned copy
stays in the file, and the record sits above the new one. That is item 25's rule
applied *inside* one transcript, where both ends are provable rather than linked
across two pages.

**What was built.** `_load_paths` reads the record instead of reporting it: the
named turn becomes `Message.superseded`, the turn written directly under it
becomes `Message.resent`, and the transcript shows both (`↩ 改后重发`,
`⊘ 已被改写`) with the explanation in the tooltip. Neither copy is deleted — the
store kept both, so the cockpit shows both. A re-send claim is positional and
*bounded*: it applies to the next turn that reaches the transcript and is spent
if any turn intervenes, because reaching past an assistant reply would mark a
message the record never named.

| Claim | Measured (2026-09-20) |
|---|---|
| first attempt, and why it is not the shipped one | one `fork: str` field. It marked 14 of 77 re-sends: a turn that was itself a re-send got overwritten by its later `superseded` label, so 63 facts vanished silently. Caught by counting marks against records on the real store — no test covered it. Two orthogonal booleans replaced it, and the overwrite case now has its own test |
| parser layer, real store | 7 sessions, 77 records → `resent` **77**, `superseded` **77**, both on **63** turns, `fork_target_missing` **0**, and `unhandled_row:resend-fork-notice` gone from **7/7** sessions (before: present in all 7) |
| API layer, the one the page maps over | `/api/sessions/workbuddy/<sid>/detail` over the same 7 sessions: 4,178 rows, `resent` **77**, `superseded` **77**, both **63**, mismatched sessions **0** — the same numbers as the parser, so no layer drift |
| rendered DOM (in-app browser, real store, 19-row session) | 5 `↩ 改后重发` + 5 `⊘ 已被改写` over 7 user rows — 4 with both, 1 with only the re-send, 1 with only the abandoned marker; the tooltip text read back verbatim |
| fixture layer | the sanitizer's own holes reproduce the bounded reach: 17 records → 15 re-send marks, 14 edited-turn marks, `fork_target_missing:3`. Asserted as 15/14/3, not rounded up to 17 |
| report surface now | **empty** — no row shape the live stores write is unread, so the next new shape will be the only thing the note says |
| what the brief carries (checked, deliberately not changed) | the lossless brief quotes **77 of its 4,096** turns as abandoned copies and the budgeted tail **4 of 109**; **0** reach `<rules>`. Annotating them would put the parser's words inside quoted dialogue, so item 33 records the exposure instead |
| gates | 6 parser tests + 1 server test added; suite **527 passed, 2 skipped**; `ruff check src tests` clean; `scripts/ci_local.py --with-frontend` **10/10** (tsc + vite build + the nine-rule audit) |
| not verified | the screenshot path: the in-app browser reported a 0×0 hidden viewport, so the visual check is DOM text + the CI audit, not a pixel image |

### Round 44 — the empty report surface is now a gate, not an accident

Round 43 emptied the unread-shape surface. An empty surface is worth nothing if
anything can refill it without anyone noticing, so it is pinned:
`test_no_row_shape_in_the_fixture_goes_unread` parses **every session** of every
shipped fixture (not a sample) and fails if any session comes back carrying an
`unhandled_row:*` note, naming the session and the shape and saying what to do
with it — read it, or declare it in `ROLELESS_ROW_TYPES` with the count it was
measured at.

| Claim | Measured (2026-09-20) |
|---|---|
| fixture corpus swept | **77 sessions across 14 CLIs**, 0 unread notes, 0 sessions that list but fail to load |
| can the gate fail? (a green gate that cannot fail is decoration) | falsified on a synthetic store with one invented row shape: it collected `unhandled_row:brand_new_shape_from_a_store_update=1` and the assertion fires — checked before committing, not assumed |
| cost | runs inside `tests/test_fixtures.py`; suite **541 passed, 2 skipped**, `ruff check src tests` clean, `ci_local.py --with-frontend` **10/10** — and that run rebuilt the bundle with **zero churn** in `server/static/`, so the shipped JS is reproducible from these sources |
| scope note | fixtures only: a test must never read the real stores, and the live-store half of this invariant is `scripts/probe_audit.py`, which the user runs |

### Round 45 — the store's own parent link audits the rule the reader uses

Round 43 infers the re-send from position. Position is an argument about where a
row sits, so the check it deserves is the store's own: 44 of the 77 records on
this machine carry a `parentId`. Measured what that means:

| Claim | Measured (2026-09-20) |
|---|---|
| does the record and the turn it names share one parent | **44 of 44** (live stores), **8 of 8** (fixture) — the record sits at a real branch point |
| does the turn *below* the record share it too | **44 of 44**, **8 of 8** — the positional rule and the id link say the same thing everywhere both exist |
| so should the reader switch to the id | no, and the measurement says why: `parentId` is a **request-level group**, not a chain edge — one parent is shared by up to **41 rows, 21 of them user turns**. Marking "everything with this parent" would flag turns no record introduced |
| what is pinned instead | a test asserting the agreement **about the file** (not about the parser, so it cannot be satisfied by editing the reader), plus a test that a shared parent does not widen the mark past the row under the record |
| falsified before committing | the agreement test passes untouched, and fires when one below-row's parent is moved off (`…jsonl:148: the turn below is elsewhere`) |
| coverage of the shipped rule | the 33 records with no `parentId` are still position-only — that is the store's limit, recorded in limitations item 32, not a claim this reader can fix |

### Round 46 — the store's other clock is spent beside the first

`task_complete` reports two numbers and the reader spent one. `duration_ms` became
the turn's `dur_ms` long ago; `time_to_first_token_ms` sat beside it unread, which
is limitations item 27. Spending it is what makes a turn legible as *slow to start*
rather than *slow to finish*.

| Claim | Measured (2026-09-20) |
|---|---|
| does the store write it | **179 of 223** `task_complete` rows on this machine (443 ms … 11,262 ms); **56 of 56** in the sanitized codex fixture |
| is it a part of the total, or a second total | 0 of the 179 live rows, and 0 of the 56 fixture rows, exceed their own `duration_ms`. It is spent as a part; nothing about it is additive |
| where it is spent | the transcript row's hover tip, beside the total: `+35.1s · 首字 4.3s / 输出 30.8s`. Render rule #7 keeps billing out of the message area, so no chip was added and the visible text is still `35.1s` |
| where it must not be spent | a `dur_ms` the server *derived* from adjacent timestamps is a different clock, so `app.py` pairs `ttft_ms` only with a store-measured total. The row cannot show a split of a number the store never wrote |
| real-machine read | the live cockpit in a browser, `#/session/codex/01a09918…`: 1 element carries the split in its `title`, and its ms reconcile with the API's `{ttft_ms: 4254, dur_ms: 35075}` to the millisecond. A second check over 13 live sessions found 15 split rows, 0 bad pairs, and 0 in a workbuddy session of 2,551 rows — absent where the store is silent |
| falsified before committing, three ways | stop the reader spending it → 3 tests red; emit it beside a derived total → the server test red; attribute it to a neighbour when `turn_id` matches nothing → 3 tests red, including one that predates this round |
| suite | **548 collected / 546 passed / 2 skipped**; the 5 new tests are 5 passed + 543 deselected under a `-k` of their own names. Headline totals are not comparable across rounds: fixture-driven `parametrize("cli", PRESENT)` moves with the environment, so the derived form (543 + 5) is what carries here |
| what item 27 now says | not "nothing spends it" but "it is spent where a store writes one": 3 of the 14 fixture stores time a first token (codex per turn, zcode and CherryStudio per model), 11 write no such number, and the 44 codex rows without it show the total alone |

### Round 47 — the doctor could not see 2,481 of the 3,322 sessions on this machine

Round 46's numbers came from pointing every parser at its live store. Doing that
exposed a bigger thing: two of the twenty readers have **no store probe at all**, so
`handoff doctor` — the one command the docs tell a user to run — prints no row for
the largest store on the machine.

| Claim | Measured (2026-09-20) |
|---|---|
| what was missing | `qoder-ide` (**2,259** sessions, 68% of this machine's data) and `opencode` (**222**) had parsers, stores and no entry in `discover()` — so no doctor row, and no row on any surface that reads it |
| why it stayed missing | `matrix.ROADMAP` exempted both from the lockstep gate that would have caught it, on two claims about their *format*: "Electron leveldb — no session files on disk" and "storage layout undocumented". Both are false here: `~/.qoder/projects/*.jsonl` and `~/.local/share/opencode/opencode.db`, read by their own parsers, 25 of 25 sampled qoder-ide sessions loading dialogue |
| what the counts reconcile to | the store holds **4,213** transcripts: **2,274** session files + **1,939** under a `subagents/` directory (verified as *reachable*, not lost: the parent lists 76 sub-agent-labelled messages and `load()` on a trace id returns its 76 messages). **19** session dirs hold `state.json` with no transcript in either position — two independent methods agree on 19 |
| what the row says now | `qoder-ide … parses yes (2259) · 2274 session file(s); 1939 transcript(s) under subagents/; 19 dir(s) with session state and no transcript; 1 account config(s)` — read from the live machine, and `qoderwake`'s line now ends `listed as qoder-ide` so 4,213 files beside a `yes (0)` is no longer a puzzle |
| a bug this round created and caught | the first `opencode_store` reported the `.db` **file** as `StoreInfo.path`; `_doctor_rows` feeds that to `with_root`, whose parser appends `opencode.db` again → doctor printed `parses yes (0)` for a 222-session store. Fixed by reporting the directory, and pinned by a test that asks the parser to resolve the probe's own path |
| falsified before committing | rename the probe's cli → the lockstep gate fails naming `qoder-ide`; drop the "transcript beside the dir" check → 2 tests red; drop the uuid-directory filter → the `jobs/*/state.json` test red (that layout has no transcript *by design*, so counting it would report a gap that is not one) |
| gates | 8/8 with the regenerated `support-matrix.json`. **555 passed / 0 skipped** (was 546 / 2): +7 new tests in `tests/test_locations.py`, and the 2 skips that disappeared were the `qoder-ide` and `opencode` lockstep exemptions this round removed — they are assertions now. `ROADMAP` holds only `trae`, and the exemption's rule is written where it can be read: an exemption must be a claim about the *format*, and a claim about a format can be measured |

### Round 47b — the store's other artifact kind was asked the ending question too

Item 31's "the transcript has no end row" was only ever about the transcript. The
qoder store also writes 2,341 `state.json` sidecars: all parse, and none holds a
key resembling `status`/`finish`/`error`/`abort`/`exit` — the fields are
`createdAt`, `revision`, `updatedAt` and a `state` dict of client bookkeeping
(`replacementDecisions`, `seenFunctionResponseIds`). The ending is therefore
unrecorded in both places a session exists, which is the strongest form of the
negative this reader can be given.

## [S1] Problem

Four slices have made the cockpit's *tokens* official: the palette is Google's 49
named roles, the shape scale is `corner-*`, feedback is the official state layer,
the type scale is the seven roles, and motion is the M3E springs. None of that
touches what a **control** is. Every control on screen is still antd's v6 default
geometry wearing our colours — and antd v6 is not Material 3.

1. **Every button is the wrong shape and the wrong size.** antd's default button
   is a 32px-tall rectangle with `border-radius: 12px` (which we set globally, in
   `theme.ts`, to the M3 *medium* corner) and 4/15px padding. M3E publishes three
   button sizes — 40 / 56 / 96px tall — with `corner-full` at rest, `20/24/32px`
   icons, `16/24/48px` leading and trailing space and, at the one point that makes
   an M3E button feel like an M3E button, a **shape morph on press** (`corner-small`
   `8px` at 40px, `corner-medium` `12px` at 56px, `corner-large` `16px` at 96px).
   None of that is present, and `border-radius: 12px` is applied to *everything*
   antd draws, which is precisely the "half antd default, half M3" mixture the
   theming contract forbids.
2. **Chips are one component pretending to be three.** `.ah-chip` is the CLI
   identity chip: a 20px-tall pill with a mono label and no press state — correct
   for what it is (a label, deliberately not a control), and not a Material chip.
   M3 publishes three *interactive* chip families (assist / filter / input) at
   32px with 18px icons, `label-large`, an 8px corner, a 1px `outline-variant`
   unselected outline, `secondary-container` when selected, and a 48px touch
   target. The cockpit has no filter chip at all, so "show me only errors" is a
   `Segmented` with the wrong anatomy.
3. **List rows have no anatomy.** A session row is a `<button>` with a border and
   a hover lift. M3 publishes list-item heights **56 / 72 / 88px** for one / two /
   three lines, a 24px leading icon at 16px leading space, 16px trailing space, a
   `body-large` label, a `body-medium` supporting line, a `label-small` overline
   *and* trailing supporting text, and an M3E **shape morph** across its states
   (`corner-extra-small` `4px` at rest → `corner-medium` `12px` on hover →
   `corner-large` `16px` when pressed or selected).
4. **The text field does not exist.** Search is an antd `Input`; nothing in the
   app has a floating label, an active indicator, a supporting-text slot, an
   error state or the official 56px container. M3's filled field is
   `16px top + 24px body-large + 16px bottom = 56px` with a `corner-extra-small-top`
   `4/4/0/0` container, a 1px `on-surface-variant` active indicator that becomes
   3px `primary` on focus, and a label that shrinks from `body-large` to
   `body-small` as it floats.
5. **Selection controls are antd's, not M3's.** antd's Switch is 44×22 with a
   2px-radius thumb; M3's is a **52×32 track** with a `corner-full` 2px outline,
   a 24px handle when selected (16px unselected, 28px pressed, 16px icon), track
   `primary` / `surface-container-highest`, handle `on-primary` / `outline`. The
   checkbox is an 18px `primary` square at 2px radius with a 40px state layer;
   the radio is a 20px `primary` ring with the same 40px layer. `Segmented` is
   the closest thing in the app to an M3 control and still has the wrong height,
   the wrong selected colour and no `corner-full`.
6. **Nothing that floats uses M3's own scrim or springs.** `DialogTokens` says
   `corner-extra-large` (**28px**), `surface-container-high`, elevation 3 and a
   `ScrimTokens.ContainerOpacity` of **0.32**; the M3E dialog enters and leaves on
   a spring. The app has no dialog, but it has antd popups whose shadow we
   already replaced and whose scrim (if a modal ever ships) would be antd's
   `rgba(0,0,0,0.45)`.
7. **Progress is a 3px bar with square ends and no stop indicator.** M3's linear
   indicator is 4px with `corner-full` ends, a `secondary-container` track, a
   **4px stop indicator** at the end of the track and a **4px gap between the
   active indicator and the stop**; the circular one is 40px at 4px thickness.
   Nothing here has ever heard of the stop indicator.

The consequence is the one the user named: the app reads as "a well-themed
dashboard", not as a Material 3 Expressive product. Tokens alone cannot fix
anatomy.

## [S2] Design

**A fifth generator block, `component`, carrying Google's per-component numbers
with their source, and a stylesheet that spends it.** `scripts/gen_tokens.py`
gains `COMPONENTS` beside `SHAPE`/`STATE`/`ELEVATION`/`TYPESCALE`/`MOTION`, with
citations and a `_source` per family. The rule stays the same as the rest of the
pipeline: a number a component uses is a token or it is a bug.

The values are taken from **first-hand AndroidX token files** (androidx-main,
`compose/material3/material3/src/commonMain/kotlin/androidx/compose/material3/tokens/`)
and cross-checked against **material-web's generated tokens and component
stylesheets** (`tokens/versions/v0_192/` and `<component>/internal/*.scss`).
Where the two disagree the disagreement is recorded rather than smoothed over
(see the deviation table in `docs/theming.md`).

| Family | Official numbers this slice spends |
|---|---|
| Button | 40 / 56 / 96px containers; `full` at rest; pressed `8` / `12` / `16`; icons 20 / 24 / 32; leading+trailing 16 / 24 / 48; `min-width 64`; outlined outline 1px (`2px` at 96) |
| Icon button | 40px container, `full` round / `medium` square, pressed `small`, icon 24, spaces 4 / 8 / 14 (narrow / default / wide) |
| FAB | 56 / 40 / 80 / 96px; corners `large` / `medium` / `large` / `extra-large`; icons 24 / 24 / 28 / 32 |
| Chip | 32px, 18px icons, `label-large`, 48px touch target; assist + input 8px corner, filter-on-M3E 12px → `full` selected → 8px pressed |
| List item | 56 / 72 / 88px; leading icon 24 at 16px; trailing 16px; morph 4 → 12 → 16 |
| Text field | filled + outlined, 16/24/16 = 56px (dense 8/24/8 = 40px, labelled ours); corner `extra-small-top` / `extra-small`; indicator 1px → 3px focus; outline 1px → 3px focus; label `body-large` → `body-small` |
| Switch | track 52×32, outline 2px, handle 24 / 16 / 28, icon 16, state layer 40 |
| Checkbox | 18px box, 2px radius, 2px outline, state layer 40 |
| Radio | 20px icon, state layer 40 |
| Segmented | 40px, `full`, selected `secondary-container` / `on-secondary-container`, outline 1px, icon 18 |
| Dialog | `extra-large` 28px, `surface-container-high`, elevation 3, scrim 0.32, M3E springs |
| Progress | linear 4px + 4px stop + 4px gap, `corner-full`, `primary` / `secondary-container`; circular 40px, 4px |
| Tooltip / Badge / Divider / Snackbar | tooltip `inverse-surface` at `extra-small`; badge 6px dot / 16px large on `error`; divider 1px `outline-variant`; snackbar `inverse-surface`, `extra-small`, elevation 3, 48 / 68px |
| Layout | top app bar small 64px; navigation bar 64 / 80px with a 40px indicator; rail item 64px with 6px vertical space |

**What "applied" means, family by family.** A new stylesheet `web/src/m3.css`
(imported by `index.css` above Tailwind, so its rules are unlayered and win)
defines one class per family, and every declaration reads a `--ah-c-*` custom
property that `theme.ts` injects from `tokens.json`. antd keeps its **behaviour**
— focus management, keyboard handling, a11y attributes, Table virtualisation —
and loses its **appearance**: `antdConfig` hands antd the same numbers through
`ConfigProvider`'s component tokens where antd exposes them (`controlHeight`,
`borderRadius`, per-component `paddingInline`), and `m3.css` takes over the
anatomy antd has no token for (the shape morph, the state layer, the stop
indicator, the floating label).

**The shape morph is the point, so it gets its own rule.** `:active` on a button
swaps `--ah-c-button-<size>-shape` for `--ah-c-button-<size>-shape-pressed`, and
a list item walks `4 → 12 → 16` across rest/hover/pressed-or-selected, on
`standard-fast-spatial`. A morph is geometry, so it animates on a spatial spring
and is zeroed by `prefers-reduced-motion` like everything else.

**Gates that can fail.** (1) `tests/test_tokens_components.py` is an independent
literal copy of Google's numbers — a generator typo fails instead of
regenerating a wrong file — covering all families above. (2) A consumption gate
asserts that every `--ah-c-*` a component reads exists in `tokens.json` **and**
that every published family is read by at least one rule, so a token block
cannot quietly become decoration. (3) A literal gate scans `m3.css` for raw
`px` sizes, hex colours and bare durations and fails outside a short, explicit
allow-list (hairline radii, `0`, percentages). Each gate ships with a mutation
proof on a `%TEMP%` copy, because this repo has shipped three gates that could
not fail.

**The dark-screenshot anomaly is reproduced and localised before any of this is
measured through a screenshot.** §8.7 of the brief records that
`getComputedStyle` reports the correct dark values while `page.screenshot()`
renders light. A read-only probe reads the exported PNG's pixels back and
compares them with the computed colours, so the slice's visual evidence is not
built on an instrument that lies.

## [S3] Out of Scope

Changing any colour, shape step, type role, elevation recipe or spring (that is
the previous four slices, and this one consumes them); new views or information
architecture; a component playground route; the parsing/rendering parity work in
§6 of the brief (a separate slice); webfonts; any JS animation library; replacing
antd's behaviour layer (a11y, keyboard, Table virtualisation stay antd's).

## Tasks

- [x] T1: `component` token block — `gen_tokens.py` emits every family above with
      Google's numbers and a per-family `_source` URL; `--check` green;
      `tests/test_tokens_components.py` asserts the numbers literally (covers: S2)
- [x] T2: Button + icon button + FAB — `m3.css` families with the official
      heights, paddings, icons, disabled 38% and the press shape morph; antd's
      `Button` receives the same geometry through `ConfigProvider`; browser-
      measured on the built bundle (covers: S2; depends: T1)
- [x] T3: Chip family — assist / filter / input at 32px with an 18px leading
      icon, the official selected container, the checkmark slot and the 48px
      touch target; the CLI identity `.ah-chip` is untouched and documented as a
      different component (covers: S2; depends: T1)
- [x] T4: List item anatomy — one/two/three-line heights, leading icon, trailing
      slot, `body-large` label + `body-medium` supporting + `label-small`
      overline/trailing, and the `4 → 12 → 16` state morph (covers: S2; depends: T1)
- [x] T5: Text field — filled and outlined, floating label, 56px and 40px
      containers, focus indicator 3px, error/disabled states (covers: S2; depends: T1)
- [x] T6: Selection controls — switch (52×32, 24/16/28 handle, 16px icon),
      checkbox (18px, 2px radius), radio (20px), segmented (40px, `full`,
      `secondary-container` selected) (covers: S2; depends: T1)
- [x] T7: Dialog — 28px radius, `surface-container-high`, elevation 3, scrim
      0.32 through `--ah-scrim`, M3E enter/exit springs (covers: S2; depends: T1)
- [x] T8: Progress — linear 4px with the 4px stop indicator and the 4px gap,
      rounded ends, official track/active/stop colours; circular 40px (covers: S2; depends: T1)
- [x] T9: Tooltip, badge, divider, snackbar — official container, shape,
      elevation and type role for each (covers: S2; depends: T1)
- [x] T10: Layout structure — 64px top app bar, navigation bar/rail geometry and
      the M3 spacing scale, applied to the shell (covers: S2; depends: T1)
- [x] T11: Gates and their mutation proofs — the literal component table, the
      token-consumption gate and the literal gate, each demonstrated able to fail
      on a `%TEMP%` copy (covers: S2; depends: T2–T10)
- [x] T12: The dark-screenshot anomaly is reproduced, root-caused and closed, or
      reported unresolved with the measurement that shows it (covers: S2)
- [x] T13: Docs, deviation register and verification — `docs/theming.md` gains
      the component contract and every new deviation; all gates green; one
      independent review recorded with its verdict (covers: S2; depends: T2–T12)
- [x] T14: Keyboard focus — the `focusRing` family from material-web's
      `_md-comp-focus-ring.scss` (3px `secondary`, 2px outward offset, the
      `0 → 8px → 3px` choreography on `duration-long4`/emphasized), spent by one
      rule whose selector arms match antd's specificity, with the Select chip's
      ring delegated to the box the reader sees; `--focus` gate plus a live
      mutation proof (covers: S2; depends: T1)
- [x] T15: The list that never loaded — one build in flight per cache key and a
      stale answer while one caller refreshes; the git probe reads `.git/HEAD`
      instead of spawning two processes per cwd; `--overlap` gate for controls
      painted over one another, with a mutation proof (covers: S2; depends: T1)
- [x] T16: Pointer states — `--states` hovers and presses a representative of
      every control family with a real pointer, in both themes, and checks the
      layer, its 8%/12% opacity, token-colouredness and the absence of colour
      swaps or filters; found and fixed a missing icon-button hover layer and a
      hovered segment painted with the selection container (covers: S2; depends: T1)
- [x] T17: Disabled states and the last unmounted families — the gallery mounts a
      disabled variant per family plus a dot Badge, a vertical Divider and a link
      Button; `--disabled` compares each against the opacity its own token
      publishes and found the FAB and filter chip fading themselves; the
      reachability audit drops to 0 unverified (covers: S2; depends: T1)
- [x] T18: Device scheme and custom seed — `auto` verified against emulated system
      schemes including a live flip with no reload; a seed derives all 49 roles
      through Google's dynamic-colour library at the 2021 spec, lazily loaded
      (0 chunks fetched without one), AA-gated on the same pairs as the baseline,
      with `ok`/`warn` and the CLI inks deliberately untouched (covers: S2)
- [x] T19: High-contrast modes — `forced-colors: active` gets system-coloured
      hover/press outlines (the mode drops `box-shadow`), the ring/indicator/
      selected states were each measured to survive, and `prefers-contrast: more`
      strengthens separators; `--states` re-runs under forced colours so the
      family list cannot rot silently (covers: S2; depends: T16)
- [x] T20: The palette's provenance — `tests/test_official_palette.py` compares
      our role→rung map and rung colours against vendored, hash-pinned copies of
      `_md-sys-color.scss` and `_md-ref-palette.scss` (v0_192): 0 differences in
      both themes, both layers; mutation-proved by changing a rung and a role.
      `--focus` and `--disabled` also gained a forced-colors pass (covers: S2)
- [x] T21: The four non-colour layers, checked the same way —
      `tests/test_official_layers.py` compares shape (12 entries), elevation (6
      levels), state (4 opacities) and type (10 shared roles × 4 fields) against
      vendored, hash-pinned copies of the matching v0_192 files: zero differences
      in each, all four mutation-proved, with the five unused official type roles
      asserted absent by name (covers: S2; depends: T20)
- [x] T22: The elevation recipe — MDC-Web's `_elevation-theme.scss` vendored (MIT,
      header asserted) and compared: 3 maps × 6 levels + 3 opacities + the
      baseline colour, 0 differences, mutation-proved on both a shadow value and
      an opacity (covers: S2; depends: T21)
- [x] T23: The M3E springs — androidx's two motion token files plus
      `MotionScheme.kt` vendored (Apache-2.0, `v0_14_0` asserted) and compared:
      12 damping/stiffness pairs, 0 differences, each scheme referencing only its
      own file, mutation-proved on a damping and a stiffness (covers: S2; depends: T21)
