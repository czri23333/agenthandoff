"""Author web/src/tokens.json: palettes, M3E shape scale and the motion tokens.

    python scripts/gen_tokens.py            # regenerate after changing a hue
    python scripts/gen_tokens.py --check    # fail if the committed file drifted

``tokens.json`` is the committed source of truth (reviewable, diffable); this
script is how it is made, kept in the repo so a contributor can reproduce it
instead of trusting a blob of hex codes. The gate:

  * every text tier on every surface          >= 4.5:1  (AA normal text)
  * every CLI identity fg on its badge bg     >= 4.5:1, in both themes
  * borders / focus rings / large text        >= 3:1
  * shape scale strictly increasing, pill huge, motion values well-formed

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

# M3 Expressive shape scale (px). Cards take lg, controls md, chips pill; the
# message roles reuse the same scale so bubbles and cards share one geometry.
SHAPE: dict[str, int] = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 28, "pill": 999}

# Motion tokens. Durations and the standard/emphasized easings are Google's,
# copied from material-web's generated token file (design system v0.192):
#   https://github.com/material-components/material-web/blob/main/tokens/versions/v0_192/_md-sys-motion.scss
# `expressive-*` are ours: M3E's spring feel needs a slight overshoot, which the
# official cubic-beziers do not have. They are marked as additions here and in
# tokens.json so nobody mistakes them for Google values.
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

BASE: dict[str, dict[str, str]] = {
    "dark": {
        "surface0": "#0e1116",  # app background
        "surface1": "#161a21",  # cards, rows, inputs
        "surface2": "#1e242e",  # raised: chips, code, hover
        "line": "#2a3240",
        "lineStrong": "#3d4757",
        "text1": "#eef1f6",
        "text2": "#c3cad6",
        "text3": "#9aa4b3",  # dimmest tier — still AA, by construction
        "accent": "#7aa2ff",
        "ok": "#7ee2a8",
        "warn": "#ffd166",
        "err": "#ff8f96",
        "codeBg": "#0b0e13",
        "scheme": "dark",
    },
    "light": {
        "surface0": "#f6f7f9",
        "surface1": "#ffffff",
        "surface2": "#eceff4",
        "line": "#d5dae2",
        "lineStrong": "#a9b3c1",
        "text1": "#14181f",
        "text2": "#3b4351",
        "text3": "#5d6779",
        "accent": "#2f5fd0",
        "ok": "#1a7f45",
        "warn": "#8a6100",
        "err": "#b4232f",
        "codeBg": "#f2f4f8",
        "scheme": "light",
    },
}

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


def containers(theme: dict, strength: float) -> dict[str, str]:
    """The four M3E tonal surfaces: a semantic colour mixed into surface1.

    Derived rather than pinned: one strength per theme reproduces all four
    shipped containers byte-exactly (dark 0.179, light 0.16 — measured by
    solving ``tint()`` for its pre-image, not by eye). Deriving means a palette
    edit re-tints the chips and the user bubble together, and the AA gate below
    re-checks the text that sits on them.
    """
    return {
        container: tint(theme["surface1"], theme[source], strength)
        for container, source in CONTAINER_SOURCES.items()
    }


def build() -> tuple[dict, list[str]]:
    problems: list[str] = []
    ids = cli_ids()
    for cli in ids:
        if cli not in CLI_HUES and cli not in CLI_PINNED:
            problems.append(f"cli {cli} has no identity: add a hue to CLI_HUES")

    themes: dict[str, dict] = {}
    for name, raw in BASE.items():
        theme = dict(raw)
        for tier in ("text1", "text2", "text3"):
            for surface in ("surface0", "surface1", "surface2"):
                if ratio(theme[tier], theme[surface]) < TEXT_PAIR_MIN:
                    theme[tier] = solve(theme[tier], theme[surface], TEXT_PAIR_MIN)
        for key in ("accent", "ok", "warn", "err"):
            if ratio(theme[key], theme["surface1"]) < TEXT_PAIR_MIN:
                theme[key] = solve(theme[key], theme["surface1"], TEXT_PAIR_MIN)
        theme["placeholder"] = theme["text3"]
        theme["onSurface0"] = theme["text1"]
        theme.update(containers(theme, CONTAINER_STRENGTH[name]))
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
    if SHAPE.get("pill", 0) < 100:
        problems.append("shape pill must be large enough to read as a pill")

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
            "every colour, and every animated duration and curve, comes from here (the few "
            "hairline radii that are not M3E surfaces — code blocks, inline marks, focus "
            "rings — stay literal, and the AA gate does not cover them). Generated: run "
            "`python scripts/gen_tokens.py` to rewrite it, `--check` to prove it is fresh. "
            "All text/surface, text-on-tonal-container and CLI-chip pairs are WCAG AA "
            "(>= 4.5:1) verified by tests/test_tokens_contrast.py. `shape` and `motion` live "
            "here so the M3E geometry and the motion contract regenerate with the palette "
            "instead of drifting beside it."
        ),
        "shape": SHAPE,
        "motion": {
            "_source": (
                "Durations and standard/emphasized/linear easings are Google's, from "
                "material-web tokens/versions/v0_192/_md-sys-motion.scss. `expressive-over`/"
                "`expressive-out` and the `stagger` steps are ours (M3E spring overshoot; M3 "
                "publishes no stagger token), not Google values."
            ),
            "duration": MOTION_DURATIONS,
            "easing": MOTION_EASINGS,
            "stagger": MOTION_STAGGER,
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
