"""Author web/src/tokens.json: palettes, M3E shape scale and the motion tokens.

    python scripts/gen_tokens.py            # regenerate after changing a hue
    python scripts/gen_tokens.py --check    # fail if the committed file drifted

``tokens.json`` is the committed source of truth (reviewable, diffable); this
script is how it is made, kept in the repo so a contributor can reproduce it
instead of trusting a blob of hex codes. The gate:

  * every text tier on every surface          >= 4.5:1  (AA normal text)
  * every CLI identity fg on its badge bg     >= 4.5:1, in both themes
  * borders / focus rings / large text        >= 3:1
  * shape scale strictly increasing, `full` at Google's 9999px, composed corners resolvable
  * every state opacity a fraction in (0, 1); every elevation level has a shadow recipe
  * typescale roles: line-height above size, weight 400/500, nothing under the 12px CJK
    floor unless it is marked mono-only
  * motion values well-formed; every spring's damping/stiffness in range and its sampled
    easing a `linear()` that runs 0 → 1

The whole file — shape and motion included — comes from here, because it did
not: `shape` used to live only in the committed JSON, so running this script
deleted the M3E radius scale, and `CLI_HUES` was stale by nine CLIs, so it
dropped their identity colours too. `--check` exists so that can never happen
quietly again: it compares the committed file with a fresh build and fails on
any drift.

Hues keep each CLI's existing identity; lightness is *solved for*, because
eyeballing contrast is exactly how the shipped cockpit ended up drawing the
`zcode` and `qodercn-ide` badges at 1.1:1 (white text on a near-white chip).
Nine newer identities (see CLI_PINNED) predate this script and are kept
verbatim — they still pass the same AA gate, they are just not hue-derived.
"""

from __future__ import annotations

import colorsys
import json
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "web" / "src" / "tokens.json"

# CLI identity hues (kept from the original palette; lightness is derived).
CLI_HUES: dict[str, str] = {
    "zcode": "#38bdf8",
    "claude": "#f0776a",
    "codebuddy": "#52c41a",
    "codebuddy-cn": "#86efac",
    "qoderwork": "#fa8c16",
    "qoderwork-cn": "#d4b106",
    "qodercn-ide": "#f5a623",
    "qwenwork": "#b37feb",
    "dsh": "#13c2c2",
    "kimi": "#eb2f96",
    "codex": "#5b8def",
    "default": "#8c8c8c",
}

# Identities that predate this script: they were hand-written into tokens.json
# when their parser landed, so no hue reproduces them exactly (verified by
# inverting badge()) and deriving one would silently re-brand nine chips. Kept
# verbatim, and still subject to the same AA gate below. Fold them into
# CLI_HUES the next time these identities are re-designed on purpose.
CLI_PINNED: dict[str, dict[str, dict[str, str]]] = {
    "workbuddy": {
        "dark": {"fg": "#2dd4a8", "bg": "#123b32", "border": "#2dd4a8"},
        "light": {"fg": "#0c6b51", "bg": "#dcf7ee", "border": "#12a379"},
    },
    "opencode": {
        "dark": {"fg": "#e8b04b", "bg": "#3f3117", "border": "#e8b04b"},
        "light": {"fg": "#8a5d0b", "bg": "#fbeecd", "border": "#b57d12"},
    },
    "qoderwake": {
        "dark": {"fg": "#e07bd0", "bg": "#43263e", "border": "#e07bd0"},
        "light": {"fg": "#a51e8a", "bg": "#fbe8f6", "border": "#c936ab"},
    },
    "qoder-ide": {
        "dark": {"fg": "#6fb6ff", "bg": "#1f3a52", "border": "#6fb6ff"},
        "light": {"fg": "#1867c2", "bg": "#e3effc", "border": "#2f7fd6"},
    },
    "qoderwake-cn": {
        "dark": {"fg": "#d48af5", "bg": "#3a2447", "border": "#d48af5"},
        "light": {"fg": "#7d1fb0", "bg": "#f5e7fc", "border": "#9a35cf"},
    },
    "cherrystudio": {
        "dark": {"fg": "#fb7185", "bg": "#4a1f28", "border": "#fb7185"},
        "light": {"fg": "#be123c", "bg": "#ffe4e6", "border": "#e11d48"},
    },
    "qoderwork-app": {
        "dark": {"fg": "#fb9a2e", "bg": "#4a3520", "border": "#fb9a2e"},
        "light": {"fg": "#9a4e03", "bg": "#fff1e0", "border": "#c26104"},
    },
    "qoderwork-cn-app": {
        "dark": {"fg": "#fbe04a", "bg": "#45401f", "border": "#fbe04a"},
        "light": {"fg": "#776705", "bg": "#faf6dc", "border": "#97850a"},
    },
    "qwenwork-app": {
        "dark": {"fg": "#c9a6f2", "bg": "#413654", "border": "#c9a6f2"},
        "light": {"fg": "#6d1fc4", "bg": "#f5eefd", "border": "#6d1fc4"},
    },
}

# M3E tonal containers: the semantic colour mixed into surface1. One strength per
# theme reproduces every shipped container byte-exactly (dark 0.179, light 0.16 —
# measured by inverting tint(), not eyeballed), so they are derived rather than
# pinned: a palette edit re-tints the bubbles/chips and the AA gate below
# re-checks the text that sits on them.
CONTAINER_STRENGTH: dict[str, float] = {"dark": 0.179, "light": 0.16}

