# Theming: tokens, contrast, and why nothing is hardcoded

The cockpit has two themes (dark and light, plus "follow the system"). Both are
generated from one file: [`web/src/tokens.json`](../web/src/tokens.json).

```
tokens.json  ──▶  theme.ts  ──▶  CSS custom properties  ──▶  index.css helpers
                          └────▶  antd ConfigProvider tokens ──▶  antd widgets
```

Components never choose a colour. They use a semantic class (`.ah-meta`,
`.ah-title`, `.ah-ok`, `.ah-warn`, `.ah-err`, `.ah-chip`, `.ah-code`, …) or a
Tailwind arbitrary value that points at a custom property
(`text-[var(--ah-text-1)]`). That is enforced by
`tests/test_tokens_contrast.py`, which fails if a palette literal appears outside
the token table.

## The contract

| Pair | Requirement |
|---|---|
| text tier (`text1/2/3`) on any surface | ≥ 4.5:1 (WCAG AA, normal text) |
| semantic colour (`accent/ok/warn/err/placeholder`) on `surface1` | ≥ 4.5:1 |
| CLI identity ink on its own chip background | ≥ 4.5:1, in **both** themes |
| `text1` on a tonal container | ≥ 4.5:1 (bubbles, chips and banners carry text) |
| chip border / divider vs surface | ≥ 1.15:1 (visible, not loud) |
| any rendered text size | an official M3 role, and ≥ 12px unless the role is `label-small` (11px, mono-only) |
| any `font-weight` | 400 or 500 — M3 publishes no heavier text weight |
| any animated property | names a `--ah-motion-*`/`--ah-spring-*` token, never a literal duration (the `prefers-reduced-motion` block is the one exception: it exists to *zero* durations) |
| interaction feedback | the official state layer (content colour at hover 8% / focus 12% / pressed 12%), never a brightness filter or a swapped background |
| keyboard focus | material-web's focus ring — 3px of `secondary` at a 2px outward offset, growing to 8px and settling on the emphasized curve — paired with the 12% focus layer; never antd's `--ant-color-primary-border`, and never a `border-radius` written on `:focus-visible` |
| depth | level 0 (outline, no shadow) unless the surface floats: popover/dropdown/menu/tooltip/dialog take levels 2–3, a hovered row level 1 |
| reduced motion | `prefers-reduced-motion: reduce` collapses every duration and delay |
| a control's geometry | an official per-component token, *referenced* (never restated) from `tokens.json`'s `component` block and spent only as a `--ah-c-*` custom property |
| interaction geometry | the M3E shape morph where the component publishes one: a button tightens to `corner-small`/`medium`/`large` while held, a list item widens `extra-small` → `medium` → `large` across rest/hover/selected |

### Where this deliberately differs from Google

"Official" needs a "where we differ, and why" beside it, or the next reader has to
re-derive every judgement.

| Official | Ours | Why |
|---|---|---|
| Roboto (`md-ref-typeface` plain/brand) | the system stack | local-first: no webfont means no network at startup and no FOUT |
| HCT palette generation from a seed | the *shipped* palette is hand-authored sRGB and AA-gated; a **user** seed is derived at runtime by Google's own library | generating the default would re-brand every colour, and the baseline is a published artefact rather than one seed's output — `#6750a4` is the baseline's *primary*, not its seed. So the default stays authored and the derivation is opt-in, per reader, in the 2021 spec the baseline was published under |
| native springs (Compose `SpringSpec`) | `linear()` sampling of the official damping/stiffness pair, `cubic-bezier` fallback | CSS has no spring primitive; the sampling is deterministic and regenerates with the tokens |
| white elevation *overlay* on dark surfaces | the MDC-Web black shadow in both themes | that is what material-web compiles to CSS for the web; our dark surfaces already step lighter (surface0→2), which serves the same purpose |
| tracking applies to every role | CJK-authored prose keeps `letter-spacing: normal` | tracking is a Latin typography device; the roles' numbers are sub-pixel Latin optimisations |
| M3 publishes no `disabled` opacity | `container 12%` / `content 38%`, labelled ours in `tokens.json` | a disabled control has to look disabled; the value is recorded as ours rather than dressed as Google's |
| `label-small` at 11px | 11px only beside a mono family | 11px CJK is illegible; the role is marked `mono_only` and the floor test enforces the pairing |
| the focus ring is a sibling element with its own geometry (`md-focus-ring`, `inset: -2px`, `border-radius = host + outward-offset`) | one `outline` with `outline-offset: 2px` | an outline never affects layout, composes with whatever shadow the host has, and — measured — Chromium grows its corner radius by the offset exactly as the published geometry does. Side by side at 4×: ours 9675 ink pixels, the published structure 9672, `IoU` **0.9985**, **15** differing pixels along the curves. The single-element form is the same ring with one less node |
| the focus *state layer* is part of the focus state (12% whenever a control holds focus) | for most controls it is on `:focus-visible`, so a pointer click focuses one without the layer | narrower than the published behaviour, and narrower than the first version of this note claimed: a text input matches `:focus-visible` on a pointer click all by itself, so the search field and the Select chip do get their layer on click (`:focus-within` and `.ant-select-focused` respectively, both measured). What is keyboard-only is the rest. Widening it to `:focus` would double the layer on every component that draws its own, so it is recorded rather than changed |
| a Select's focus indicator is the control's own outline | the ring is drawn on the chip around the input, via `:has(:focus-visible)` | antd sets `outline: none` on the inner input, and that input measures 132x30 inside a 176x50 chip — so the ring landed on a node with no visible box while the outline never rendered at all. `:has()` moves both the ring and the layer to the box the reader sees and stays keyboard-only, because a pointer click focuses the input without matching `:focus-visible` |
| a card header carries a title and one trailing affordance | the session-detail rail's brief card carries the title and the 摘要/全文 switch in the header, and its three transport actions moved into the body | the rail is 400px wide; the title row plus three buttons came to ~450px, and antd's single-row head painted them over each other — measured: the `.zip` button at x 1081–1187 over the switch at x 1109–1213, and over the title. M3 publishes no "card header with a toolbar", and a second row that wraps is the honest answer at this width. The gate that finds this class of defect (`--overlap`) compares every pair of rendered controls on every route, in both themes, and on a session-detail route |
| a dense text field is 40dp in Material's own spec pages | built from the same three published numbers (`8 + 24 + 8`), labelled ours | the *token* files publish only the 56dp geometry; the derivation is shown so it can be checked rather than trusted |
| the filled field's focus indicator is 3px (`tokens/_md-comp-filled-field.scss`) | 3px | material-web's own pinned `versions/v0_192/_md-comp-filled-text-field.scss` still says 2px; the current field token set is the newer document and we follow it, but the disagreement is real and recorded here |
| a list item's disabled label is 38% (`ListTokens.kt`) | 38% | material-web's `_md-comp-list.scss` says 0.3 for the same token. androidx is the newer source; either way the value is Google's, not a guess |
| every component has a Material implementation | some do not, and the cockpit's are ours | M3 publishes no data table, no banner, no empty state, no description list and no inline spinner size. The table takes the list item's 16px leading space and the spacing scale for its cells; the rest are compositions, named here rather than left to look official |
| antd's `size="small"` is a 32px control | mapped onto M3's *small* (40px); `size="large"` onto M3's *medium* (56px) | M3 publishes no 32px button. Leaving it would put an off-scale rectangle in an M3 toolbar, which is worse than moving it 8px |
| a button's shape is its container's | a bare `.ah-btn` means the *filled* button, and antd's `default` is the *outlined* one | antd's variant classes are the owner of container colour; an earlier draft painted every antd button from the shared geometry rule and shipped an outlined button with a primary container. The rule now sets geometry only |
| a list row lifts on hover (as the m3eofficial report claimed) | it morphs instead: `extra-small → medium`, elevation stays 0 | `ListTokens.kt` gives a list item level 0 at rest and level 4 only while *dragged*. The previous slice raised a hovered row to level 1 by analogy with M3E cards; that was wrong, and the row is now the correction |
| `.ah-chip` is a chip | it is a CLI identity *label*: no press state, no morph, deliberately | it answers no interaction because it has none. M3's interactive families are `.ah-mchip` (`--assist` / `--filter` / `--input`) and are separate components with separate tokens |
| `FabMediumTokens.ContainerShape` | **ours**: `corner-large` (16px) | Google's file has that line commented out (`// TODO: uncomment when ShapeKeyTokens.CornerLargeIncreased is available`) and no published token set gives `corner-large-increased` a dp value. M3E's intent is 20dp; 16 is our inference, marked `shapeOurs` in `tokens.json` rather than presented as Google's |
| one number, one operator | the opacity token *is* the percentage, and no rule multiplies it again | `color-mix(… var(--ah-c-dialog-scrim-opacity) …)`. The first draft wrote `calc(var(… ) * 100%)`, i.e. percentage × percentage, which is not a valid calc type: the declaration was invalid at computed-value time and the dialog painted **no scrim at all**. A fallback would not have rescued it — an invalid substituted value discards every candidate for that property |
| list rows sit on `surface` (`ListTokens.ItemContainerColor`) | `surface-container-low`, no border | a screen of 118 rows needs a resting fill to scan; the *border* is gone, which is what M3 actually forbids, and the fill is one step |
| M3E's loading indicator morphs between shapes along a path | it morphs its *corner* while turning: `corner-full` → `corner-extra-small` four times per revolution | the Compose morph is a path animation CSS cannot express, so this is the closest equivalent and is labelled as one. The first attempt rotated a circle, which is a no-op — a circle has no feature to turn — so the loader read as a static purple dot. Measured after the fix: 28 distinct corner radii in 1.2 s, from 19.5px to fully round |
| `SearchBarTokens` publishes no placeholder ink | the placeholder borrows the supporting-text role, `on-surface-variant` | same tier, same published role, rather than a new colour |
| M3 primary navigation tabs are a top-level destination control | the cockpit's shortcut keys (`1`–`5`) render inside each tab as a small hint | the shortcuts are a real feature of this product and cannot live in a tooltip; the label itself is no longer `会话 1`, which is what made the tabs read as names |

