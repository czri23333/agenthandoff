"""The token file must carry Google's published values, not the generator's memory of them.

`test_tokens_generated.py` proves the file matches the generator; that is not the
same as the generator matching Google. A wrong constant there regenerates a wrong
file and every comparison still passes, so the numbers below are an *independent
hand-written copy* read out of Google's own token files:

* shape / state / elevation / typescale / motion — material-web, design system
  `v0_192`, `tokens/versions/v0_192/_md-sys-*.scss`
* springs — androidx `compose/material3` `tokens/{Expressive,Standard}MotionTokens.kt`
  (`v0_14_0`), reached through `MotionScheme.kt`
* the dp → box-shadow recipe — MDC-Web `packages/mdc-elevation/_elevation-theme.scss`

Change a number here only after re-reading the source it cites.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOKENS = json.loads((REPO / "web" / "src" / "tokens.json").read_text(encoding="utf-8"))

# material-web v0_192 / _md-sys-shape.scss
OFFICIAL_CORNERS = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 28, "full": 9999}
OFFICIAL_COMPOSED = {
    "extra-small-top": "4px 4px 0px 0px",
    "large-top": "16px 16px 0px 0px",
    "large-start": "16px 0px 0px 16px",
    "large-end": "0px 16px 16px 0px",
    "extra-large-top": "28px 28px 0px 0px",
}

# material-web v0_192 / _md-sys-state.scss
OFFICIAL_STATE = {"hover": 0.08, "focus": 0.12, "pressed": 0.12, "dragged": 0.16}

# material-web v0_192 / _md-sys-elevation.scss (dp), and MDC-Web's recipe for dp 1
OFFICIAL_ELEVATION_DP = {
    "level0": 0,
    "level1": 1,
    "level2": 3,
    "level3": 6,
    "level4": 8,
    "level5": 12,
}
# MDC-Web's umbra/penumbra/ambient maps at 0.2/0.14/0.12 black, for each of M3's
# six dp levels. An independent review verified levels 2-5 against the source but
# noted only level 1 was pinned here — a typo in the other four would have passed
# CI, so all six are written out.
OFFICIAL_SHADOWS = {
    "level0": "none",
    "level1": "0px 2px 1px -1px rgba(0, 0, 0, 0.2), 0px 1px 1px 0px rgba(0, 0, 0, 0.14), "
    "0px 1px 3px 0px rgba(0, 0, 0, 0.12)",
    "level2": "0px 3px 3px -2px rgba(0, 0, 0, 0.2), 0px 3px 4px 0px rgba(0, 0, 0, 0.14), "
    "0px 1px 8px 0px rgba(0, 0, 0, 0.12)",
    "level3": "0px 3px 5px -1px rgba(0, 0, 0, 0.2), 0px 6px 10px 0px rgba(0, 0, 0, 0.14), "
    "0px 1px 18px 0px rgba(0, 0, 0, 0.12)",
    "level4": "0px 5px 5px -3px rgba(0, 0, 0, 0.2), 0px 8px 10px 1px rgba(0, 0, 0, 0.14), "
    "0px 3px 14px 2px rgba(0, 0, 0, 0.12)",
    "level5": "0px 7px 8px -4px rgba(0, 0, 0, 0.2), 0px 12px 17px 2px rgba(0, 0, 0, 0.14), "
    "0px 5px 22px 4px rgba(0, 0, 0, 0.12)",
}

# material-web v0_192 / _md-sys-typescale.scss, rem × 16 → px
OFFICIAL_ROLES = {
    "body-medium": (14, 20, 0.25, 400),
    "body-small": (12, 16, 0.4, 400),
    "label-large": (14, 20, 0.1, 500),
    "label-medium": (12, 16, 0.5, 500),
    "label-small": (11, 16, 0.5, 500),
    "title-small": (14, 20, 0.1, 500),
    "title-medium": (16, 24, 0.15, 500),
}

# androidx material3 v0_14_0, Expressive/StandardMotionTokens.kt
OFFICIAL_SPRINGS = {
    "expressive-fast-spatial": (0.6, 800.0),
    "expressive-default-spatial": (0.8, 380.0),
    "expressive-slow-spatial": (0.8, 200.0),
    "expressive-fast-effects": (1.0, 3800.0),
    "expressive-default-effects": (1.0, 1600.0),
    "expressive-slow-effects": (1.0, 800.0),
    "standard-fast-spatial": (0.9, 1400.0),
    "standard-default-spatial": (0.9, 700.0),
    "standard-slow-spatial": (0.9, 300.0),
    "standard-fast-effects": (1.0, 3800.0),
    "standard-default-effects": (1.0, 1600.0),
    "standard-slow-effects": (1.0, 800.0),
}

# material-web v0_192: `_md-sys-color.scss` role→tone mapping over the tones in
# `_md-ref-palette.scss`. A sample of both themes, written out by hand.
OFFICIAL_COLOR_ROLES = {
    "light": {
        "surface": "#fef7ff",
        "on-surface": "#1d1b20",
        "surface-container-low": "#f7f2fa",
        "surface-container-high": "#ece6f0",
        "surface-container-lowest": "#ffffff",
        "on-surface-variant": "#49454f",
        "outline": "#79747e",
        "outline-variant": "#cac4d0",
        "primary": "#6750a4",
        "on-primary": "#ffffff",
        "primary-container": "#eaddff",
        "on-primary-container": "#21005d",
        "secondary": "#625b71",
        "tertiary": "#7d5260",
        "error": "#b3261e",
        "on-error": "#ffffff",
        "error-container": "#f9dedc",
        "inverse-surface": "#322f35",
        "scrim": "#000000",
    },
    "dark": {
        "surface": "#141218",
        "on-surface": "#e6e0e9",
        "surface-container-low": "#1d1b20",
        "surface-container-high": "#2b2930",
        "surface-container-lowest": "#0f0d13",
        "on-surface-variant": "#cac4d0",
        "outline": "#938f99",
        "outline-variant": "#49454f",
        "primary": "#d0bcff",
        "on-primary": "#381e72",
        "primary-container": "#4f378b",
        "on-primary-container": "#eaddff",
        "secondary": "#ccc2dc",
        "tertiary": "#efb8c8",
        "error": "#f2b8b5",
        "on-error": "#601410",
        "error-container": "#8c1d18",
        "inverse-surface": "#e6e0e9",
        "scrim": "#000000",
    },
}

# The cockpit's own names must resolve to those roles, not to hand-picked hexes.
REPO_NAMES_TO_ROLES = {
    "surface0": "surface",
    "surface1": "surface-container-low",
    "surface2": "surface-container-high",
    "line": "outline-variant",
    "lineStrong": "outline",
    "text1": "on-surface",
    "text2": "on-surface-variant",
    "accent": "primary",
    "accentContainer": "primary-container",
    "err": "error",
    "errContainer": "error-container",
    "codeBg": "surface-container-lowest",
}


def test_colour_roles_are_googles_baseline_scheme():
    roles = TOKENS["colorRoles"]["roles"]
    for theme, expected in OFFICIAL_COLOR_ROLES.items():
        for role, hex_value in expected.items():
            assert roles[theme][role] == hex_value, f"{theme}.{role}"


def test_both_themes_carry_the_full_role_set():
    roles = TOKENS["colorRoles"]["roles"]
    assert set(roles["light"]) == set(roles["dark"]), "themes must define the same roles"
    # Every role the mapping names, resolved: a tone typo raises in the generator,
    # and this pins the count so a dropped role is noticed.
    assert len(roles["light"]) == 49


def test_the_repo_palette_is_the_official_roles_not_a_tint():
    """The palette is an alias onto the roles — no hand-picked hex survives.

    This is what makes the scheme *Google's* rather than "close to it": before
    this, `surface1` was `#161a21` (a hand-authored blue-grey) and
    `accentContainer` was a tint of it, neither of which is an M3 value.
    """
    for theme, mapping in (("dark", REPO_NAMES_TO_ROLES), ("light", REPO_NAMES_TO_ROLES)):
        palette = TOKENS["themes"][theme]
        roles = TOKENS["colorRoles"]["roles"][theme]
        for name, role in mapping.items():
            assert palette[name] == roles[role], f"{theme}.{name} != {role}"


def test_shape_carries_googles_corner_steps_and_composed_corners():
    assert TOKENS["shape"] == OFFICIAL_CORNERS
    assert TOKENS["shapeComposed"]["corners"] == OFFICIAL_COMPOSED


def test_state_layer_opacities_are_googles_four():
    assert TOKENS["state"]["opacity"] == OFFICIAL_STATE


def test_state_disabled_is_labelled_as_ours():
    """M3's token file publishes no disabled opacity — the file must say so."""
    disabled = TOKENS["state"]["disabled"]
    assert set(disabled) == {"container", "content"}
    assert "ours" in TOKENS["state"]["_source"]