# ── M3 official layers ───────────────────────────────────────────────────────
# Sources, all fetched first-hand on 2026-09-10. material-web pins its whole token
# set to design-system v0_192:
#   tokens/versions/v0_192/_md-sys-shape.scss       (corner radii)
#   tokens/versions/v0_192/_md-sys-state.scss       (state-layer opacities)
#   tokens/versions/v0_192/_md-sys-elevation.scss   (elevation levels, in dp)
#   tokens/versions/v0_192/_md-sys-typescale.scss   (type roles)
# M3E's springs are NOT published there; they are androidx material3 token files
# (v0_14_0), reached through MotionScheme.kt:
#   compose/material3/material3/src/commonMain/kotlin/androidx/compose/material3/
#     tokens/{Expressive,Standard}MotionTokens.kt
# The dp→box-shadow recipe is MDC-Web's elevation maps — the same algorithm
# material-web compiles to CSS:
#   packages/mdc-elevation/_elevation-theme.scss

# M3E shape scale (px): the official corner steps plus `full`. Cards take lg,
# controls md, chips full; the message roles reuse the same scale so bubbles and
# cards share one geometry. `full` is Google's `corner-full` = 9999px.
SHAPE: dict[str, int] = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 28, "full": 9999}

# The official *composed* corners, derived from the scale above so a scale edit
# propagates. None means the zero corner: Google publishes these as four-value
# lists (corner-extra-small-top `4px 4px 0 0`, corner-large-start, corner-large-end,
# …), and call sites used to spell them out by hand — `.ah-user-bubble` wrote
# `lg lg 0 lg`.
COMPOSED_CORNERS: dict[str, tuple] = {
    "extra-small-top": ("xs", "xs", None, None),
    "large-top": ("lg", "lg", None, None),
    "large-start": ("lg", None, None, "lg"),
    "large-end": (None, "lg", "lg", None),
    "extra-large-top": ("xl", "xl", None, None),
}

# State layers: the surface's own content colour, composited over it, at Google's
# official opacities. This is what M3 means by feedback — not a brightness filter,
# not a different background colour. `disabled` is NOT in M3's token file; those
# two numbers are ours and are marked as ours wherever they surface.
STATE: dict[str, float] = {"hover": 0.08, "focus": 0.12, "pressed": 0.12, "dragged": 0.16}
STATE_DISABLED: dict[str, float] = {"container": 0.12, "content": 0.38}

# Elevation: M3's official levels in dp, plus the MDC-Web umbra/penumbra/ambient
# maps that turn a dp into a CSS box-shadow. Level 0 is no shadow by definition —
# M3 separates resting surfaces with an outline and reserves shadow for what floats.
# MDC's maps run to 24 dp; these are the six levels the M3 scale uses.
ELEVATION_DP: dict[str, int] = {
    "level0": 0,
    "level1": 1,
    "level2": 3,
    "level3": 6,
    "level4": 8,
    "level5": 12,
}
_SHADOW_RGB, _UMBRA_OPACITY, _PENUMBRA_OPACITY, _AMBIENT_OPACITY = (
    "0, 0, 0",
    0.2,
    0.14,
    0.12,
)
_UMBRA: dict[int, str] = {
    0: "0px 0px 0px 0px",
    1: "0px 2px 1px -1px",
    3: "0px 3px 3px -2px",
    6: "0px 3px 5px -1px",
    8: "0px 5px 5px -3px",
    12: "0px 7px 8px -4px",
}
_PENUMBRA: dict[int, str] = {
    0: "0px 0px 0px 0px",
    1: "0px 1px 1px 0px",
    3: "0px 3px 4px 0px",
    6: "0px 6px 10px 0px",
    8: "0px 8px 10px 1px",
    12: "0px 12px 17px 2px",
}
_AMBIENT: dict[int, str] = {
    0: "0px 0px 0px 0px",
    1: "0px 1px 3px 0px",
    3: "0px 1px 8px 0px",
    6: "0px 1px 18px 0px",
    8: "0px 3px 14px 2px",
    12: "0px 5px 22px 4px",
}

# The official type roles this cockpit needs, with M3's size / line-height /
# tracking / weight (the token file's rem values × 16). Sizes are px. `mono_only`
# marks the single role that sits under this repo's 12 px CJK floor: 11 px is
# legitimate for latin identifiers and monospace, and the gate refuses to let it
# be used anywhere a CJK glyph can land.
CJK_FLOOR_PX = 12
TYPESCALE: dict[str, dict] = {
    "body-medium": {"size": 14, "line": 20, "tracking": 0.25, "weight": 400},
    "body-small": {"size": 12, "line": 16, "tracking": 0.4, "weight": 400},
    "label-large": {"size": 14, "line": 20, "tracking": 0.1, "weight": 500},
    "label-medium": {"size": 12, "line": 16, "tracking": 0.5, "weight": 500},
    "label-small": {"size": 11, "line": 16, "tracking": 0.5, "weight": 500, "mono_only": True},
    "title-small": {"size": 14, "line": 20, "tracking": 0.1, "weight": 500},
    "title-medium": {"size": 16, "line": 24, "tracking": 0.15, "weight": 500},
}

