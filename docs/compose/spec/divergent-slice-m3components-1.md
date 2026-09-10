---
feature: divergent-slice-m3components-1
status: designed
updated: 2026-09-10
branch: compose/divergent-slice-m3components-1
commits: 0cb9eb1..HEAD
---

# Divergent Slice M3 Components 1

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

- [ ] T1: `component` token block — `gen_tokens.py` emits every family above with
      Google's numbers and a per-family `_source` URL; `--check` green;
      `tests/test_tokens_components.py` asserts the numbers literally (covers: S2)
- [ ] T2: Button + icon button + FAB — `m3.css` families with the official
      heights, paddings, icons, disabled 38% and the press shape morph; antd's
      `Button` receives the same geometry through `ConfigProvider`; browser-
      measured on the built bundle (covers: S2; depends: T1)
- [ ] T3: Chip family — assist / filter / input at 32px with an 18px leading
      icon, the official selected container, the checkmark slot and the 48px
      touch target; the CLI identity `.ah-chip` is untouched and documented as a
      different component (covers: S2; depends: T1)
- [ ] T4: List item anatomy — one/two/three-line heights, leading icon, trailing
      slot, `body-large` label + `body-medium` supporting + `label-small`
      overline/trailing, and the `4 → 12 → 16` state morph (covers: S2; depends: T1)
- [ ] T5: Text field — filled and outlined, floating label, 56px and 40px
      containers, focus indicator 3px, error/disabled states (covers: S2; depends: T1)
- [ ] T6: Selection controls — switch (52×32, 24/16/28 handle, 16px icon),
      checkbox (18px, 2px radius), radio (20px), segmented (40px, `full`,
      `secondary-container` selected) (covers: S2; depends: T1)
- [ ] T7: Dialog — 28px radius, `surface-container-high`, elevation 3, scrim
      0.32 through `--ah-scrim`, M3E enter/exit springs (covers: S2; depends: T1)
- [ ] T8: Progress — linear 4px with the 4px stop indicator and the 4px gap,
      rounded ends, official track/active/stop colours; circular 40px (covers: S2; depends: T1)
- [ ] T9: Tooltip, badge, divider, snackbar — official container, shape,
      elevation and type role for each (covers: S2; depends: T1)
- [ ] T10: Layout structure — 64px top app bar, navigation bar/rail geometry and
      the M3 spacing scale, applied to the shell (covers: S2; depends: T1)
- [ ] T11: Gates and their mutation proofs — the literal component table, the
      token-consumption gate and the literal gate, each demonstrated able to fail
      on a `%TEMP%` copy (covers: S2; depends: T2–T10)
- [ ] T12: The dark-screenshot anomaly is reproduced, root-caused and closed, or
      reported unresolved with the measurement that shows it (covers: S2)
- [ ] T13: Docs, deviation register and verification — `docs/theming.md` gains
      the component contract and every new deviation; all gates green; one
      independent review recorded with its verdict (covers: S2; depends: T2–T12)