`tokens.json` is **generated**. Edit `scripts/gen_tokens.py`, then:

```bash
python scripts/gen_tokens.py          # rewrites tokens.json and firstpaint.css
python scripts/gen_tokens.py --check  # fails if either committed file drifted
cd web && npm ci && npm run build     # emits into src/agent_handoff/server/static
```

`--check` covers **both** outputs now (the token file and the two-line pre-JS
first paint), because a generated file that drifts silently is the failure mode
this script exists to prevent, and it does not care which file it is.

`--check` exists because this file used to be half-generated: `shape` and the
four tonal containers lived only in the committed JSON, so following these
instructions deleted the M3E radius scale (silently — `theme.ts` falls back to
hardcoded values) and nine CLI identity colours (loudly — a test caught those).
The identity list now comes from the parser registry, so a new CLI cannot be
added without an identity, and `tests/test_tokens_generated.py` fails if the
committed file and a fresh run disagree.

Nine **CLI identities** are pinned rather than hue-derived. They predate the
script, and solving `badge()` for its pre-image returns nothing for any hue
(`opencode`, `qoder-ide`, `cherrystudio`, `qoderwork-app`, `qwenwork-app` are
out of gamut; for the other four the rounded hue reproduces `bg` but never
`fg`/`border`), so they are kept verbatim — still AA-gated — instead of being
quietly re-branded. Fold them into `CLI_HUES` the next time those identities are
re-designed on purpose.

The four **tonal containers** are the opposite case and are now *derived*: one
strength per theme reproduces all four byte-exactly (dark `0.179`, light `0.16`,
measured by solving `tint()` for its pre-image rather than by eye), so a palette
edit re-tints the chips and the user bubble together and the AA gate re-checks
the text that sits on them. Use inversion as the test before pinning anything:
an exact pre-image means derive, no pre-image means pin.

## Interaction state (M3)

M3 does not express feedback as a different colour or a filter. It composites the
surface's **own content colour** over the surface at an official opacity:
`hover 0.08`, `focus 0.12`, `pressed 0.12`, `dragged 0.16`
(`tokens/versions/v0_192/_md-sys-state.scss`). Ours is one inset shadow, so no
extra DOM is needed and the layer sits over whatever the element already has:

```css
.ah-row:hover {
  box-shadow: inset 0 0 0 9999px
    color-mix(in srgb, var(--ah-state-layer-color, currentColor) var(--ah-state-hover), transparent);
}
```

`--ah-state-layer-color` exists for a filled surface whose official layer colour is
the *on*-colour of its container rather than its own text. Focus keeps a visible
ring — M3 pairs the indicator with the layer, it does not replace it.

Two things this replaced, both non-M3: `filter: brightness(0.9)` on press
(darkens a light surface and lightens a dark one — the wrong direction in exactly
one of the two themes) and row hover *swapping* `surface1` for a tonal container.
A 12% content layer is not the same composition as a tonal fill, and only the
former is checkable against Google's spec.