# Official M3E springs: a damping ratio and a stiffness. MotionScheme picks
# between the standard and the expressive scheme; CSS has no spring primitive, so
# each spring is *sampled* into a `linear()` easing below and ships a cubic-bezier
# fallback for engines without `linear()`.
SPRINGS: dict[str, dict[str, float]] = {
    "expressive-fast-spatial": {"damping": 0.6, "stiffness": 800.0},
    "expressive-default-spatial": {"damping": 0.8, "stiffness": 380.0},
    "expressive-slow-spatial": {"damping": 0.8, "stiffness": 200.0},
    "expressive-fast-effects": {"damping": 1.0, "stiffness": 3800.0},
    "expressive-default-effects": {"damping": 1.0, "stiffness": 1600.0},
    "expressive-slow-effects": {"damping": 1.0, "stiffness": 800.0},
    "standard-fast-spatial": {"damping": 0.9, "stiffness": 1400.0},
    "standard-default-spatial": {"damping": 0.9, "stiffness": 700.0},
    "standard-slow-spatial": {"damping": 0.9, "stiffness": 300.0},
    "standard-fast-effects": {"damping": 1.0, "stiffness": 3800.0},
    "standard-default-effects": {"damping": 1.0, "stiffness": 1600.0},
    "standard-slow-effects": {"damping": 1.0, "stiffness": 800.0},
}
# Fallbacks are ours, chosen from the official curve set: spatial springs overshoot
# so they approximate to `expressive-out`; effects springs are critically damped
# and match `standard`.
SPRING_FALLBACK: dict[str, str] = {
    "spatial": "cubic-bezier(0.22, 1.2, 0.36, 1)",
    "effects": "cubic-bezier(0.2, 0, 0, 1)",
}
SPRING_SAMPLES = 24
SPRING_SETTLE_TOLERANCE = 0.001

# Motion tokens. Durations and the standard/emphasized easings are Google's,
# copied from material-web's generated token file (design system v0.192):
#   https://github.com/material-components/material-web/blob/main/tokens/versions/v0_192/_md-sys-motion.scss
# `expressive-*` are ours: they exist as the fallback tier for the springs above,
# which CSS cannot express. They are marked as additions here and in tokens.json
# so nobody mistakes them for Google values.
MOTION_DURATIONS: dict[str, str] = {
    "short1": "50ms",
    "short2": "100ms",
    "short3": "150ms",
    "short4": "200ms",
    "medium1": "250ms",
    "medium2": "300ms",
    "medium3": "350ms",
    "medium4": "400ms",
    "long1": "450ms",
    "long2": "500ms",
    "long3": "550ms",
    "long4": "600ms",
    "extra-long1": "700ms",
    "extra-long2": "800ms",
    "extra-long3": "900ms",
    "extra-long4": "1000ms",
}

MOTION_EASINGS: dict[str, str] = {
    # Google's (material-web v0.192)
    "linear": "cubic-bezier(0, 0, 1, 1)",
    "standard": "cubic-bezier(0.2, 0, 0, 1)",
    "standard-accelerate": "cubic-bezier(0.3, 0, 1, 1)",
    "standard-decelerate": "cubic-bezier(0, 0, 0, 1)",
    "emphasized": "cubic-bezier(0.2, 0, 0, 1)",
    "emphasized-accelerate": "cubic-bezier(0.3, 0, 0.8, 0.15)",
    "emphasized-decelerate": "cubic-bezier(0.05, 0.7, 0.1, 1)",
    # Ours (M3E overshoot for press/release and expand/collapse)
    "expressive-over": "cubic-bezier(0.34, 1.4, 0.64, 1)",
    "expressive-out": "cubic-bezier(0.22, 1.2, 0.36, 1)",
}

# Stagger steps, in ms. M3 publishes no such token (its lists do not stagger),
# so this one is ours and is labelled as such — but it lives in the token file
# all the same, so "the rhythm between rows" is a value with an owner and a
# check rather than a literal someone typed into the stylesheet.
MOTION_STAGGER: dict[str, str] = {"row": "12ms"}

# Both shapes below are what the browser actually accepts: a CSS cubic-bezier
# takes exactly four numbers, and its two x control points must lie in [0, 1]
# (y may exceed 1 — that overshoot is the point of `expressive-*`). A gate that
# only checked the prefix would happily ship `cubic-bezier(0.2, 0, 0)`, which
# the browser drops on the floor. The number pattern is CSS's, not Python's:
# `1e-5` is valid and `1.` is not (`CSS.supports` disagrees with `float()` on
# both), and it cannot match `1.2.3`, so the `float()` below cannot raise.
_NUMBER = r"-?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?"
_EASING_RE = re.compile(
    rf"cubic-bezier\(\s*({_NUMBER})\s*,\s*({_NUMBER})\s*,\s*({_NUMBER})\s*,\s*({_NUMBER})\s*\)"
)
_DURATION_RE = re.compile(r"(\d+)ms")


def easing_problem(value: str) -> str | None:
    """Why this value is not a usable cubic-bezier, or None when it is.

    A validator must report, never raise: this function is called from the
    build gate that `--check` and the tests run, so a traceback here replaces
    the one message the contributor needs ("which token, and what is wrong").
    """
    match = _EASING_RE.fullmatch(value)
    if not match:
        return "not cubic-bezier(a, b, c, d) with four plain numbers"
    for group in (1, 3):  # the x control points
        x = float(match.group(group))
        if not 0.0 <= x <= 1.0:
            return f"control-point x {x} is outside [0, 1]"
    return None

