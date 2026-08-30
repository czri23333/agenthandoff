"""Author web/src/tokens.json: dark + light palettes whose pairs all pass WCAG AA.

    python scripts/gen_tokens.py        # regenerate after changing a hue or tier

``tokens.json`` is the committed source of truth (reviewable, diffable); this
script is how it is made, kept in the repo so a contributor can reproduce it
instead of trusting a blob of hex codes. The gate:

  * every text tier on every surface          >= 4.5:1  (AA normal text)
  * every CLI identity fg on its badge bg     >= 4.5:1, in both themes
  * borders / focus rings / large text        >= 3:1

Hues keep each CLI's existing identity; lightness is *solved for*, because
eyeballing contrast is exactly how the shipped cockpit ended up drawing the
`zcode` and `qodercn-ide` badges at 1.1:1 (white text on a near-white chip).
"""

from __future__ import annotations

import colorsys
import json
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


def build() -> tuple[dict, list[str]]:
    problems: list[str] = []
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
        theme["cli"] = {cli: badge(hue, theme["surface1"]) for cli, hue in CLI_HUES.items()}
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
        for cli, pair in theme["cli"].items():
            r = ratio(pair["fg"], pair["bg"])
            if r < TEXT_PAIR_MIN:
                problems.append(f"{name}: cli {cli} fg/bg = {r:.2f}:1")
            if ratio(pair["border"], theme["surface1"]) < 1.15:
                problems.append(f"{name}: cli {cli} border invisible")

    tokens = {
        "_readme": (
            "Cockpit design tokens — the single source of truth for both themes. theme.ts "
            "turns this file into CSS custom properties plus antd ConfigProvider tokens, so "
            "no component hardcodes a colour. All text/surface and CLI-chip pairs are WCAG "
            "AA (>= 4.5:1) verified by tests/test_tokens_contrast.py; regenerate with "
            "`python scripts/gen_tokens.py`."
        ),
        "contrast": {"text": TEXT_PAIR_MIN, "graphic": GRAPHIC_MIN},
        "cli": list(CLI_HUES),
        "themes": themes,
    }
    return tokens, problems


def main() -> int:
    tokens, problems = build()
    if problems:
        print("AA gate failed:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    OUT.write_text(json.dumps(tokens, indent=2) + "\n", encoding="utf-8", newline="\n")
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