`tests/test_typography_scale.py` and `tests/test_tokens_m3official.py` keep the
values honest; nothing asserts the *absence* of `brightness()` any more, because
there is nothing left to find — the layer is the only mechanism in the stylesheet.

Hover was swept separately for the same reason the focus ring was: if antd can
out-specify our layer on `:focus-visible`, it can on `:hover`. The first version
of that sweep was a probe with a substring test, and it was too weak to be worth
trusting — so it became `--states`: a real pointer, a settled transition
(`getAnimations({subtree: true})`, because a tab's layer lives on `::before`), and
four questions per control — is there a layer, is it at the published 8%/12%, is
its colour in the token table, and did the control answer by *swapping* a colour
or filtering itself.

It found two things the stylesheet looked fine while hiding:

* **every icon button answered the pointer with nothing.** The family set
  `--ah-state-layer-color` and spent it only on `:active`, so hover layer alpha
  read `0.000` on all ten of them. The fix is the ordinary 8% layer — and it had
  to be followed by an explicit 12% on press, because pressing keeps `:hover`
  true and the two selectors tie at (0,4,0): without it, the *hover* value won on
  source order (measured `press 0.080`).
* **a hovered segment looked selected.** `:root .ant-segmented
  .ant-segmented-item:hover:not(.ant-segmented-item-selected)` was painted with
  the same `secondary-container` as the selected segment — the swapped-background
  mechanism this contract forbids, wearing the selection colour. It is now the 8%
  layer over the segment's own ink (and `on-secondary-container` when the segment
  *is* selected), so pointing at a segment no longer claims it is chosen.

The sweep samples by **family** rather than by document order (a route with 187
rows would otherwise spend every slot on rows), and it is honest about the
denominator: `States: 44 controls hovered and pressed with a real pointer`.

The **disabled** state is the fifth thing that is checkable, and it is checked
where it exists: the whole running product has two disabled controls (the pager's
previous button on page one and the `<button>` inside it), so the gallery mounts a
disabled variant of every family the tokens describe — buttons, icon button, FAB,
chips, switch, checkbox, radio, segmented, select chip, input — and `--disabled`
asks three questions of each: it must not fade *itself* (a blanket `opacity` takes
the focus ring and every child with it), it must not take focus, and it must not
answer the pointer.

The expectation for that first question is read out of `tokens.json` rather than
written into the tool, because the file publishes two different shapes:
`checkbox.disabled.opacity` and `radio.disabled.opacity` are `0.38` — for those
two the published treatment *is* the control at 38% — while switch, field,
segmented and slider publish per-part opacities, so their element must stay at
`1`. A gate that demanded `1` everywhere would call antd's correct checkbox a
defect; one that accepted `0.38` everywhere would pass the two real defects it
found:

* **a disabled FAB and a disabled filter chip were faded, not composed.** Neither
  family had a disabled rule, so both fell through to `button:disabled { opacity:
  0.38 }` — which fades the container, the content *and* the FAB's elevation
  shadow by the same amount. Both now compose the published opacities (the FAB
  takes the generic `state.disabled` pair, the chip its own 0.12/0.38) and keep
  `opacity: 1`.
* the *probe* was wrong twice: it read the baseline before the entry animation
  settled (so a mid-transition `box-shadow` looked like "the pointer changed
  something" on a control that ignores the pointer), and it clicked the first
  `.ah-select-chip` after a disabled one had been mounted before it, which opened
  nothing and turned `:root .ant-select-item` into a phantom dead rule.

Mounting the disabled variants also closed the last three **unverified** families:
the gallery now renders a dot Badge, a vertical Divider and a `type="link"`
Button, and the audit reports `0 unverified` for the first time.

## Keyboard focus (M3)

M3 publishes the focus indicator as a component of its own — material-web ships
it as `md-focus-ring`, with its own token set — and two of its values are not what
memory supplies. The ring is **`secondary`**, not `primary`, and it does not
appear at its resting width: it grows to 8px over the first quarter of
`duration-long4` and settles back to 3px over the remaining three quarters, on
the emphasized curve.

`tokens/_md-comp-focus-ring.scss` (the values) and
`focus/internal/_focus-ring.scss` (the choreography) are the sources;
`gen_tokens.py`'s `focusRing` family carries all six numbers and `index.css`
spends them as one `outline` plus two keyframes:

```css
:focus-visible,
.ant-btn:focus-visible:not(:disabled), /* + switch, segmented, slider, chip arms */
.ant-select.ah-select-chip:has(:focus-visible) {
  outline: var(--ah-c-focus-ring-width) solid var(--ah-c-focus-ring-color);
  outline-offset: var(--ah-c-focus-ring-outward-offset);
  animation-name: ah-focus-grow, ah-focus-shrink;
  animation-duration: calc(var(--ah-c-focus-ring-duration) * 0.25),
    calc(var(--ah-c-focus-ring-duration) * 0.75);
  animation-delay: 0s, calc(var(--ah-c-focus-ring-duration) * 0.25);
}
```

Measured over 5 routes × 2 themes (`--focus`, 98 focusable elements): every ring
is `3px` of `#625b71` (light) / `#ccc2dc` (dark) at a `2px` offset, the
choreography times as `150ms` + `450ms` after a `150ms` delay, and no element's
own `border-radius` changes when it receives focus. Four of those elements — a
Select's inner input — delegate the ring to the chip that draws their box, which
is why the gate treats "no ring here, a ring on an ancestor" as a pass rather
than a failure.

The sweep has two channels now, and the second one exists because the first
could not see what a keyboard user sees. The synthetic pass calls
`element.focus()` over 98 nodes; the keyboard pass presses <kbd>Tab</kbd> through
each route (and through an open dropdown, which is the only way a menu item
exists at all). The last run: **540 nodes examined, 406 of them by keyboard, 26
skipped as "focusable but with no box" — those are judged by the keyboard pass
instead — 44 delegating their ring to a larger box, 0 defects.** The three
mutations above were each re-introduced on purpose, one at a time, and the gate
reported antd's ring on the segmented item, antd's ring on the menu items and
the slider's second indicator before it was reverted.

`prefers-reduced-motion: reduce` skips the pulse without losing the ring, which
the existing block's `animation-duration: 0.001ms !important` is not obviously
enough to guarantee — so it was measured rather than assumed. Same element, same
focus call: with `no-preference` the two animations are running (`150ms` and
`450ms` after a `150ms` delay) and the width reads `0px` at t=0 and `5px` at
250ms on its way to 3; with `reduce` the element reports **no** animations and
`3px` of `secondary` at a `2px` offset immediately.

Four things this replaced, all measured first:

1. `2px solid var(--ah-accent)` — our thickness and our role.
2. `border-radius: 4px` on `:focus-visible`, which rewrote the radius of four
   elements (`.ah-searchbar__input`, two `.ant-select-input`s, and the slider
   handle, whose ring should be a circle) the moment they took focus.
3. antd's `--ant-color-primary-border`, the colour its algorithm derives, which
   equalled no token in either theme — `rgb(194, 189, 201)` in light, and a
   *different* derived grey in each dark surface (`rgb(76, 70, 91)` on a menu
   item, `rgb(29, 27, 32)`-adjacent values elsewhere; an earlier version of this
   note said "the same in both themes", which the review falsified). Its rule is
   `:where(.hash).ant-btn:not(:disabled):focus-visible` — `:where()` contributes
   nothing, but the three remaining class/pseudo-class levels make it (0,3,0),
   above a bare `:focus-visible`. The selector arms above match that specificity
   and sit later in the document; the Select's own halo rule is (0,4,0), which is
   why its arm is written as a chip rule rather than a component hint.
4. Three places a keyboard user can reach and the first version of the gate could
   not see, all found by the independent review: a **dropdown menu item**, whose
   ring was antd's (its rule is
   `.ant-dropdown .ant-dropdown-menu .ant-dropdown-menu-item:focus-visible`,
   (0,4,0)); a **segmented control**, where our ring was computed on a `0x0`
   `opacity: 0` input that cannot be seen while antd's grey showed on the 52×38
   item — and where antd only marks the item focused for a *real* key focus, so
   the sweep has to press <kbd>Tab</kbd> to see it; and a **slider handle**, which
   showed our round ring and antd's square one at the same time because antd
   paints its indicator on the handle's `::after`. All three are fixed and all
   three are now in the gate: it opens the menu with the keyboard, walks each
   route with <kbd>Tab</kbd>, resolves a focusable node to the box the reader
   sees, and reads pseudo-element indicators by `outline-style` (antd's
   transitions in from `0px`, so a width check reads zero at t=0).