# ── M3 baseline colour scheme (official) ─────────────────────────────────────
# Tones verbatim from material-web tokens v0_192 `_md-ref-palette.scss`; the
# role→tone mapping verbatim from `_md-sys-color.scss` (`values-light` /
# `values-dark`). Both fetched 2026-09-10. The *references* are stored, not 48
# hex values per theme, so this stays auditable against Google: the hexes are
# derived, and the derivation is the mapping Google ships.
M3_TONES: dict[str, dict[int, str]] = {
    "primary": {
        0: "#000000", 10: "#21005d", 20: "#381e72", 30: "#4f378b", 40: "#6750a4", 50: "#7f67be",
        60: "#9a82db", 70: "#b69df8", 80: "#d0bcff", 90: "#eaddff", 95: "#f6edff",
        99: "#fffbfe", 100: "#ffffff",
    },
    "secondary": {
        0: "#000000", 10: "#1d192b", 20: "#332d41", 30: "#4a4458", 40: "#625b71", 50: "#7a7289",
        60: "#958da5", 70: "#b0a7c0", 80: "#ccc2dc", 90: "#e8def8", 95: "#f6edff",
        99: "#fffbfe", 100: "#ffffff",
    },
    "tertiary": {
        0: "#000000", 10: "#31111d", 20: "#492532", 30: "#633b48", 40: "#7d5260", 50: "#986977",
        60: "#b58392", 70: "#d29dac", 80: "#efb8c8", 90: "#ffd8e4", 95: "#ffecf1",
        99: "#fffbfa", 100: "#ffffff",
    },
    "error": {
        0: "#000000", 10: "#410e0b", 20: "#601410", 30: "#8c1d18", 40: "#b3261e", 50: "#dc362e",
        60: "#e46962", 70: "#ec928e", 80: "#f2b8b5", 90: "#f9dedc", 95: "#fceeee",
        99: "#fffbf9", 100: "#ffffff",
    },
    "neutral": {
        0: "#000000", 4: "#0f0d13", 6: "#141218", 10: "#1d1b20", 12: "#211f26", 17: "#2b2930",
        20: "#322f35", 22: "#36343b", 24: "#3b383e", 30: "#48464c", 40: "#605d64", 50: "#79767d",
        60: "#938f96", 70: "#aea9b1", 80: "#cac5cd", 87: "#ded8e1", 90: "#e6e0e9",
        92: "#ece6f0", 94: "#f3edf7", 95: "#f5eff7", 96: "#f7f2fa", 98: "#fef7ff",
        99: "#fffbff", 100: "#ffffff",
    },
    "neutral-variant": {
        0: "#000000", 10: "#1d1a22", 20: "#322f37", 30: "#49454f", 40: "#605d66", 50: "#79747e",
        60: "#938f99", 70: "#aea9b4", 80: "#cac4d0", 90: "#e7e0ec", 95: "#f5eefa",
        99: "#fffbfe", 100: "#ffffff",
    },
}

# role -> "family:tone", exactly as `_md-sys-color.scss` maps them.
M3_ROLE_REFS: dict[str, dict[str, str]] = {
    "light": {
        "background": "neutral:98",
        "on-background": "neutral:10",
        "surface": "neutral:98",
        "on-surface": "neutral:10",
        "surface-dim": "neutral:87",
        "surface-bright": "neutral:98",
        "surface-container-lowest": "neutral:100",
        "surface-container-low": "neutral:96",
        "surface-container": "neutral:94",
        "surface-container-high": "neutral:92",
        "surface-container-highest": "neutral:90",
        "surface-variant": "neutral-variant:90",
        "on-surface-variant": "neutral-variant:30",
        "outline": "neutral-variant:50",
        "outline-variant": "neutral-variant:80",
        "primary": "primary:40",
        "on-primary": "primary:100",
        "primary-container": "primary:90",
        "on-primary-container": "primary:10",
        "primary-fixed": "primary:90",
        "primary-fixed-dim": "primary:80",
        "on-primary-fixed": "primary:10",
        "on-primary-fixed-variant": "primary:30",
        "secondary": "secondary:40",
        "on-secondary": "secondary:100",
        "secondary-container": "secondary:90",
        "on-secondary-container": "secondary:10",
        "secondary-fixed": "secondary:90",
        "secondary-fixed-dim": "secondary:80",
        "on-secondary-fixed": "secondary:10",
        "on-secondary-fixed-variant": "secondary:30",
        "tertiary": "tertiary:40",
        "on-tertiary": "tertiary:100",
        "tertiary-container": "tertiary:90",
        "on-tertiary-container": "tertiary:10",
        "tertiary-fixed": "tertiary:90",
        "tertiary-fixed-dim": "tertiary:80",
        "on-tertiary-fixed": "tertiary:10",
        "on-tertiary-fixed-variant": "tertiary:30",
        "error": "error:40",
        "on-error": "error:100",
        "error-container": "error:90",
        "on-error-container": "error:10",
        "surface-tint": "primary:40",
        "inverse-surface": "neutral:20",
        "inverse-on-surface": "neutral:95",
        "inverse-primary": "primary:80",
        "scrim": "neutral:0",
        "shadow": "neutral:0",
    },
    "dark": {
        "background": "neutral:6",
        "on-background": "neutral:90",
        "surface": "neutral:6",
        "on-surface": "neutral:90",
        "surface-dim": "neutral:6",
        "surface-bright": "neutral:24",
        "surface-container-lowest": "neutral:4",
        "surface-container-low": "neutral:10",
        "surface-container": "neutral:12",
        "surface-container-high": "neutral:17",
        "surface-container-highest": "neutral:22",
        "surface-variant": "neutral-variant:30",
        "on-surface-variant": "neutral-variant:80",
        "outline": "neutral-variant:60",
        "outline-variant": "neutral-variant:30",
        "primary": "primary:80",
        "on-primary": "primary:20",
        "primary-container": "primary:30",
        "on-primary-container": "primary:90",
        "primary-fixed": "primary:90",
        "primary-fixed-dim": "primary:80",
        "on-primary-fixed": "primary:10",
        "on-primary-fixed-variant": "primary:30",
        "secondary": "secondary:80",
        "on-secondary": "secondary:20",
        "secondary-container": "secondary:30",
        "on-secondary-container": "secondary:90",
        "secondary-fixed": "secondary:90",
        "secondary-fixed-dim": "secondary:80",
        "on-secondary-fixed": "secondary:10",
        "on-secondary-fixed-variant": "secondary:30",
        "tertiary": "tertiary:80",
        "on-tertiary": "tertiary:20",
        "tertiary-container": "tertiary:30",
        "on-tertiary-container": "tertiary:90",
        "tertiary-fixed": "tertiary:90",
        "tertiary-fixed-dim": "tertiary:80",
        "on-tertiary-fixed": "tertiary:10",
        "on-tertiary-fixed-variant": "tertiary:30",
        "error": "error:80",
        "on-error": "error:20",
        "error-container": "error:30",
        "on-error-container": "error:90",
        "surface-tint": "primary:80",
        "inverse-surface": "neutral:90",
        "inverse-on-surface": "neutral:20",
        "inverse-primary": "primary:40",
        "scrim": "neutral:0",
        "shadow": "neutral:0",
    },
}

