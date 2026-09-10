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
| depth | level 0 (outline, no shadow) unless the surface floats: popover/dropdown/menu/tooltip/dialog take levels 2–3, a hovered row level 1 |
| reduced motion | `prefers-reduced-motion: reduce` collapses every duration and delay |

### Where this deliberately differs from Google

"Official" needs a "where we differ, and why" beside it, or the next reader has to
re-derive every judgement.

| Official | Ours | Why |
|---|---|---|
| Roboto (`md-ref-typeface` plain/brand) | the system stack | local-first: no webfont means no network at startup and no FOUT |
| HCT palette generation from a seed | hand-authored sRGB, AA-gated | generating roles would re-brand every colour; the palette is a product decision, not a derivation |
| native springs (Compose `SpringSpec`) | `linear()` sampling of the official damping/stiffness pair, `cubic-bezier` fallback | CSS has no spring primitive; the sampling is deterministic and regenerates with the tokens |
| white elevation *overlay* on dark surfaces | the MDC-Web black shadow in both themes | that is what material-web compiles to CSS for the web; our dark surfaces already step lighter (surface0→2), which serves the same purpose |
| tracking applies to every role | CJK-authored prose keeps `letter-spacing: normal` | tracking is a Latin typography device; the roles' numbers are sub-pixel Latin optimisations |
| M3 publishes no `disabled` opacity | `container 12%` / `content 38%`, labelled ours in `tokens.json` | a disabled control has to look disabled; the value is recorded as ours rather than dressed as Google's |
| `label-small` at 11px | 11px only beside a mono family | 11px CJK is illegible; the role is marked `mono_only` and the floor test enforces the pairing |

`tokens.json` is **generated**. Edit `scripts/gen_tokens.py`, then:

```bash
python scripts/gen_tokens.py          # rewrites web/src/tokens.json
python scripts/gen_tokens.py --check  # fails if the committed file drifted
cd web && npm ci && npm run build     # emits into src/agent_handoff/server/static
```

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

## Adding a colour

1. Add it to `BASE` in `scripts/gen_tokens.py` for both themes.
2. Reference it as `--ah-<name>` in `theme.ts`.
3. Use it through a class in `index.css` — never as a literal in a component.
4. If it carries meaning (status/severity), assert its contrast in
   `tests/test_tokens_contrast.py`.