A fifth surface came from *extending the sweep* rather than from the review: the
session-detail route (found by asking the API for a real session id — it is not
one of the five list routes) carries antd's `Pagination`, whose own focus rule is
`:where(.hash).ant-pagination:not(.ant-pagination-disabled)
.ant-pagination-item:focus-visible` — (0,4,0) again, painting
`rgb(194, 189, 201)` at a 1px offset while our grow animation passed through it.
Six arms cover the pager, and the sweep is green on that route.

That extension also exposed a flaw in the *measurement*, which is worth writing
down because it produced a colour that belonged to no rule: `settle()` finished
only the `ah-focus-*` animations, so a reading taken while the cockpit's
`outline-color`/`outline-offset` transition was still interpolating reported
`rgb(37, 34, 41) at 1px` on the pager's next button — about 15% of the way from
antd's `rgb(29, 27, 32)` to our `rgb(98, 91, 113)`. `settle()` now finishes every
*finite* animation (infinite ones, like the spinner, are left alone), and the
same button reads `3px` of `secondary` at `2px`.

`scripts/audit_component_rules.py --focus` is the check, and it refuses an empty
sweep. Its decision logic (`focus_defects`) is a plain function so
`tests/test_tokens_components.py` can feed it broken evidence: antd's grey, a
squared radius, a missing ring and a theme that did not apply all fail it. The
gate was then made to fail for real by pointing the ring at `primary` and
rebuilding: it exited 1 and reported `rgb(103, 80, 164)` against the expected
`rgb(98, 91, 113)` in light, and `rgb(208, 188, 255)` against `rgb(204, 194, 220)`
in dark.

## Depth (M3)

M3 publishes elevations in dp (`0/1/3/6/8/12`) and separates resting surfaces with
an **outline**, not a shadow — level 0 means no shadow at all. Google's web
implementation turns a dp into three shadows (umbra 0.2, penumbra 0.14, ambient
0.12 black); `gen_tokens.py` carries MDC-Web's maps verbatim and emits one
`--ah-elevation-levelN` per level.

Where they are spent: nothing in the app gets a shadow for decoration. antd's
elevated surfaces (popover, dropdown, menu, tooltip, dialog, message) take levels 2
and 3 through `ConfigProvider`'s `boxShadowSecondary`/`boxShadow`; a hovered row
takes level 1, which is the M3E lift. Cards, chips, code, insets and bars stay
level 0 and are drawn with `--ah-line`, verified at rest as `box-shadow: none`.

## Type scale (M3)

Seven official roles, each with Google's size, line-height, **tracking** and weight
(`tokens/versions/v0_192/_md-sys-typescale.scss`, rem × 16):

| Role | Size / line | Tracking | Weight | Spent on |
|---|---|---|---|---|
| `title-medium` | 16 / 24 | 0.15px | 500 | markdown `h1` |
| `title-small` | 14 / 20 | 0.1px | 500 | session title |
| `body-medium` | 14 / 20 | 0.25px | 400 | body, user bubble, assistant, markdown |
| `label-large` | 14 / 20 | 0.1px | 500 | markdown `h2`–`h4`, `strong`, `th` |
| `body-small` | 12 / 16 | 0.4px | 400 | meta, faint, numerals, reasoning, tool call, markdown table |
| `label-medium` | 12 / 16 | 0.5px | 500 | uppercase labels, identity chip, tool-call header |
| `label-small` | 11 / 16 | 0.5px | 500 | mono-only: latin identifiers beside `font-mono` |

The stylesheet sets no literal pixel size — it reads the role's four values from
`--ah-type-<role>-{size,line,tracking,weight}` — and weights are 400 or 500 only,
because M3 defines nothing heavier. Before this, `13.5px`, `13px`, `12.5px`,
`font-weight: 600` and a hand-rolled `letter-spacing: 0.04em` were doing the work.

Tracking is a Latin optimisation, so CJK-authored prose (`.tx-user`, `.ah-md`
content) is the one place the role's tracking is not wanted; that is in the
deviation table above rather than in a silent override. `label-small` at 11px is
the single role under the CJK floor, marked `mono_only` in `tokens.json`, and both
the generator's gate and `test_font_floor_is_enforced_across_the_frontend` refuse
to let it be used without a mono family.

## Motion (M3E)

The cockpit follows Material 3 Expressive, whose motion is a *contract*, not
styling. Durations and the standard/emphasized/linear curves are Google's, copied
from material-web's generated token file (`tokens/versions/v0_192/_md-sys-motion.scss`).

