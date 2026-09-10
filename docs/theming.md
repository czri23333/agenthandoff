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
| any rendered text size | ≥ 12px (CJK stops being legible below that) |
| any animated property | names a `--ah-motion-*` token, never a literal duration (the `prefers-reduced-motion` block is the one exception: it exists to *zero* durations) |
| reduced motion | `prefers-reduced-motion: reduce` collapses every duration and delay |

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

## Motion (M3E)

The cockpit follows Material 3 Expressive, whose motion is a *contract*, not
styling. Durations and the standard/emphasized curves are Google's, copied from
material-web's generated token file (`tokens/versions/v0_192/_md-sys-motion.scss`);
`expressive-over` / `expressive-out` are ours — M3E's spring feel needs a slight
overshoot that the official curves do not have — and are labelled as additions
in `tokens.json` so nobody reads them as Google values.

`theme.ts` injects them as custom properties (`--ah-motion-duration-short3`,
`--ah-motion-easing-emphasized`, …) for both themes, and hands the same values to
antd, so an antd popup and a hand-written row never disagree about what "300ms
emphasized" means.

How they are spent — the rule `index.css` follows, so a reviewer can check it:

| Surface | Token | Curve |
|---|---|---|
| press / hover feedback | `short2`–`short3` (100–150 ms) | `standard`, `expressive-out` |
| a row or chip *appearing* | `short4` (200 ms) | `standard-decelerate` |
| a view or panel changing | `medium2` (300 ms) | `emphasized-decelerate` |
| hovering a *surface* (outline firms up; no state layer) | `medium1` (250 ms) | `emphasized` |
| a surface resizing (progress, gauge) | `medium1`–`medium2` | `emphasized` |
| an endless loop (skeleton shimmer) | `extra-long4` (1000 ms) | `linear` |

Two tokens are ours, not Google's, and both are labelled as such in
`tokens.json`: `expressive-over`/`expressive-out` (the M3E spring overshoot) and
the `--ah-motion-stagger` step (12 ms, the list rhythm — M3 publishes no stagger
token). The stagger is capped at the eighth row *of a list*: past that a delay
stops being a flourish and becomes a wait. It is pure CSS `nth-child`, so the
counter is per `<ul>` and a domain-grouped view restarts the rhythm per group.

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