# The cockpit's own names, resolved through the official roles. Only two colours
# here are not M3 at all — `ok` and `warn`: M3 has no success/warning roles, so
# they stay ours (AA-solved against whichever surface they land on) and are
# labelled as ours in tokens.json.
SEMANTIC_FROM_ROLES: dict[str, dict[str, str]] = {
    "dark": {
        "surface0": "surface",
        "surface1": "surface-container-low",
        "surface2": "surface-container-high",
        "line": "outline-variant",
        "lineStrong": "outline",
        "text1": "on-surface",
        "text2": "on-surface-variant",
        "text3": "on-surface-variant",
        "accent": "primary",
        "accentContainer": "primary-container",
        "err": "error",
        "errContainer": "error-container",
        "codeBg": "surface-container-lowest",
    },
    "light": {
        "surface0": "surface",
        "surface1": "surface-container-low",
        "surface2": "surface-container-high",
        "line": "outline-variant",
        "lineStrong": "outline",
        "text1": "on-surface",
        "text2": "on-surface-variant",
        "text3": "on-surface-variant",
        "accent": "primary",
        "accentContainer": "primary-container",
        "err": "error",
        "errContainer": "error-container",
        "codeBg": "surface-container-lowest",
    },
}

# Ours: no M3 role for success or warning. Solved for AA against each theme's
# surfaces below, same gate as everything else.
OUR_COLOURS: dict[str, dict[str, str]] = {
    "dark": {"ok": "#7ee2a8", "warn": "#ffd166"},
    "light": {"ok": "#1a7f45", "warn": "#8a6100"},
}


def colour_roles(theme: str) -> dict[str, str]:
    """Every official role for a theme, resolved from the tone references."""
    out: dict[str, str] = {}
    for role, ref in M3_ROLE_REFS[theme].items():
        family, _, tone = ref.partition(":")
        out[role] = M3_TONES[family][int(tone)]
    return out


def base_palette(theme: str) -> dict[str, str]:
    """The cockpit's palette: official roles under our names, plus ok/warn."""
    roles = colour_roles(theme)
    base = {
        name: roles[role]
        for name, role in SEMANTIC_FROM_ROLES[theme].items()
        if role in roles
    }
    base.update(OUR_COLOURS[theme])
    base["scheme"] = theme
    base["placeholder"] = roles["on-surface-variant"]
    return base

TEXT_PAIR_MIN = 4.5
GRAPHIC_MIN = 3.0


# -- colour maths -------------------------------------------------------------
def rgb(hexcolor: str) -> tuple[float, float, float]:
    h = hexcolor.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def to_hex(triple) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in triple)


def lum(color: str) -> float:
    def chan(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(c) for c in rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a: str, b: str) -> float:
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def hsl(color: str) -> tuple[float, float, float]:
    h, lt, s = colorsys.rgb_to_hls(*rgb(color))
    return h, s, lt


def from_hsl(h: float, s: float, lt: float) -> str:
    return to_hex(colorsys.hls_to_rgb(h, lt, s))


def solve(base: str, bg: str, target: float) -> str:
    """Push ``base``'s lightness away from ``bg`` until the pair passes ``target``."""
    h, s, _ = hsl(base)
    upward = lum(bg) < 0.5
    step = 0.01 if upward else -0.01
    lightness = 0.5
    cand = base
    for _ in range(120):
        lightness = max(0.0, min(1.0, lightness + step))
        cand = from_hsl(h, s, lightness)
        if ratio(cand, bg) >= target:
            return cand
        if lightness in (0.0, 1.0):
            break
    return cand


def tint(surface: str, hue: str, strength: float) -> str:
    sr, sg, sb = rgb(surface)
    hr, hg, hb = rgb(hue)
    return to_hex(
        (sr + (hr - sr) * strength, sg + (hg - sg) * strength, sb + (hb - sb) * strength)
    )


def badge(hue: str, surface: str) -> dict:
    strength = 0.22 if lum(surface) < 0.5 else 0.16
    bg = tint(surface, hue, strength)
    return {"fg": solve(hue, bg, TEXT_PAIR_MIN), "bg": bg, "border": solve(hue, bg, GRAPHIC_MIN)}