**M3E's own motion primitive is a spring, and Google publishes it — just not in
material-web.** The official damping-ratio + stiffness pairs live in androidx
material3's token files (`tokens/{Expressive,Standard}MotionTokens.kt`, v0_14_0,
reached through `MotionScheme.kt`): expressive spatial fast `0.6/800`, default
`0.8/380`, slow `0.8/200`; standard `0.9/1400`, `0.9/700`, `0.9/300`; effects in
both schemes `1.0` with `3800/1600/800`. CSS cannot express a spring, so
`gen_tokens.py` **samples** each one — the closed-form damped-oscillator response,
24 stops out to the settle time — into a `linear()` easing, and ships the settle
duration plus a `cubic-bezier` fallback beside it. `expressive-over` /
`expressive-out` are now that fallback tier, not the motion vocabulary.

`theme.ts` injects them as custom properties (`--ah-motion-duration-short3`,
`--ah-spring-standard-fast-spatial-easing`, …) for both themes, and hands the
duration/easing pairs to antd, so an antd popup and a hand-written row never
disagree about what a spring means.

One subtlety worth knowing before editing it: a `var()` that resolves to a
function the engine does not support makes the whole declaration **invalid at
computed-value time**, and that does *not* fall back to the previous declaration —
so the sampled curve is selected by `@supports (transition-timing-function:
linear(0, 1))`, which re-points the `--ah-ease-*` aliases, rather than by cascade
order.

How the springs are spent — the rule `index.css` follows:

| Surface | Spring | Measured |
|---|---|---|
| press / hover feedback (recurring) | `standard-fast-spatial` / `standard-fast-effects` | 240 ms / 160 ms |
| a row or chip *appearing* | `standard-default-spatial` | 320 ms |
| a view or panel changing (prominent) | `expressive-default-spatial` | 440 ms, peaks at 1.015 |
| hovering a *surface* (outline firms up) | `standard-fast-effects` | 160 ms |
| a surface resizing (progress, gauge) | `standard-default-spatial` | 320 ms |
| a container unfolding (sub-sessions) | `expressive-fast-spatial` | 360 ms, peaks at 1.094 |
| an endless loop (skeleton shimmer) | *not a spring* — `extra-long4` + `linear` | 1000 ms |

Standard is used for the recurring, utilitarian interactions and expressive for
the prominent one, which is the distinction M3E draws between its two schemes.

Two values are ours, not Google's, and both are labelled as such *in `tokens.json`
and gated by `gen_tokens.py`*: the `cubic-bezier` fallbacks for the springs, and
`motion.stagger.row` (`--ah-motion-stagger-row`, 12 ms — M3 publishes no stagger
token, but the list rhythm still deserves an owner). The stagger is capped at the
eighth row *of a list*: past that a delay stops being a flourish and becomes a
wait. It is pure CSS `nth-child`, so the counter is per `<ul>` and a domain-grouped
view restarts the rhythm per group.

Two cascade rules are load-bearing here, because breaking either is silent:

- An **unlayered** element rule beats *every* cascade layer regardless of
  specificity. `index.css`'s `button { transition: … }` is unlayered and
  Tailwind's `.transition-*` utilities are layered, so the pressable shorthand
  decides whether a utility can animate at all: `opacity` is in that list
  because the copy button relies on it.
- A class shorthand outranks the element one, so `.ah-row` (many rows are
  `<button>`s) repeats the pressable property list rather than inheriting it.

Adding or changing motion is a token change first: edit `gen_tokens.py`, rerun
it, rebuild, and the new timing reaches CSS, antd and the tests together. Motion
is deliberately absent where it would lie: chips answer no press (they are
labels, not controls), and the freshness dot does not pulse (a permanently
moving element reads as an alarm and breaks screenshot automation).

## Components (M3)

### Round 2: the shape of the page, not just of its controls

Round 1 tokenised every control and the verdict was still "not Google's level",
because what reads as Material is not the button radius — it is what the page is
*made of*. Measured against Google's component set, four surfaces had no M3
structure at all:

| Was | Is | Official source |
|---|---|---|
| a full-width antd `Segmented` for navigation | a `PrimaryNavigationTabTokens` tab row: 48dp tabs on `surface`, a **3dp primary indicator** under the active one, `title-small` labels, primary / on-surface-variant ink |
| an antd `Input.Search` — a 32px rectangle with a square button bolted to its edge | a `SearchBarTokens` docked search bar: **56dp, corner-full**, `surface-container-high` at elevation 3, a body-large input, an on-surface leading icon and a 30dp avatar slot |
| 118 bordered cards | `ListTokens` list items: **no border**, 16dp leading space, a state layer, and the `4 → 12 → 16` corner morph |
| two antd `Select`s and a `Button` | `FilterChipTokens` chips — 32dp, corner-medium at rest and **corner-full once a value is chosen** — over a `MenuTokens` dropdown (`surface-container`, corner-extra-small, elevation 2) |
| a `.ah-bar` toolbar (a 1px rule) | a `DockedToolbarTokens` strip: 64dp of `surface-container`, 16dp leading and trailing, spacing from the published 4–32dp band |
| an antd `Spin` | `LoadingIndicatorTokens`: a 48dp corner-full `primary-container` container with a 38dp `on-primary-container` active shape |
| a section card whose *header* was a full-width `--ah-*-container` strip | the card's own surface with a **4px tone rule** at the header's leading edge | M3 publishes no card header, but it does publish what a header is *for*: a `title-small` label on the card's surface, and status as ink on a container rather than as a filled band. A 30px `ok` strip reads as a solid green bar and was the loudest thing on the transcript screen |
| four identical pills in the app bar | one icon button that opens a menu | theme and language are *settings*, not filters: `IconButtonTokens` + `MenuTokens` is the pattern, and a segmented button is for one mutually exclusive choice — which is what the two that remain (search mode, grouping) actually are. The bar is also narrower for it: the smallest breakpoint it wraps at stops at 115px instead of 161px |
| an M3 tab indicator travels between its tabs | one shared element, positioned by `App.tsx` | Material allocates a single indicator and animates its offset, which a per-tab pseudo-element cannot do — a rule can fade its own indicator in, it cannot move it to another tab. This is the one piece of geometry the *app* owns rather than the stylesheet, because `theme.ts` cannot measure anything; the size, corner and colour it is drawn with are still tokens. Measured: `translate` 0 → 327px with **7 intermediate positions** and the spatial spring's fast middle (26 → 184 → 257) |
| a `Tag` at `font-weight: 600` in the table header | `label-large` (500) | M3 publishes no 600. antd's rule lives in antd's runtime stylesheet, so the source-scanning weight gate could not see it; a computed-value sweep of the rendered page could, and it is now part of `scripts/audit_component_rules.py` |
| the vendor's empty-state illustration | `.ah-empty__mark`: a 48dp `corner-full` container in `surface-container-high` with a 24dp mark in `on-surface-variant` | `Empty` drew a 184×152 SVG at a fixed 140px, in the vendor's words, carrying a `<title>` that announced the state a second time to a screen reader. M3 publishes no empty-state component, so ours is a composition and says so — and its ink pair (`text2` on `surface2`) is one the contrast test already gates |
| `List`'s own empty state | the list is mounted only when it has rows | the inbox drew our empty state *and* `locale.emptyText` underneath it. That was invisible while both were the vendor's illustration and obvious the moment one stopped being; `locale={{ emptyText: null }}` does not suppress it |
| antd's own banner palette for an `Alert` | a tonal container with `text1` on it — the same pattern `.ah-tonal-*` uses elsewhere | M3 publishes no banner, so this is ours and says so. antd's warning palette made the interruption banner the loudest thing on the transcript screen, amber-on-olive, with a contrast nobody had checked; ours is AA-gated against `text1` by `tests/test_tokens_contrast.py`. The `warn`/`ok` containers themselves are ours for the same reason they always were: M3 has no success or warning role |
| antd's `Tag color="green"` preset palette | `.ah-tag` with four tones, each one of our AA-gated containers | the preset API *is* the bug this file opens with, and it had survived in five places across three views. Measured: `read` rendered **3.37:1** in the light theme and 7.04:1 in dark — one theme passing and the other not is exactly what a spot check misses, and antd's derived pairs were covered by no gate at all. The colour gate only knew the three preset names that *do not exist*; it now knows every name antd resolves |

