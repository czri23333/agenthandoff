"""Shape, elevation, state and type — checked against Google's own files.

`tests/test_official_palette.py` does this for the colour layer. This is the same
idea for the four layers that are not colours, and they need it for the same
reason: a wrong rung is a *plausible* value, not an error. A tracking of `0.25`
instead of `0.5`, an elevation of `4` instead of `3`, a corner of `12` instead of
`16` — every one of those renders, looks like Material, and is not Material.

The fixtures are verbatim copies (Apache-2.0, headers intact) of five files from
`tokens/versions/v0_192/` in material-components/material-web, fetched
first-hand on 2026-09-12 and pinned by sha256 below:

    _md-sys-shape.scss       12 corner entries (7 simple + 5 composed)
    _md-sys-elevation.scss   6 levels, in dp
    _md-sys-state.scss       4 state-layer opacities
    _md-sys-typescale.scss   15 type roles, discrete keys (size/line/tracking/weight)
    _md-ref-typeface.scss    the weight rungs the typescale references

Two conventions are the reason a naive comparison would mislead, and both are
handled here rather than in prose: the official file writes type sizes and
tracking in **rem** (converted at 16px), and the composed corners are published as
four-value lists (`28px 28px 0px 0px`) where we keep them as named tuples that the
generator flattens.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "tests" / "fixtures" / "m3spec"

EXPECTED_HASHES = {
    "md-sys-shape.scss": "2ffa44f85591cde7f501aafb8e26c422d341b1eae56b3e2fab7ab6034a3ee6eb",
    "md-sys-elevation.scss": "658319c50ce8f33f08d567493dfe52106e9ef177f43b4d6a38526ee339e24972",
    "md-sys-state.scss": "d410dd5d47c1bc25b25b6fa82901bdf8d555360cbd35716bc73ed8d6a61ea6f8",
    "md-sys-typescale.scss": "7c8cbd48c99465a6924eff73d7809c764f528a81933206d548e1a88b33dbe8d9",
    "md-ref-typeface.scss": "b5055798c322a39f4664f04afe6e09f5126145cd0fd005a71426f8a630434c93",
}
# One fixture is from a different repository *and* a different licence: the
# dp→box-shadow recipe is MDC-Web's, MIT, not material-web's Apache-2.0. The
# header is kept verbatim and this test asserts it is still there.
MDC_ELEVATION = "mdc-elevation-theme.scss"
MDC_ELEVATION_SHA = "e50ad0e52382834369d76a09ceac80644e2d9405b87050282fd19a5dea8954cf"


def _generator():
    module = importlib.util.spec_from_file_location(
        "gen_tokens_for_layers", REPO / "scripts" / "gen_tokens.py"
    )
    assert module and module.loader
    gen = importlib.util.module_from_spec(module)
    module.loader.exec_module(gen)
    return gen


def _values(name: str) -> str:
    """The body of a generated `@return ( … );` map."""
    text = (SPEC / name).read_text(encoding="utf-8")
    return text.split("@return (", 1)[1].split(");", 1)[0]


def test_the_layer_fixtures_are_the_pinned_files():
    for name, expected in EXPECTED_HASHES.items():
        data = (SPEC / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected, f"{name} was edited"
        assert b"Design system version: v0.192" in data, name


def test_the_mdc_elevation_recipe_is_the_pinned_mit_file():
    """The one fixture that is not material-web, and not Apache-2.0."""
    data = (SPEC / MDC_ELEVATION).read_bytes()
    assert hashlib.sha256(data).hexdigest() == MDC_ELEVATION_SHA
    assert b"Copyright 2017 Google Inc." in data
    assert b"Permission is hereby granted, free of charge" in data


def test_the_dp_to_shadow_recipe_matches_mdc_web():
    """Umbra, penumbra and ambient, at the six levels M3 publishes.

    `tests/…::test_elevation_levels_match_the_official_dp_scale` proves we have
    the right *levels*; this proves we turn each level into the shadow MDC-Web
    publishes, which is a second file in a second repository. Ten of these values
    would look plausible if they were wrong — a penumbra blur of `11px` instead of
    `10px` is not something a reader can see and not something the browser
    complains about.
    """
    gen = _generator()
    text = (SPEC / MDC_ELEVATION).read_text(encoding="utf-8")
    chunks = re.split(r"\$([a-z]+)-map:\s*\(", text)
    official: dict[str, dict[int, str]] = {}
    for i in range(1, len(chunks), 2):
        name, body = chunks[i], re.split(r"\$[a-z]+-map:\s*\(", chunks[i + 1])[0]
        official[name] = {
            int(key): " ".join(value.split())
            for key, value in re.findall(r"(\d+):\s*'([^']+)'", body)
        }
    opacities = {
        m.group(1): float(m.group(2))
        for m in re.finditer(r"\$(umbra|penumbra|ambient)-opacity:\s*([0-9.]+)", text)
    }

    assert sorted(official) == ["ambient", "penumbra", "umbra"]
    assert all(len(levels) == 25 for levels in official.values())
    assert opacities == {"umbra": 0.2, "penumbra": 0.14, "ambient": 0.12}

    ours = {"umbra": gen._UMBRA, "penumbra": gen._PENUMBRA, "ambient": gen._AMBIENT}
    ours_opacities = {
        "umbra": gen._UMBRA_OPACITY,
        "penumbra": gen._PENUMBRA_OPACITY,
        "ambient": gen._AMBIENT_OPACITY,
    }
    for kind, levels in ours.items():
        assert sorted(levels) == [0, 1, 3, 6, 8, 12], kind
        for dp, value in levels.items():
            assert value == official[kind][dp], f"{kind} at {dp}dp"
    for kind, value in ours_opacities.items():
        assert value == pytest.approx(opacities[kind]), kind
    # The shadow colour: MDC's `$baseline-color: black`, which the generator writes
    # as the rgb triplet every recipe shares.
    assert gen._SHADOW_RGB == "0, 0, 0"


def test_corners_match_the_official_shape_scale():
    """Seven simple corners plus the five composed ones, as four-value lists."""
    gen = _generator()
    body = _values("md-sys-shape.scss")
    official = {
        m.group(1): " ".join(m.group(2).split())
        for m in re.finditer(
            r"'([a-z0-9-]+)':\s*\n?\s*if\(\$exclude-hardcoded-values,\s*null,\s*\(?((?:[0-9]+px)(?:\s+[0-9]+px)*)\)?",
            body,
        )
    }
    ours = {
        "corner-extra-small": f"{gen.SHAPE['xs']}px",
        "corner-small": f"{gen.SHAPE['sm']}px",
        "corner-medium": f"{gen.SHAPE['md']}px",
        "corner-large": f"{gen.SHAPE['lg']}px",
        "corner-extra-large": f"{gen.SHAPE['xl']}px",
        "corner-full": f"{gen.SHAPE['full']}px",
        "corner-none": "0px",
    }
    for name, corners in gen.COMPOSED_CORNERS.items():
        ours[f"corner-{name}"] = " ".join(
            "0px" if step is None else f"{gen.SHAPE[step]}px" for step in corners
        )

    assert len(official) == 12, "the official shape file changed shape"
    if ours != official:
        raise AssertionError(
            {
                k: (ours.get(k), official.get(k))
                for k in set(ours) | set(official)
                if ours.get(k) != official.get(k)
            }
        )


def test_elevation_levels_match_the_official_dp_scale():
    gen = _generator()
    official = {
        m.group(1): int(m.group(2))
        for m in re.finditer(
            r"'(level[0-9])':\s*if\(\$exclude-hardcoded-values,\s*null,\s*([0-9]+)\)",
            _values("md-sys-elevation.scss"),
        )
    }
    assert official == {
        "level0": 0,
        "level1": 1,
        "level2": 3,
        "level3": 6,
        "level4": 8,
        "level5": 12,
    }
    assert {k: float(v) for k, v in official.items()} == gen.ELEVATION_DP


def test_state_layer_opacities_match_the_official_file():
    gen = _generator()
    official = {
        m.group(1): float(m.group(2))
        for m in re.finditer(
            r"'([a-z-]+)-state-layer-opacity':\s*if\(\$exclude-hardcoded-values,\s*null,\s*([0-9.]+)\)",
            _values("md-sys-state.scss"),
        )
    }
    assert official == {"dragged": 0.16, "focus": 0.12, "hover": 0.08, "pressed": 0.12}
    assert official == gen.STATE


def test_every_type_role_we_ship_matches_the_official_typescale():
    """Sizes and tracking are published in rem; the comparison is at 16px.

    The five roles we do not carry are asserted *by name* rather than ignored: a
    role that quietly disappears from either side is a change worth seeing, and
    the cockpit uses none of them (`display-*`, `headline-large`,
    `headline-medium`).
    """
    gen = _generator()
    text = (SPEC / "md-sys-typescale.scss").read_text(encoding="utf-8")
    weights = {
        m.group(1): int(m.group(2))
        for m in re.finditer(
            r"'(weight-[a-z]+)':\s*if\(\$exclude-hardcoded-values,\s*null,\s*([0-9]+)\)",
            _values("md-ref-typeface.scss"),
        )
    }

    official: dict[str, dict[str, float]] = {}
    for key, field in (("size", "size"), ("line-height", "line"), ("tracking", "tracking")):
        for m in re.finditer(
            rf"'([a-z-]+)-{key}':\s*if\(\$exclude-hardcoded-values,\s*null,\s*([0-9.]+)rem\)",
            text,
        ):
            official.setdefault(m.group(1), {})[field] = round(float(m.group(2)) * 16, 4)
    for m in re.finditer(
        r"'([a-z-]+)-weight':\s*map\.get\(\$deps, 'md-ref-typeface', '(weight-[a-z]+)'\)", text
    ):
        official.setdefault(m.group(1), {})["weight"] = weights[m.group(2)]

    assert len(official) == 15, "the official typescale changed"
    assert sorted(set(official) - set(gen.TYPESCALE)) == [
        "display-large",
        "display-medium",
        "display-small",
        "headline-large",
        "headline-medium",
    ]

    differences = {}
    for role in sorted(set(gen.TYPESCALE) & set(official)):
        mine, theirs = gen.TYPESCALE[role], official[role]
        delta = {
            field: (mine.get(field), theirs.get(field))
            for field in ("size", "line", "tracking", "weight")
            if abs(float(mine.get(field, 0)) - float(theirs.get(field, 0))) > 0.001
        }
        if delta:
            differences[role] = delta
    assert not differences, differences