def cli_ids() -> list[str]:
    """Every CLI that must have an identity, straight from the parser registry.

    The identity list used to be a hand-kept copy beside the parsers, which is
    how nine CLIs ended up missing from this script and deleted from the file
    whenever someone followed the docs and regenerated. Importing the registry
    makes drift impossible: add a parser and the next run demands its hue.
    """
    try:
        from agent_handoff.parsers import all_parsers
    except ImportError as exc:  # pragma: no cover - run from an uninstalled tree
        raise SystemExit(
            "gen_tokens needs the package importable (`pip install -e .`) so the CLI "
            f"identity list cannot silently go stale: {exc}"
        ) from exc
    return [parser.cli for parser in all_parsers()] + ["default"]


CONTAINER_SOURCES: dict[str, str] = {
    "accentContainer": "accent",
    "okContainer": "ok",
    "warnContainer": "warn",
    "errContainer": "err",
}


def containers(theme: dict, strength: float, only: tuple[str, ...] | None = None) -> dict[str, str]:
    """Tonal surfaces: a semantic colour mixed into surface1.

    Only *success* and *warning* containers come from here now. M3 has no such
    roles, so those two stay derived (one strength per theme, measured by solving
    ``tint()`` for its pre-image rather than by eye). The accent and error
    containers are Google's own `primary-container` / `error-container` and are
    taken verbatim from the colour-role map — deriving them would have replaced
    an official value with a hand-rolled approximation that merely looked similar.
    """
    return {
        container: tint(theme["surface1"], theme[source], strength)
        for container, source in CONTAINER_SOURCES.items()
        if only is None or container in only
    }


def elevation_shadow(dp: int) -> str:
    """The MDC-Web box-shadow for an elevation level, from the official maps.

    Three shadows (umbra/penumbra/ambient) at 0.2/0.14/0.12 black — that is the
    recipe material-web compiles to CSS. Level 0 is `none`: M3 has no shadow at
    rest, it has an outline.
    """
    if dp == 0:
        return "none"
    return (
        f"{_UMBRA[dp]} rgba({_SHADOW_RGB}, {_UMBRA_OPACITY}), "
        f"{_PENUMBRA[dp]} rgba({_SHADOW_RGB}, {_PENUMBRA_OPACITY}), "
        f"{_AMBIENT[dp]} rgba({_SHADOW_RGB}, {_AMBIENT_OPACITY})"
    )


def spring_curve(damping: float, stiffness: float) -> tuple[str, int]:
    """Sample a unit-mass spring into a CSS `linear()` easing, plus its duration.

    Closed form of a damped harmonic oscillator released at rest: with
    ``omega0 = sqrt(stiffness)`` and ratio ``zeta``, the response is
    ``1 - e^(-zeta*omega0*t) * (cos(wd*t) + zeta*omega0/wd * sin(wd*t))`` for
    ``zeta < 1`` (``wd = omega0*sqrt(1 - zeta^2)``), and ``1 - e^(-omega0*t)*(1 +
    omega0*t)`` at ``zeta = 1``. The window runs to the settle time — the first
    instant the curve has stayed within a tenth of a percent — so the easing
    reaches 1 instead of being cut off mid-flight.
    """
    omega = math.sqrt(stiffness)

    def response(t: float) -> float:
        if damping >= 1.0:
            return 1 - math.exp(-omega * t) * (1 + omega * t)
        wd = omega * math.sqrt(1 - damping * damping)
        return 1 - math.exp(-damping * omega * t) * (
            math.cos(wd * t) + damping * omega / wd * math.sin(wd * t)
        )

    def settled(t: float) -> bool:
        return all(
            abs(1 - response(t + step * 0.02)) <= SPRING_SETTLE_TOLERANCE for step in range(0, 50)
        )

    settle = 0.1
    while settle < 6.0 and not settled(settle):
        settle += 0.02

    stops = ", ".join(
        f"{response(settle * i / SPRING_SAMPLES):.3f} {i * 100 / SPRING_SAMPLES:.1f}%"
        for i in range(1, SPRING_SAMPLES)
    )
    return f"linear(0, {stops}, 1)", round(settle * 1000)