The nav is why tokens alone could not get there: a segmented button is the right
control for "which filter" and the wrong one for "which of five screens am I on".
Corner-radius tuning does not fix a control that is the wrong component.

**What this round cost, in honesty:** the list row keeps a `surface-container-low`
fill where `ListTokens.ItemContainerColor` says `surface` (a 118-row screen needs
a resting fill to scan); the loading indicator morphs its *corner* rather than
along M3E's shape path, because that morph is a Compose path animation CSS cannot
express; and the search bar's placeholder borrows the supporting-text role,
because SearchBarTokens publishes no placeholder ink. All three are in the
deviation register below.

Measured on the built bundle: the search bar computes `56px` / `9999px` /
`rgb(33,31,38)` with the level-3 recipe; a tab's active indicator is a 3px
primary bar; a filter chip is `32px` at `12px`, opening to `9999px` on
`secondary-container` once chosen; the docked toolbar is `64px` on
`surface-container`; a `Select` wearing `.ah-select-chip` is `32px` at `12px`
with a 1px `outline-variant` border, and its dropdown is `4px` on
`surface-container` with the level-2 recipe.

Tokens describe a *surface*. A control is made of anatomy — height, padding, icon
size, corner, the corner it morphs to while held — and until the m3components
slice that anatomy was antd v6's while the colours were ours. Measured before:
a 32px button with `border-radius: 12px`, a switch with a 2px-radius knob, a 3px
progress bar with square ends and no stop indicator, a list row that *lifted* on
hover. None of those is Material 3, and none of them was checkable against
Material 3, because the number lived in a stylesheet rather than in the contract.

Now it lives in the contract. `scripts/gen_tokens.py` carries a `component`
block — 22 families, each naming the files it came from — whose values are
**references** rather than copies:

```
@shape:sm          → the shape scale (8px)
@corner:xs-top     → a composed corner (`--ah-corner-extra-small-top`)
@role:primary      → an official colour role (`var(--ah-primary)`)
@type:label-large  → all four `var(--ah-type-label-large-{size,line,tracking,weight})`
@elev:level3       → an elevation recipe
@spring:standard-fast-spatial → a spring's duration and easing pair
```

`build()` refuses to run if a reference does not resolve, so renaming a rung of
the shape scale cannot leave a component pointing at nothing — which is how
`shape.pill` went missing once already. `theme.ts` flattens the block into
`--ah-c-<path>` custom properties (camelCase → kebab-case: `listItem.height.oneLine`
→ `--ah-c-list-item-height-one-line`), and `m3.css` reads them.

**One owner per property.** antd keeps behaviour — focus management, the keyboard
model, aria, Table virtualisation — and keeps any property it exposes as a
*named* token, which `antdConfig()` now sets from the same token file
(`Button.paddingInline` from `button.sizes.small.leading`, `Switch.trackHeight`
from `switch.track.height`, `Table.cellPaddingBlock` from the spacing scale, and
so on). `m3.css` owns what antd has no token for: the press shape morph, the
state-layer composition, the chip families, the list-item morph, the floating
label, the progress stop.

That paragraph used to end "there is no property with two owners, and no property
with none", and an independent review measured it false: `height` and
`padding-inline` on a button are set by the antd *token* and by `m3.css`, and the
one that wins is the higher-specificity rule rather than the token. The honest
version is that the two agree because both read the same token file — which is a
checkable statement, and not the same claim. The same review caught the
consequence: the documented `size="large"` → M3 *medium* (56px) mapping had never
worked, because `:root .ant-btn.ant-btn` outranks antd's own `.ant-btn-lg`. Both
are fixed, and the second is now measured rather than asserted.

Where antd's own stylesheet is the obstacle rather than the owner, the override
is deliberate and commented: `:root .ant-btn.ant-btn` is (0,3,0) against antd's
`.css-<hash>.ant-btn-compact-item` at (0,2,0), because a plain `.ant-btn` ties
and then *loses*: antd injects its styles at runtime, i.e. after this bundle.

**The shape morph is the point**, so it gets its own rule and its own numbers.
Button{Small,Medium,Large}Tokens publish `ContainerShapeRound: corner-full` and
`PressedContainerShape: corner-small/medium/large`; `ListTokens` publishes
`ItemContainerExpressiveShape: corner-extra-small`, `ItemHoveredContainerExpressiveShape:
corner-medium` and `ItemPressedContainerExpressiveShape: corner-large`. Both are
spent as geometry, so both animate on a spatial spring and are zeroed by
`prefers-reduced-motion` like everything else. They are also the reason the
generic `button:active { transform: scale(0.97) }` is retired on these elements:
M3 answers a press with a corner and a state layer, not by shrinking the thing
the reader is aiming at.

Measured on the built bundle in headless Chromium (dark theme):

