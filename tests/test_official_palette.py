"""The palette is Google's baseline — proved against Google's own files.

`docs/theming.md` has claimed since the first colour commit that the shipped
palette is the published M3 baseline. That was true, but "the baseline" was a
statement about values a human had transcribed; this is the version that cannot
rot. The two files under `tests/fixtures/m3spec/` are verbatim copies (Apache-2.0,
headers intact) of:

    tokens/versions/v0_192/_md-sys-color.scss
    tokens/versions/v0_192/_md-ref-palette.scss

from material-components/material-web, fetched first-hand on 2026-09-12. The
tool layer is two separate maps — a role names a *rung* (`primary40`), and the
rung names a hex — so both are compared, and both are compared for both themes.

Why vendor rather than fetch in the test: a gate that needs the network is a gate
that fails on a train, and this repo's CI has never had network guarantees. The
hashes below pin the copies, so a silent edit is a failure rather than a new
truth.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "tests" / "fixtures" / "m3spec"
COLOR = SPEC / "_md-sys-color.scss"
PALETTE = SPEC / "_md-ref-palette.scss"

# sha256 of the fetched bytes; a change here is a deliberate re-vendor.
EXPECTED_HASHES = {
    "_md-sys-color.scss": "aa0c2dc244989edcb1bb2af169a87d290e5303a7e945720cd2c21c8bdb103670",
    "_md-ref-palette.scss": "9208b47a2e67a9060a6d3440428a8ff0265e747d96477ae1b56dc7931d69f0d3",
}


def _generator():
    module = importlib.util.spec_from_file_location(
        "gen_tokens_for_palette", REPO / "scripts" / "gen_tokens.py"
    )
    assert module and module.loader
    gen = importlib.util.module_from_spec(module)
    module.loader.exec_module(gen)
    return gen


def _expand(hex_text: str) -> str:
    text = hex_text.lower()
    return "#" + "".join(c * 2 for c in text[1:]) if len(text) == 4 else text


def _official_tones() -> dict[str, str]:
    text = PALETTE.read_text(encoding="utf-8")
    return {
        name: _expand(value)
        for name, value in re.findall(
            r"'([a-z0-9-]+)':\s*if\(\$exclude-hardcoded-values,\s*null,\s*(#[0-9a-fA-F]{3,8})\)",
            text,
        )
    }


def _official_roles(theme: str) -> dict[str, str]:
    text = COLOR.read_text(encoding="utf-8")
    body = (
        text.split(f"@function values-{theme}", 1)[1]
        .split("@return (", 1)[1]
        .split(");", 1)[0]
    )
    return dict(
        re.findall(
            r"'([a-z0-9-]+)':\s*map\.get\(\$deps, 'md-ref-palette', '([a-z0-9-]+)'\)", body
        )
    )


def test_the_fixtures_are_the_pinned_files():
    """The copies carry Google's version banner and match the recorded hashes."""
    for name, expected in EXPECTED_HASHES.items():
        data = (SPEC / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected, f"{name} was edited"
        assert b"Design system version: v0.192" in data, name
        assert b"Copyright 2023 Google LLC" in data and b"Apache-2.0" in data, name


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_role_maps_to_the_official_rung(theme: str):
    """Our 49 roles → the same reference rungs Google's file publishes.

    This is the layer where a transcription slip would hide: the rung names are
    arbitrary (`neutral87` does not exist, and `neutral96` and `neutral98` differ
    by two hex digits), so a typo produces a plausible colour rather than an
    error.
    """
    gen = _generator()
    ours = {role: rung.replace(":", "") for role, rung in gen.M3_ROLE_REFS[theme].items()}
    official = _official_roles(theme)

    assert len(official) == 49, "the official file changed shape"
    missing = {role: rung for role, rung in ours.items() if official.get(role) != rung}
    assert not missing, f"{theme}: roles that disagree with v0_192: {missing}"


def test_every_reference_tone_is_the_official_hex():
    """Our 89 rungs → Google's hexes, byte for byte."""
    gen = _generator()
    ours = {
        f"{family}{tone}": value.lower()
        for family, tones in gen.M3_TONES.items()
        for tone, value in tones.items()
    }
    official = _official_tones()

    assert len(official) >= 89, "the official palette shrank"
    differences = {
        name: (ours.get(name), official.get(name))
        for name in set(ours) | set(official)
        if ours.get(name) != official.get(name)
    }
    # The only names allowed to differ are the two utility entries the official
    # file publishes and we do not carry as rungs — and they may only differ by
    # being absent on our side. Every tone we *do* carry has to match.
    unexpected = {k: v for k, v in differences.items() if k not in ("black", "white")}
    assert not unexpected, unexpected
    for name in ("black", "white"):
        if name in differences:
            assert differences[name][0] is None, differences[name]


def test_the_canonical_roles_are_the_ones_everyone_quotes():
    """A reader's spot check: the four values the M3 docs are known by."""
    tones = _official_tones()
    assert tones["primary40"] == "#6750a4"
    assert tones["primary80"] == "#d0bcff"
    assert tones["primary90"] == "#eaddff"
    assert tones["neutral98"] == "#fef7ff"