def test_elevation_levels_are_googles_and_every_recipe_matches():
    assert TOKENS["elevation"]["levels"] == OFFICIAL_ELEVATION_DP
    assert TOKENS["elevation"]["shadow"] == OFFICIAL_SHADOWS


def test_every_type_role_matches_googles_scale():
    roles = TOKENS["typescale"]["roles"]
    assert set(roles) == set(OFFICIAL_ROLES)
    for role, expected in OFFICIAL_ROLES.items():
        spec = roles[role]
        got = (spec["size"], spec["line"], spec["tracking"], spec["weight"])
        assert got == expected, role


def test_only_the_mono_role_sits_under_the_cjk_floor():
    floor = TOKENS["typescale"]["cjkFloor"]
    assert floor == 12
    for role, spec in TOKENS["typescale"]["roles"].items():
        if spec["size"] < floor:
            assert spec.get("mono_only") is True, f"{role} is under the CJK floor and not mono_only"
            assert spec["size"] == 11, f"{role} is below Google's smallest role (label-small, 11px)"


@pytest.mark.parametrize("name,expected", sorted(OFFICIAL_SPRINGS.items()))
def test_springs_are_googles_damping_and_stiffness(name: str, expected: tuple):
    spring = TOKENS["motion"]["spring"][name]
    assert (spring["damping"], spring["stiffness"]) == expected


def test_every_spring_ships_a_usable_css_realisation():
    """CSS has no spring primitive: each one is sampled to `linear()` with a bezier fallback."""
    for name, spring in TOKENS["motion"]["spring"].items():
        assert spring["easing"].startswith("linear(0, "), name
        assert spring["easing"].endswith(", 1)"), name
        assert re.fullmatch(r"\d+ms", spring["duration"]), (name, spring["duration"])
        assert spring["fallback"].startswith("cubic-bezier("), name
        values = [float(m) for m in re.findall(r"(-?\d+\.\d+) \d", spring["easing"])]
        assert len(values) == 23, name
        assert max(values) >= 0.9, f"{name}: the sample never gets near 1"