| Surface | Rest | Hovered | Pressed |
|---|---|---|---|
| filled button | `40px`, `9999px`, `rgb(208,188,255)` on `rgb(56,30,114)`, `rgb(0,0,0)` shadow | 8% layer, level-1 shadow | corner `8px`, 12% layer, level-0 |
| outlined button | `40px`, `9999px`, transparent, `rgb(202,196,208)` | 8% layer, **no** shadow | corner `8px`, 12% layer |
| list row | corner `4px`, no shadow | corner `12px`, 8% layer | corner `16px`, 12% layer, `transform: none` |
| top app bar | `64px` on `rgb(33,31,38)`, title 22/28 weight 400 | — | — |
| segmented | `40px`, `9999px`, 1px `rgb(147,143,153)` | — | selected `rgb(74,68,88)` on `rgb(232,222,248)` |
| switch, off → on | `52×32`, 2px outline, handle `16px` | — | handle `24px` at `inset-inline-start: 20px` |

**The consumption gate is the one that keeps this honest**, and it runs twice.
`tests/test_tokens_components.py` reimplements `theme.ts`'s flattening and asserts
the stylesheet's `--ah-c-*` references and the token file's leaves are *equal*
sets — 375 properties, neither side with an orphan. The browser probe asserts the
same thing against the *running page*: it reads the injected `<style id="ah-tokens">`
and the loaded CSSOM, which is the only way to catch a divergence between the two
implementations of the transform. Both found real defects on the way in: three
keys were written `icon_colour` where the CSS read `icon-color`, and a probe run
showed an outlined antd button painted with the filled container.

It is necessary and it is not sufficient, and an independent review made that
concrete: **a rule can read every token it names and still apply to nothing.**
`.ant-tooltip-inner` is a v5 class name — v6 renders `.ant-tooltip-container` —
so the rule was dead CSS that satisfied the gate perfectly. The review then found
four more of the same shape (`.ant-modal-content`, `.ant-progress-bg`/`-inner`,
`.ant-checkbox-inner`, `.ant-radio-inner`, `.ant-message-notice-content`), one of
which was live: **a white snackbar with black text over the dark page**, because
v6 renders `message` as `.ant-message-notice`.

The response is a third check, and it needs a browser: a gallery project outside
the repo that mounts every antd family *and* every `.ah-*` class, built against
this worktree's own `theme.ts` and `index.css` through a directory junction, plus
a probe that walks the CSSOM and asks, of every rule that reads a `--ah-c-*`
property, whether its selector matches at least one element. Measured after the
fix: **152 of 222** rules match in the gallery, and the 70 that do not are state
(`:hover`, `:active`, `:disabled`, `:focus-*`), animation-only (`-thumb`,
`-zoom-leave`) or a component the gallery does not mount (`-btn-link`,
`-divider-vertical`). A class name antd does not emit is not on that list.

That probe is now a repo tool rather than a scratch script:

```bash
python scripts/audit_component_rules.py     # needs playwright and `npm ci` in web/
```

It writes the gallery to a temp directory (junctions to `web/node_modules` and
`web/src`, so there is nothing to keep in sync), builds it, opens it in two page
states — a dialog traps the pointer, and a dropdown only exists while it is open
— and merges the results. Its classifier is exercised by a pytest, so the part
that decides *dead* from *unverified* runs in CI even where no browser does.
Measured on the shipped sheet: **224 of 278** rules reach an element, **0**
defects, 3 unverified with a written reason each.

Point it at a running cockpit as well and it sweeps the *rendered product*:

```bash
python scripts/audit_component_rules.py --app http://127.0.0.1:18753/ \
    --route "#/" --route "#/memory" --route "#/threads" --route "#/doctor"
```

That pass collects every distinct computed colour, radius, font size and font
weight on each route and asks whether each one exists in the token table. It is
the only check that can see a value antd *derives*, and it has found three:
`th { font-weight: 600 }` (M3 publishes no 600, and the rule lives in antd's
stylesheet), a status tag at **3.37:1** in the light theme, and a spinner drawn
in `rgb(180,163,220)`, a colour in no token anywhere. Measured now: **2 weights,
3 sizes, 5 radii and 14 colours** distinct across the four routes, **none of them
off-token** — and the counts are printed beside the verdict, because a violation
list is only evidence if the sweep examined something.

Two more gates: the values themselves are an independent hand transcription of
Google's files (so a generator typo fails instead of regenerating a wrong file
that then passes `--check` because both sides moved together), and `m3.css` may
not contain a px length, a hex colour or a bare curve outside a short allow-list.

### The pre-JS first paint

One open question from §8.7 of the brief — a dark theme whose `getComputedStyle`
reports the right colours while `page.screenshot()` renders light — is now closed,
and the answer was not in the compositor.

`--ah-surface-0` is written by `theme.ts`, which is inside the JS bundle. Between
the first byte of navigation and that bundle executing — measured at 44–99 ms on
this machine — `body { background: var(--ah-surface-0) }` is a guaranteed-invalid
substitution, the declaration is dropped, and the page has **no canvas paint at
all**. A capture taken in that window is composited onto the compositor's base
colour, which is white; a DOM read one round-trip later sees the injected tokens
and reports `rgb(20, 18, 24)`. Reproduced at 7/8 cold captures; the alternatives
(background propagation, `color-scheme`, stylesheet order, a stale frame, an
element painted over the DOM) were each falsified by measurement.

The fix is two declarations, and they are **generated** rather than typed:
`scripts/gen_tokens.py` writes `web/src/firstpaint.css` from the same palette, and
`index.css` imports it before any rule that could paint the root. A hand-written
copy would have been a second source of truth, which is the thing `--check`
exists to eliminate. Measured after the fix: **0/8** white, 8/8 at the exact
`rgb(20,18,24)`.

## Why the CLI chips are ours and not antd's

The shipped cockpit passed `Tag color="sky"` and `color="amber"` for zcode and
qodercn-ide. Neither exists as an antd v6 preset, so antd fell back to its
default chip — a light background with white text. Measured in the browser:
**1.1:1**, i.e. the agent identity was invisible on the most-used row in the app.

Preset colour names are a stringly-typed API that fails silently. Owning the
chips makes identity colour a *checked value*: add a parser without adding a
token and `test_every_supported_cli_has_an_identity` tells you.

## Switching themes

- UI: the theme control in the header (system / dark / light), persisted in
  `localStorage["ah-theme"]`.
- Keyboard: `T` cycles the three modes.
- Before first paint: a five-line script in `web/index.html` resolves the mode so
  the page never flashes the wrong background.
- `color-scheme` is set per theme, so native scrollbars, form controls and
  date pickers follow without extra CSS.

### Following the device, and a custom seed

**What "follow the device" can mean on the web.** The platform exposes a
light/dark *preference* (`prefers-color-scheme`) and nothing more — the wallpaper
colour that Android's Material You derives a palette from is not exposed to a
browser, so a web cockpit cannot read it. What it can do, and does:

