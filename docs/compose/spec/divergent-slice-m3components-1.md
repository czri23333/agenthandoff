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
