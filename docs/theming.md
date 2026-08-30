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
| chip border / divider vs surface | ≥ 1.15:1 (visible, not loud) |
| any rendered text size | ≥ 12px (CJK stops being legible below that) |

Regenerate the palette (lightness is solved for, not eyeballed):

```bash
python scripts/gen_tokens.py     # refuses to write if any pair fails the gate
cd web && npm ci && npm run build   # emits into src/agent_handoff/server/static
```

Both steps are CI-checked, so a hand-edited token table that drops below AA
cannot merge.

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
