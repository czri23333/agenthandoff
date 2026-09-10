---
feature: divergent-slice-motion-1
status: designed
updated: 2026-09-09
branch: compose/divergent-slice-motion-1
commits: c033438..HEAD
---

# Divergent Slice Motion 1

## Report

## [S1] Problem
Two evidence-backed defects, both in the M3E layer the cockpit claims to follow:

1. **The documented token regeneration is lossy and destructive.** `docs/theming.md` tells contributors to run `python scripts/gen_tokens.py`; that script's output dict does not contain `shape`, so a run deletes the entire M3E shape scale, and its `CLI_HUES` table is stale by nine CLIs, so the same run drops their identity colours. Evidence: running it turned `web/src/tokens.json` into `110 deletions` including `"shape": { "xs": 4, … }`. `theme.ts` reads shape with hardcoded fallbacks, so the geometry regresses **silently**; the CLI loss at least trips `test_every_supported_cli_has_an_identity`. Nothing in CI compares the committed token file against a fresh run.
2. **M3E is a motion-first design language and the token contract has no motion.** `tokens.json` and `theme.ts` carry 0 motion entries; `index.css` has 3 keyframes and 9 transitions, all with bare `ease`/`linear`. M3's duration scale and standard/emphasized easing curves (official values published in material-web's `_md-sys-motion.scss`) are absent, so every animation is ad-hoc, unversioned, and unverifiable — the same "no token, no contract" shape as the old preset-colour bug that shipped 1.1:1 chips.

## [S2] Design
**One source, generated, checked.** `scripts/gen_tokens.py` becomes the single author of the whole file: it emits `shape` (M3E scale), `motion`, `contrast`, `cli`, `themes`. The `cli` identity list is derived from `agent_handoff.parsers.all_parsers()` (plus `default`), so it can never go stale again; the nine CLIs missing from `CLI_HUES` take their hue from the committed palette (converted to HSL hue) so **no identity colour changes**. A new `--check` mode writes nothing and exits non-zero when the committed file differs from a fresh build.

**Motion is part of the contract, not decoration.** `motion` carries the official M3 token set — durations `short1..4` = 50/100/150/200 ms, `medium1..4` = 250/300/350/400 ms, `long1..4` = 450/500/550/600 ms, `extra-long1..4` = 700/800/900/1000 ms; easings `standard` `cubic-bezier(0.2,0,0,1)`, `standard-accelerate` `(0.3,0,1,1)`, `standard-decelerate` `(0,0,0,1)`, `emphasized` `(0.2,0,0,1)`, `emphasized-accelerate` `(0.3,0,0.8,0.15)`, `emphasized-decelerate` `(0.05,0.7,0.1,1)` — plus two documented expressive overshoot curves (`expressive-over` `(0.34,1.4,0.64,1)`, `expressive-out` `(0.22,1.2,0.36,1)`) for the M3E spring feel, marked in the token table as ours rather than Google's. `theme.ts` emits them as custom properties (`--ah-motion-duration-*`, `--ah-motion-easing-*`) for both themes; `index.css` consumes tokens and keeps no bare duration outside the token block. Tests assert the committed file is byte-identical to a fresh run and that motion values are well-formed, so a hand edit or a lossy generator fails loudly.

**Applied motion, with reduced-motion substitutes.** Surfaces: view enter (fade + 4 px rise), session rows (short entrance, no per-row stagger beyond 6 rows), row hover state layer, card hover border/elevation, expand/collapse (grid-template-rows), progress and gauge transitions, chip press. The existing global `prefers-reduced-motion: reduce` override stays and gains per-property substitutes where a fade is a legitimate reduction of a slide.

## [S3] Out of Scope
Changing any palette value; adding JS animation libraries (CSS-first, zero new runtime deps); antd's internal component motion beyond the tokens passed through `ConfigProvider`; layout or information-architecture changes; the asar-derived message-role geometry already documented in `index.css`. `scroll-behavior: smooth` stays (it is already inside the reduced-motion override).

## Tasks
- [ ] T1: Generator is complete and lossless — acceptance: `gen_tokens.py` emits `shape`, `motion` and a registry-derived `cli` list; `uv run python scripts/gen_tokens.py` produces a byte-identical `tokens.json` (`git diff` empty) and `--check` exits 0 on the committed file, non-zero after a one-byte edit (covers: S2)
- [ ] T2: Drift + shape gate in tests — acceptance: a test asserts the committed `tokens.json` equals a fresh generator run and that every motion duration/easing is well-formed; deleting `shape` or a `cli` entry from the committed file makes it fail (covers: S2; depends: T1)
- [ ] T3: Motion tokens reach CSS — acceptance: `theme.ts` emits `--ah-motion-duration-*` and `--ah-motion-easing-*`; the built bundle contains the official values; `npx tsc -b` and `npm run build` clean (covers: S2; depends: T1)
- [ ] T4: Motion applied with reduced-motion branches — acceptance: the listed surfaces animate using token durations/easings, browser-measured computed styles match the tokens, and with `prefers-reduced-motion: reduce` emulated every duration collapses; screenshots captured (covers: S2; depends: T3)
- [ ] T5: Docs — acceptance: `docs/theming.md` documents the motion contract and the regenerated-file rule; `pytest`, `evidence --check`, `conformance --check` green (covers: S2; depends: T2, T4)