def build() -> tuple[dict, list[str]]:
    problems: list[str] = []
    ids = cli_ids()
    for cli in ids:
        if cli not in CLI_HUES and cli not in CLI_PINNED:
            problems.append(f"cli {cli} has no identity: add a hue to CLI_HUES")

    themes: dict[str, dict] = {}
    for name in ("dark", "light"):
        theme = base_palette(name)
        for tier in ("text1", "text2", "text3"):
            for surface in ("surface0", "surface1", "surface2"):
                if ratio(theme[tier], theme[surface]) < TEXT_PAIR_MIN:
                    theme[tier] = solve(theme[tier], theme[surface], TEXT_PAIR_MIN)
        for key in ("accent", "ok", "warn", "err"):
            if ratio(theme[key], theme["surface1"]) < TEXT_PAIR_MIN:
                theme[key] = solve(theme[key], theme["surface1"], TEXT_PAIR_MIN)
        theme["placeholder"] = theme["text3"]
        theme["onSurface0"] = theme["text1"]
        theme.update(
            containers(theme, CONTAINER_STRENGTH[name], only=("okContainer", "warnContainer"))
        )
        theme["cli"] = {
            cli: (
                dict(CLI_PINNED[cli][name])
                if cli in CLI_PINNED
                else badge(CLI_HUES[cli], theme["surface1"])
            )
            for cli in ids
            if cli in CLI_HUES or cli in CLI_PINNED
        }
        themes[name] = theme

    for name, theme in themes.items():
        for tier in ("text1", "text2", "text3"):
            for surface in ("surface0", "surface1", "surface2"):
                r = ratio(theme[tier], theme[surface])
                if r < TEXT_PAIR_MIN:
                    problems.append(f"{name}: {tier}/{surface} = {r:.2f}:1")
        for key in ("accent", "ok", "warn", "err"):
            r = ratio(theme[key], theme["surface1"])
            if r < TEXT_PAIR_MIN:
                problems.append(f"{name}: {key}/surface1 = {r:.2f}:1")
        for container in ("accentContainer", "okContainer", "warnContainer", "errContainer"):
            r = ratio(theme["text1"], theme[container])
            if r < TEXT_PAIR_MIN:
                problems.append(
                    f"{name}: text1/{container} = {r:.2f}:1 (tonal surfaces carry text)"
                )
        for cli, pair in theme["cli"].items():
            r = ratio(pair["fg"], pair["bg"])
            if r < TEXT_PAIR_MIN:
                problems.append(f"{name}: cli {cli} fg/bg = {r:.2f}:1")
            if ratio(pair["border"], theme["surface1"]) < 1.15:
                problems.append(f"{name}: cli {cli} border invisible")

    sizes = list(SHAPE.values())
    if sizes != sorted(sizes) or len(set(sizes)) != len(sizes):
        problems.append(f"shape scale must be strictly increasing: {SHAPE}")
    if SHAPE.get("full", 0) < 1000:
        problems.append("shape `full` must be Google's corner-full (9999px)")
    for corner, parts in COMPOSED_CORNERS.items():
        unknown = [p for p in parts if p is not None and p not in SHAPE]
        if unknown:
            problems.append(f"composed corner {corner} references unknown steps {unknown}")

    for label, value in {
        **STATE,
        **{f"disabled-{k}": v for k, v in STATE_DISABLED.items()},
    }.items():
        if not 0.0 < value < 1.0:
            problems.append(f"state opacity {label} must be a fraction in (0, 1), got {value}")

    for level, dp in ELEVATION_DP.items():
        if not all(dp in table for table in (_UMBRA, _PENUMBRA, _AMBIENT)):
            problems.append(f"elevation {level} ({dp}dp) has no umbra/penumbra/ambient recipe")

    for role, spec in TYPESCALE.items():
        if spec["line"] <= spec["size"]:
            problems.append(f"typescale {role}: line-height must exceed the size")
        if spec["weight"] not in (400, 500):
            problems.append(f"typescale {role}: M3 uses weight 400 or 500, got {spec['weight']}")
        if spec["tracking"] < 0:
            problems.append(f"typescale {role}: tracking must not be negative")
        if spec["size"] < CJK_FLOOR_PX and not spec.get("mono_only"):
            problems.append(
                f"typescale {role}: {spec['size']}px is under the {CJK_FLOOR_PX}px CJK floor "
                "and is not marked mono_only"
            )

    for name, spring in SPRINGS.items():
        if not 0.0 < spring["damping"] <= 1.0:
            problems.append(f"spring {name}: damping must be in (0, 1], got {spring['damping']}")
        if spring["stiffness"] <= 0:
            problems.append(f"spring {name}: stiffness must be positive, got {spring['stiffness']}")
        curve, settle_ms = spring_curve(spring["damping"], spring["stiffness"])
        if not (curve.startswith("linear(0, ") and curve.endswith(", 1)")):
            problems.append(f"spring {name}: sampled easing must run 0 → 1, got {curve[:40]}…")
        if not 40 <= settle_ms <= 4000:
            problems.append(f"spring {name}: settle time {settle_ms}ms is out of range")

    # Report the offending *value*, never raise on it: `int(v[:-2])` used to
    # blow up with a ValueError traceback on `"1.1s"` — the exact style the
    # sheet shipped before this change — instead of naming the bad token.
    ordered: list[int] = []
    for name, value in MOTION_DURATIONS.items():
        if not _DURATION_RE.fullmatch(value):
            problems.append(f"motion duration {name} must be a plain ms value, got {value!r}")
            continue
        ordered.append(int(value[:-2]))
    if ordered != sorted(ordered):
        problems.append("motion durations must be non-decreasing in declared order")

    for name, value in MOTION_EASINGS.items():
        problem = easing_problem(value)
        if problem:
            problems.append(f"motion easing {name}: {problem} ({value})")

    for name, value in MOTION_STAGGER.items():
        if not _DURATION_RE.fullmatch(value):
            problems.append(f"motion stagger {name} must be a plain ms value, got {value!r}")

    tokens = {
        "_readme": (
            "Cockpit design tokens — the single source of truth for both themes. theme.ts "
            "turns this file into CSS custom properties plus antd ConfigProvider tokens: "
            "colours, shape, interaction state, elevation, type scale and motion all come "
            "from here (the few hairline radii that are not M3E surfaces — code blocks, inline "
            "marks, focus rings — stay literal, and the AA gate does not cover them). Sources: "
            "material-web tokens v0_192 for shape/state/elevation/typescale/motion, androidx "
            "material3 tokens v0_14_0 for the springs, MDC-Web elevation maps for the "
            "dp→box-shadow recipe; each block carries its own `_source` and marks whatever is "
            "ours rather than Google's. Generated: run `python scripts/gen_tokens.py` to rewrite "
            "it, `--check` to prove it is fresh. All text/surface, text-on-tonal-container and "
            "CLI-chip pairs are WCAG AA (>= 4.5:1) verified by tests/test_tokens_contrast.py."
        ),
        "colorRoles": {
            "_source": (
                "Google's full M3 baseline colour scheme: the role→tone mapping is "
                "material-web tokens/versions/v0_192/_md-sys-color.scss and the tones are "
                "_md-ref-palette.scss. Derived here rather than copied as hex, so the file "
                "states the derivation and a tone typo fails loudly."
            ),
            # Tone keys are emitted as strings: JSON turns an int key into a string,
            # so an in-memory int key made the committed file compare unequal to a
            # fresh build even though both were correct.
            "tones": {
                family: {str(tone): hexv for tone, hexv in tones.items()}
                for family, tones in M3_TONES.items()
            },
            "roles": {theme: colour_roles(theme) for theme in ("dark", "light")},
        },
        "shape": SHAPE,
        "shapeComposed": {
            "_source": "Google's composed corners (corner-*-top/start/end), derived from `shape`.",
            "corners": {
                corner: " ".join(f"{SHAPE[step]}px" if step else "0px" for step in parts)
                for corner, parts in COMPOSED_CORNERS.items()
            },
        },
        "state": {
            "_source": (
                "Opacity of a surface's own content colour composited over it — M3's definition "
                "of feedback. hover/focus/pressed/dragged are Google's (material-web "
                "tokens/versions/v0_192/_md-sys-state.scss). `disabled` is ours: M3's token file "
                "publishes no disabled opacity."
            ),
            "opacity": STATE,
            "disabled": STATE_DISABLED,
        },
        "elevation": {
            "_source": (
                "Levels are M3's (material-web tokens/versions/v0_192/_md-sys-elevation.scss), in "
                "dp. The dp→box-shadow recipes are MDC-Web's umbra/penumbra/ambient maps "
                "(packages/mdc-elevation/_elevation-theme.scss) at 0.2/0.14/0.12 black — the same "
                "algorithm material-web compiles to CSS. Level 0 is `none`: M3 separates resting "
                "surfaces with an outline."
            ),
            "levels": ELEVATION_DP,
            "shadow": {level: elevation_shadow(dp) for level, dp in ELEVATION_DP.items()},
        },
        "typescale": {
            "_source": (
                "Google's M3 type roles (material-web "
                "tokens/versions/v0_192/_md-sys-typescale.scss), rem × 16 = px. `label-small` is "
                f"11px, under this repo's {CJK_FLOOR_PX}px CJK floor, so it is marked mono_only: "
                "latin identifiers and monospace only."
            ),
            "cjkFloor": CJK_FLOOR_PX,
            "roles": TYPESCALE,
        },
        "motion": {
            "_source": (
                "Durations and the standard/emphasized/linear easings are Google's, from "
                "material-web tokens/versions/v0_192/_md-sys-motion.scss. `spring` is Google's "
                "M3E motion scheme (androidx material3 tokens v0_14_0: spring damping ratios and "
                "stiffnesses); `easing`/`duration` inside each spring are the `linear()` sample of "
                "that spring and its settle time, derived here because CSS has no spring "
                "primitive, and `fallback` is our cubic-bezier approximation for engines without "
                "`linear()`. `expressive-over`/`expressive-out` and the `stagger` step are ours."
            ),
            "duration": MOTION_DURATIONS,
            "easing": MOTION_EASINGS,
            "stagger": MOTION_STAGGER,
            "spring": {
                name: {
                    "damping": spring["damping"],
                    "stiffness": spring["stiffness"],
                    "duration": f"{spring_curve(spring['damping'], spring['stiffness'])[1]}ms",
                    "easing": spring_curve(spring["damping"], spring["stiffness"])[0],
                    "fallback": SPRING_FALLBACK[
                        "spatial" if name.endswith("-spatial") else "effects"
                    ],
                }
                for name, spring in SPRINGS.items()
            },
        },
        "contrast": {"text": TEXT_PAIR_MIN, "graphic": GRAPHIC_MIN},
        "cli": ids,
        "themes": themes,
    }
    return tokens, problems


