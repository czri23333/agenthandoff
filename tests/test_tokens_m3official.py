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
OFFICIAL_LEVEL1_SHADOW = (
    "0px 2px 1px -1px rgba(0, 0, 0, 0.2), "
    "0px 1px 1px 0px rgba(0, 0, 0, 0.14), "
    "0px 1px 3px 0px rgba(0, 0, 0, 0.12)"
)

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


def test_elevation_levels_are_googles_and_level0_is_no_shadow():
    assert TOKENS["elevation"]["levels"] == OFFICIAL_ELEVATION_DP
    assert TOKENS["elevation"]["shadow"]["level0"] == "none"
    assert TOKENS["elevation"]["shadow"]["level1"] == OFFICIAL_LEVEL1_SHADOW


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