* a fresh profile with no stored key resolves to `auto` and follows the OS —
  measured under emulated system schemes: `dark` → primary `#d0bcff`, `light` →
  `#6750a4`, `data-theme-mode="auto"` in both;
* flipping the OS scheme **while the page is open** re-themes it without a
  reload (`matchMedia(...).addEventListener("change")` calls `applyTheme` when
  the stored mode is `auto`), and the stored key stays absent — the reader never
  has to choose;
* a stored `dark`/`light` still wins, because a deliberate choice outranks the
  environment.

**A custom seed, derived by Google's own maths.** The header menu's colour
section sets a seed (`localStorage["ah-seed"]`), and the palette is generated at
runtime by `@material/material-color-utilities` — the HCT tonal-palette machinery
Material You itself uses — through `SchemeTonalSpot` at the **2021 spec**, the
spec the shipped baseline was published under. All **49** published roles come
out of it, then the cockpit's own aliases (`--ah-accent`, `--ah-text-1`,
`--ah-surface-*`, …) are resolved exactly as `gen_tokens.py` resolves them at
generation time. Measured: seed `#006a6a` gives light `primary #006a6a`,
`surface #f4fbfa` and dark `primary #80d5d4`, `surface #0e1514`, with `auto` still
switching between the two when the OS flips.

Three things a seed deliberately cannot change: the `ok`/`warn` pair and their
containers (M3 publishes no success or warning role, so they stay ours and
AA-solved against the baseline surfaces), the CLI identity inks (an identity is
a name, not a hue — re-deriving them would make `zcode` stop looking like
`zcode`), and anything measured in px.

**The AA gate, and its honest limit.** A seed is held to the same 4.5:1 check the
hand-authored palette is (`seedContrastReport`, the same alias pairs
`tests/test_tokens_contrast.py` checks), and a seed that fails is refused —
proven by mutation, not by reading: raising the threshold to 10.0 made the menu
report `这个种子会产生不可读的配色… light accent/surface-2 = 5.23:1`, leave
`ah-seed` unset and keep the baseline palette on screen. In practice **no seed
has ever been refused**: ten seeds from `#6750a4` to `#00ff00` all land between
**5.23:1 and 5.30:1**, because `SchemeTonalSpot` pins each role to a fixed tone
and HCT keeps luminance nearly constant across hues. The gate is therefore
insurance against a future spec change or a future bug, not a filter that fires —
and saying so is more useful than implying it protects against user error.

**It is not in the entry bundle.** The library is 107 KB minified; importing it
eagerly added **96.4 KB** to the entry chunk (757.0 KB → 853.4 KB, measured).
It is behind a dynamic `import()` instead: the entry carries only the plumbing
(778.6 KB), the library arrives as its own 129.7 KB chunk, and a probe with no
stored seed measures **0** module chunks fetched while a stored seed makes the
palette the generated one. The first paint after a cold load with a seed shows
the baseline for one frame, which is a complete legible palette, and then the
generated one.

### The device's other requests

Light/dark is not the only thing a platform can ask for. Two more signals are
handled, and both were measured before they were written:

**`forced-colors: active`** (Windows high contrast, and the high-contrast
extension). The state layer is an inset `box-shadow`, and this mode forces
`box-shadow: none` — measured: every control answered the pointer with
`sh: none`, so hover and press produced nothing but the M3E shape morph. The
affordance moves to an outline in *system* colours (`CanvasText` on hover,
`Highlight` on press, inset by 2px so nothing reflows): the brand palette is
supposed to disappear in this mode, the feedback is not. Everything else was
checked rather than assumed — the focus ring survives as
`rgb(55, 0, 110) solid 3px` at a 2px offset (the UA's `Highlight`), the tab
indicator survives as a 3px system-coloured bar, a selected segment still differs
from an unselected one by its forced fill, and the CLI chips fall back to
`Canvas`/`CanvasText`.

That arm is a *list* of families, which is exactly the kind of thing that rots
silently — and the first version did: it named only `.ah-*` classes, and most
buttons in this cockpit are antd `Button`s that never carry one, so the arm
measured no effect at all. `--states` now repeats its pass under
`forced-colors: active` and requires each sampled control to show an outline on
hover and on press, so a family missing from that list is a failure rather than a
silence.

**`prefers-contrast: more`.** The palette is already WCAG-AA, so the honest answer
is not a second palette but stronger *separators*: `--ah-line` is re-pointed at
`--ah-line-strong`, the published rung above it in both themes (`#cac4d0` →
`#79747e` light, `#49454f` → `#938f99` dark). No opacity is invented and the
official 8%/12% state layers are untouched. The rule needs `html:root[data-theme]`
because the generated stylesheet is appended at runtime: a plain `:root` rule
loses on both specificity and order, which is how the first version measured no
change at all.

## Adding a colour

1. Add it to `BASE` in `scripts/gen_tokens.py` for both themes.
2. Reference it as `--ah-<name>` in `theme.ts`.
3. Use it through a class in `index.css` — never as a literal in a component.
4. If it carries meaning (status/severity), assert its contrast in
   `tests/test_tokens_contrast.py`.

## Adding a component token

1. Add the family (or the key) to `COMPONENTS` in `scripts/gen_tokens.py`, with a
   `_source` naming the file it came from — androidx, material-web, or the word
   `Ours`. The generator refuses a family without one.
2. Point at an existing value rather than restating it: `@shape:sm`,
   `@role:on-surface-variant`, `@type:body-medium`, `@elev:level3`,
   `@corner:extra-small-top`, `@spring:standard-fast-spatial`, `@dur:long4`,
   `@ease:emphasized`. The generator refuses a reference that does not resolve.
3. Run `python scripts/gen_tokens.py`, then read the token in `m3.css` as
   `var(--ah-c-<path>)` — the path with `-` between the keys and camelCase folded
   (`listItem.height.oneLine` → `--ah-c-list-item-height-one-line`). `index.css`
   spends component tokens too — the focus ring is global — and the consumption
   gate reads both stylesheets, so a token spent only by the shell is still
   covered.
4. **The consumption gate is exact, so you cannot skip step 3.** Publishing a
   token no rule reads fails `test_stylesheet_reads_exactly_the_published_component_tokens`,
   and so does reading one the generator does not emit. That is deliberate: a
   token that nothing spends is a number pretending to be a contract, and a
   property nothing injects is a control with an undefined value.
5. If the value is a colour role, `test_every_reference_resolves` proves the role
   exists, and the browser probe proves it reaches a computed value.