def render(tokens: dict) -> str:
    # ensure_ascii=False so the em dash in _readme stays a dash: the file is
    # UTF-8 and its whole point is being reviewable in a diff.
    return json.dumps(tokens, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Unknown flags refuse to run rather than fall through to a write: a typo
    # like `--checks` used to silently rewrite the file, which is the one way
    # this script could still damage tokens.json.
    unknown = [a for a in argv if a != "--check"]
    if unknown:
        print(f"unknown argument(s): {' '.join(unknown)}; usage: gen_tokens.py [--check]")
        return 2
    check = "--check" in argv
    tokens, problems = build()
    if problems:
        print("gate failed:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    fresh = render(tokens)
    if check:
        committed = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if committed != fresh:
            print(
                f"{OUT} is stale: run `python scripts/gen_tokens.py` and commit the result",
                file=sys.stderr,
            )
            return 1
        print(f"{OUT} matches the generator ({len(tokens['cli'])} CLI identities)")
        return 0
    OUT.write_text(fresh, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    for name, theme in tokens["themes"].items():
        worst_text = min(
            ratio(theme[t], theme[s])
            for t in ("text1", "text2", "text3")
            for s in ("surface0", "surface1", "surface2")
        )
        worst_chip = min(ratio(p["fg"], p["bg"]) for p in theme["cli"].values())
        print(f"  {name}: worst text {worst_text:.2f}:1 · worst CLI chip {worst_chip:.2f}:1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
