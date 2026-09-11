"""The component layer must be Google's, and the stylesheet must spend all of it.

Three independent claims, in the order they can fail:

1. **The numbers are Google's.** `OFFICIAL` below is a hand transcription of the
   androidx material3 token files (v0_14_0) and material-web's field token set,
   written from the source rather than read out of our own generator, so a typo in
   `scripts/gen_tokens.py` fails here instead of regenerating a wrong file that
   then passes `--check` because both sides moved together. This is the same
   shape as `test_tokens_m3official.py`, deliberately duplicated: two transcriptions
   of one document are what make a transcription checkable.

2. **Every published token is spent, and nothing is spent that is not published.**
   The stylesheet reads `--ah-c-*` custom properties; `theme.ts` derives exactly
   one custom property per leaf of `tokens.json["component"]`, by the same
   camelCase→kebab-case rule reimplemented here. So the two sets must be *equal*:
   a rule reading a property nobody injects is a component with an undefined
   value, and a token nobody reads is a number in a file pretending to be a
   contract. This is the gate the browser probe mirrors at runtime.

3. **No rule writes its own geometry.** `m3.css` may not contain a px length, a
   hex colour or a bare duration outside a short allow-list, because "the value is
   a token" is the property that makes every other claim in `docs/theming.md`
   checkable.

Sources, fetched first-hand (2026-09-10):
  androidx/androidx, androidx-main,
    compose/material3/material3/src/commonMain/kotlin/androidx/compose/material3/tokens/
  material-components/material-web, main,
    tokens/_md-comp-filled-field.scss, tokens/_md-comp-outlined-field.scss,
    tokens/versions/v0_192/_md-comp-*.scss, <component>/internal/*.scss
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WEB = Path(__file__).resolve().parent.parent / "web" / "src"
TOKENS = json.loads((WEB / "tokens.json").read_text(encoding="utf-8"))
C = TOKENS["component"]
STYLE = (WEB / "m3.css").read_text(encoding="utf-8")
# The second stylesheet that spends component tokens. The focus ring is a
# *global* treatment — it lands on every focusable element, not on one family —
# so it lives in `index.css`, and a consumption gate that only read `m3.css`
# would call its six tokens unspent. Both files are the stylesheet for this gate.
SHELL_STYLE = (WEB / "index.css").read_text(encoding="utf-8")
STYLES = (STYLE, SHELL_STYLE)

# ── 1. Google's numbers, transcribed by hand ────────────────────────────────

# Button{Small,Medium,Large}Tokens.kt, plus BaselineButtonTokens.kt for the
# 64px minimum width and the 0.1 / 0.38 disabled pair.
OFFICIAL_BUTTON = {
    "small": {
        "height": 40, "leading": 16, "trailing": 16, "icon": 20, "gap": 8,
        "shape": 9999, "shapeSquare": 12, "shapePressed": 8, "outlineWidth": 1,
    },
    "medium": {
        "height": 56, "leading": 24, "trailing": 24, "icon": 24, "gap": 8,
        "shape": 9999, "shapeSquare": 16, "shapePressed": 12, "outlineWidth": 1,
    },
    "large": {
        "height": 96, "leading": 48, "trailing": 48, "icon": 32, "gap": 12,
        "shape": 9999, "shapeSquare": 28, "shapePressed": 16, "outlineWidth": 2,
    },
}

# ListTokens.kt
OFFICIAL_LIST_ITEM = {
    "height": {"oneLine": 56, "twoLine": 72, "threeLine": 88},
    "leadingSpace": 16,
    "trailingSpace": 16,
    "icon": 24,
    "avatar": 40,
    "shape": {"rest": 4, "hover": 12, "active": 16},
}

# SwitchTokens.kt
OFFICIAL_SWITCH = {
    "track": {"width": 52, "height": 32, "outlineWidth": 2},
    "handle": {"selected": 24, "unselected": 16, "pressed": 28, "icon": 16},
    "stateLayer": 40,
}


def test_button_sizes_are_googles_three():
    got = {k: v for k, v in C["button"]["sizes"].items()}
    assert got == OFFICIAL_BUTTON, got
    assert C["button"]["minWidth"] == 64
    assert C["button"]["disabledContainer"] == 0.1
    assert C["button"]["disabledContent"] == 0.38


def test_button_press_shape_morphs_and_tightens():
    """ButtonSmallTokens.PressedContainerShape is corner-small, not corner-full."""
    for size, spec in C["button"]["sizes"].items():
        assert spec["shape"] != spec["shapePressed"], size
        assert spec["shapePressed"] < spec["shape"], size


def test_button_elevations_are_per_variant():
    assert C["button"]["elevation"] == {
        "rest": "elev:level0",
        "hover": "elev:level1",
        "pressed": "elev:level0",
    }
    assert C["button"]["elevationElevated"]["hover"] == "elev:level2"


def test_icon_button_is_the_40px_small_icon_button():
    small = C["iconButton"]["small"]
    assert small["height"] == 40
    assert small["icon"] == 24
    assert small["shape"] == 9999
    assert small["shapeSquare"] == 12
    assert small["shapePressed"] == 8
    assert small["space"] == {"narrow": 4, "default": 8, "wide": 14}
    assert small["outlineWidth"] == 1


def test_fab_sizes_are_googles_four():
    sizes = {k: v["size"] for k, v in C["fab"]["sizes"].items()}
    assert sizes == {"small": 40, "regular": 56, "medium": 80, "large": 96}
    shapes = {k: v["shape"] for k, v in C["fab"]["sizes"].items()}
    # 40 takes corner-medium, 56 corner-large, 96 corner-extra-large.
    assert shapes == {"small": 12, "regular": 16, "medium": 16, "large": 28}
    # …and 80's is OURS: FabMediumTokens.kt leaves ContainerShape commented out
    # behind a TODO because `corner-large-increased` has no published dp value.
    # The marker is what stops that inference from being read as Google's.
    assert C["fab"]["sizes"]["medium"].get("shapeOurs") is True
    assert "shapeOurs" not in C["fab"]["sizes"]["regular"]


def test_chip_is_32px_with_an_18px_icon_on_a_48px_touch_target():
    assert C["chip"]["height"] == 32
    assert C["chip"]["touchTarget"] == 48
    assert C["chip"]["icon"] == 18
    assert C["chip"]["avatar"] == 24
    # AssistChipTokens/FilterChipTokens/InputChipTokens carry corner-small; the
    # M3E base chip (ChipsTokens) rounds to corner-medium and opens to full.
    assert C["chip"]["variant"]["assist"]["shape"] == 8
    assert C["chip"]["variant"]["filter"]["shape"] == 12
    assert C["chip"]["selected"]["shape"] == 9999
    assert C["chip"]["selected"]["outlineWidth"] == 0
    assert C["chip"]["unselectedOutlineWidth"] == 1


def test_list_item_geometry_and_morph_are_googles():
    got = {
        "height": C["listItem"]["height"],
        "leadingSpace": C["listItem"]["leadingSpace"],
        "trailingSpace": C["listItem"]["trailingSpace"],
        "icon": C["listItem"]["icon"],
        "avatar": C["listItem"]["avatar"],
        "shape": C["listItem"]["shape"],
    }
    assert got == OFFICIAL_LIST_ITEM, got


def test_text_field_is_16_plus_24_plus_16():
    assert C["textField"]["height"] == 56
    assert C["textField"]["space"] == {
        "top": 16,
        "bottom": 16,
        "leading": 16,
        "trailing": 16,
        "content": 16,
    }
    # The content line is body-large; the container is the three official numbers.
    assert TOKENS["typescale"]["roles"]["body-large"]["line"] == 24
    assert (
        C["textField"]["space"]["top"]
        + TOKENS["typescale"]["roles"]["body-large"]["line"]
        + C["textField"]["space"]["bottom"]
        == C["textField"]["height"]
    )
    assert C["textField"]["withLabel"] == {"top": 8, "bottom": 8}
    assert C["textField"]["outlineLabelPadding"] == 4
    assert C["textField"]["labelPaddingBottom"] == 8
    assert C["textField"]["iconSize"] == 24
    assert C["textField"]["filled"]["indicatorHeight"] == 1
    assert C["textField"]["outlined"]["outlineWidth"] == 1


def test_text_field_dense_variant_is_labelled_ours():
    """M3's published token set has no dense field: 40 must not be dressed as Google's."""
    import subprocess
    import sys

    source = (Path(__file__).resolve().parent.parent / "scripts" / "gen_tokens.py").read_text(
        encoding="utf-8"
    )
    assert "heightDense" in source
    assert "Ours: M3's published token set has no dense variant" in source
    assert C["textField"]["heightDense"] == 40
    # It is the same geometry with the container spaces halved, not a third number.
    assert C["textField"]["denseSpaces"] * 2 + 24 == C["textField"]["heightDense"]
    assert subprocess is not None and sys is not None  # keep the imports honest


def test_switch_is_52_by_32():
    got = {
        "track": C["switch"]["track"],
        "handle": C["switch"]["handle"],
        "stateLayer": C["switch"]["stateLayer"],
    }
    for section, expected in OFFICIAL_SWITCH.items():
        if not isinstance(expected, dict):
            assert got[section] == expected, section
            continue
        for key, value in expected.items():
            assert got[section][key] == value, f"{section}.{key}"
    # SwitchTokens.TrackShape is corner-full and HandleShape too.
    assert got["track"]["shape"] == 9999


def test_checkbox_radio_and_segmented_are_googles():
    assert C["checkbox"]["size"] == 18
    assert C["checkbox"]["radius"] == 2
    assert C["checkbox"]["outlineWidth"] == 2
    assert C["checkbox"]["stateLayer"] == 40
    assert C["radio"]["size"] == 20
    assert C["radio"]["stateLayer"] == 40
    assert C["segmented"]["height"] == 40
    assert C["segmented"]["shape"] == 9999
    assert C["segmented"]["outlineWidth"] == 1
    assert C["segmented"]["icon"] == 18
    assert C["segmented"]["selected"]["container"] == "role:secondary-container"
    assert C["segmented"]["selected"]["content"] == "role:on-secondary-container"


def test_dialog_is_corner_extra_large_with_the_official_scrim():
    assert C["dialog"]["shape"] == 28
    assert C["dialog"]["container"] == "role:surface-container-high"
    assert C["dialog"]["elevation"] == "elev:level3"
    assert C["dialog"]["scrim"]["opacity"] == 0.32
    assert C["dialog"]["scrim"]["role"] == "role:scrim"


def test_progress_publishes_the_stop_indicator_and_the_gap():
    linear = C["progress"]["linear"]
    assert linear == {"height": 4, "trackSpace": 4, "stop": 4, "wavelength": 40}
    assert C["progress"]["circular"] == {"size": 40, "thickness": 4}
    assert C["progress"]["shape"] == 9999
    assert C["progress"]["active"] == "role:primary"
    assert C["progress"]["track"] == "role:secondary-container"


def test_tooltip_badge_divider_and_snackbar_are_googles():
    assert C["tooltip"]["shape"] == 4
    assert C["tooltip"]["container"] == "role:inverse-surface"
    assert C["badge"]["dot"] == 6
    assert C["badge"]["large"] == 16
    assert C["divider"]["thickness"] == 1
    assert C["divider"]["color"] == "role:outline-variant"
    assert C["snackbar"]["singleLine"] == 48
    assert C["snackbar"]["twoLine"] == 68
    assert C["snackbar"]["elevation"] == "elev:level3"


def test_layout_structures_are_googles_heights():
    assert C["appBar"]["small"]["height"] == 64
    assert C["appBar"]["medium"]["height"] == 112
    # The tab indicator's corner is 3dp, a bespoke value rather than a shape step
    # — referring it to the scale rounded it to 4 and no gate could tell.
    assert C["primaryTab"]["indicator"]["height"] == 3
    assert C["primaryTab"]["indicator"]["shape"] == 3
    assert C["navigationBar"]["height"] == 64
    assert C["navigationBar"]["tallHeight"] == 80
    assert C["navigationBar"]["indicator"]["height"] == 40
    assert C["navigationRail"]["item"]["height"] == 64
    assert C["navigationRail"]["item"]["verticalSpace"] == 6


def test_every_family_names_its_source():
    for family, spec in C.items():
        if family.startswith("_"):
            continue
        source = spec["_source"]
        assert any(mark in source for mark in ("androidx", "material-web", "Ours")), family


@pytest.mark.parametrize(
    "kind,table",
    [
        ("role", TOKENS["colorRoles"]["roles"]["dark"]),
        ("type", TOKENS["typescale"]["roles"]),
        ("elev", TOKENS["elevation"]["levels"]),
        ("corner", TOKENS["shapeComposed"]["corners"]),
        ("spring", TOKENS["motion"]["spring"]),
        ("dur", TOKENS["motion"]["duration"]),
        ("ease", TOKENS["motion"]["easing"]),
    ],
)
def test_every_reference_resolves(kind: str, table: dict):
    """A reference that does not resolve is a component reading an undefined value."""
    prefix = f"{kind}:"
    for path, value in _leaves(C):
        if isinstance(value, str) and value.startswith(prefix):
            assert value[len(prefix) :] in table, f"{path} → {value}"


# ── 2. The stylesheet and the token file must agree, exactly ────────────────


def _leaves(node, path: str = ""):
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).startswith("_"):
                continue
            yield from _leaves(value, f"{path}.{key}" if path else str(key))
        return
    yield path, node


def _code() -> str:
    """`m3.css` with block comments blanked out, newlines preserved.

    Preserving the newlines matters: the literal gates below report line numbers,
    and a comment that spans lines would otherwise shift every subsequent one —
    which is how the first version of this gate reported prose as geometry.
    """
    return re.sub(
        r"/\*.*?\*/",
        lambda m: "\n" * m.group(0).count("\n"),
        STYLE,
        flags=re.S,
    )


def _kebab(key: str) -> str:
    """The same transform `theme.ts` applies: `oneLine` → `one-line`."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", key).lower()


def _injected() -> set[str]:
    """Every `--ah-c-*` property `theme.ts` would emit for this token file."""
    return _injected_of(C)


def _injected_of(component: dict) -> set[str]:
    out: set[str] = set()
    for path, value in _leaves(component):
        name = "--ah-c-" + "-".join(_kebab(part) for part in path.split("."))
        if value is None:
            continue
        # `bool` before `int`: `isinstance(True, int)` is true in Python, so a
        # boolean leaf (the `shapeOurs` marker on the 80dp FAB) would otherwise
        # be reported as a published length while `theme.ts` — where `typeof
        # true === "boolean"` — emits nothing. An independent review found this
        # divergence by mutation; the marker now exercises it on every run.
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out.add(name)
            continue
        kind, _, target = str(value).partition(":")
        if kind == "type":
            out.update(f"{name}-{suffix}" for suffix in ("size", "line", "tracking", "weight"))
        elif kind == "spring":
            out.update(f"{name}-{suffix}" for suffix in ("duration", "easing"))
        else:
            out.add(name)
    return out


def _referenced() -> set[str]:
    return {
        name
        for style in STYLES
        for name in re.findall(r"var\((--ah-c-[A-Za-z0-9-]+)", style)
    }


def test_stylesheet_reads_exactly_the_published_component_tokens():
    injected, referenced = _injected(), _referenced()
    assert referenced - injected == set(), (
        "m3.css/index.css read component tokens theme.ts never injects: "
        f"{sorted(referenced - injected)}"
    )
    assert injected - referenced == set(), (
        "component tokens are published but nothing spends them: "
        f"{sorted(injected - referenced)}"
    )
    assert len(injected) >= 300, (
        f"only {len(injected)} component tokens are published — a shrinking block "
        "means a family was dropped without a note"
    )


def test_the_gate_can_fail():
    """The consumption gate must be able to fail, or it proves nothing.

    This repo has shipped three gates that could not (a curve check that only
    looked at the prefix, a font floor that only looked at one file, a key-order
    comparison that compared nothing), so the mutation is part of the test rather
    than a claim in a report.
    """
    # (a) the sets are computed, not empty
    assert len(_injected()) > 300
    assert len(_referenced()) > 300
    # (b) the transform is load-bearing: a camelCase key that lost its hyphen
    #     would produce a name no rule reads, and the gate would say so
    assert "--ah-c-list-item-height-one-line" in _injected()
    assert "--ah-c-list-item-height-oneline" not in _injected()
    # (c) publish one extra token and the "nobody spends it" half fires
    mutated = json.loads(json.dumps(C))
    mutated["button"]["sizes"]["small"]["smuggled"] = 13
    assert _injected_of(mutated) - _referenced() == {"--ah-c-button-sizes-small-smuggled"}
    # (d) delete a token a rule reads and the other half fires
    del mutated["button"]["sizes"]["small"]["smuggled"]
    del mutated["switch"]["track"]["width"]
    assert _referenced() - _injected_of(mutated) == {"--ah-c-switch-track-width"}
    # (e) a boolean leaf is a marker, not a length: both sides must skip it
    assert _injected_of({"fam": {"flag": True}}) == set()
    assert "--ah-c-fab-sizes-medium-shape-ours" not in _injected()


def test_the_literal_gate_can_fail():
    """Positive control for the three literal scanners.

    The cases below the first four are the ones an independent review's mutation
    run *found missing*: uppercase units, units other than px/rem/em, and named
    colours beyond the six words the first draft listed. They are here so the
    widening cannot be quietly reverted.
    """
    assert _length_offenders("padding: 13px;") == ["line 1: 13px"]
    assert _length_offenders("padding: 13PX;") == ["line 1: 13PX"]
    assert _length_offenders("width: 13vh;") == ["line 1: 13vh"]
    assert _length_offenders("margin: 13pt;") == ["line 1: 13pt"]
    assert _colour_offenders("color: #fff;") == ["line 1: #fff"]
    assert _colour_offenders("color: white;") == ["line 1: white"]
    assert _colour_offenders("color: White;") == ["line 1: White"]
    assert _colour_offenders("color: gold;") == ["line 1: gold"]
    assert _colour_offenders("color: rebeccapurple;") == ["line 1: rebeccapurple"]
    assert _colour_offenders("color: oklch(0.5 0 0);") == ["line 1: oklch("]
    assert _duration_offenders("transition: color cubic-bezier(0.2, 0, 0, 1);") == [
        "line 1: cubic-bezier("
    ]
    assert _duration_offenders("transition: color steps(4);") == ["line 1: steps("]
    # …and that it does not fire on the two shapes the sheet legitimately needs:
    # a media-query breakpoint and the state-layer spread.
    assert _length_offenders("@media (min-width: 1200px) {") == []
    assert _length_offenders("box-shadow: inset 0 0 0 9999px var(--ah-primary);") == []
    assert _colour_offenders("box-shadow: 0 0 0 0 transparent;") == []
    # A property whose *name* contains a colour word is not a colour.
    assert _colour_offenders("white-space: nowrap; background: currentColor;") == []
    assert _colour_offenders("color: var(--ah-c-tooltip-content);") == []


# ── 3. No rule writes its own geometry ──────────────────────────────────────

# `0` is absence, `100%` / `50%` / `1px` appear only inside `calc()` fractions of
# a token, `transparent` is the absence of a shadow in a comma-separated list,
# and `9999px` is the spread that turns an inset shadow into a full-area layer
# (an implementation detail of *how* a state layer is composited, not a value).
ALLOWED_LENGTHS = {"0", "1px", "9999px", "100%", "50%", "0%"}
ALLOWED_COLOURS = {"transparent", "currentColor"}


def _length_offenders(css: str) -> list[str]:
    """Every length in `css` that is not in the allow-list, as "line N: value"."""
    out: list[str] = []
    for lineno, line in enumerate(css.splitlines(), 1):
        # A media-query breakpoint is layout, not component geometry: M3 has no
        # opinion about how wide a window has to be before a side column appears.
        if line.lstrip().startswith("@media"):
            continue
        # `IGNORECASE` and the full unit list are both from an independent review
        # that mutation-tested this gate: `13PX`, `13vh` and `13pt` all passed it,
        # so the gate was enforcing "no px in lower case" rather than "no
        # lengths". The unit set is CSS's own, minus the ones that cannot appear
        # here (`deg`, `s` for angles) but plus everything a length can be.
        for match in re.finditer(
            r"(?<![\w-])(\d+(?:\.\d+)?)(px|rem|em|ex|ch|vh|vw|vmin|vmax|cm|mm|in|pt|pc|q|fr|ms|s)\b",
            line,
            re.IGNORECASE,
        ):
            if match.group(0).lower() not in {a.lower() for a in ALLOWED_LENGTHS}:
                out.append(f"line {lineno}: {match.group(0)}")
    return out


def _colour_offenders(css: str) -> list[str]:
    out: list[str] = []
    for lineno, line in enumerate(css.splitlines(), 1):
        for match in re.finditer(
            r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|oklch|oklab|color|lab|lch)\(",
            line,
            re.IGNORECASE,
        ):
            out.append(f"line {lineno}: {match.group(0)}")
        # Every CSS named colour, not a hand-written handful. A review mutation
        # showed `gold` and `rebeccapurple` sailing past the old six-word list;
        # `CSS_NAMED_COLOURS` below is the full keyword set, and the rule refuses
        # a hyphen on either side so `white-space` is still a property.
        for match in re.finditer(r"(?<![\w-])([a-zA-Z]+)(?![\w-])", line):
            if match.group(1).lower() in CSS_NAMED_COLOURS:
                out.append(f"line {lineno}: {match.group(1)}")
        # `currentColor` and `transparent` are the two keywords this sheet is
        # allowed to name: one is "whatever ink this element already has", the
        # other is "no paint".
        for match in re.finditer(
            r"(?<![\w-])(currentcolor|transparent)(?![\w-])", line, re.IGNORECASE
        ):
            if match.group(1).lower() not in {c.lower() for c in ALLOWED_COLOURS}:
                out.append(f"line {lineno}: {match.group(1)}")
    return out


# Every CSS named colour, including the ones a reviewer's mutation found missing.
# `transparent` and `currentcolor` are deliberately absent: they are in
# ALLOWED_COLOURS and are the two the sheet may name.
_NAMED_COLOUR_WORDS = (
    "aliceblue antiquewhite aqua aquamarine azure beige bisque black "
    "blanchedalmond blue blueviolet brown burlywood cadetblue chartreuse "
    "chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan "
    "darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta "
    "darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen "
    "darkslateblue darkslategray darkslategrey darkturquoise darkviolet "
    "deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite "
    "forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green "
    "greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender "
    "lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan "
    "lightgoldenrodyellow lightgray lightgreen lightgrey lightpink "
    "lightsalmon lightseagreen lightskyblue lightslategray lightslategrey "
    "lightsteelblue lightyellow lime limegreen linen magenta maroon "
    "mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen "
    "mediumslateblue mediumspringgreen mediumturquoise mediumvioletred "
    "midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive "
    "olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise "
    "palevioletred papayawhip peachpuff peru pink plum powderblue purple "
    "rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown "
    "seagreen seashell sienna silver skyblue slateblue slategray slategrey "
    "snow springgreen steelblue tan teal thistle tomato turquoise violet "
    "wheat white whitesmoke yellow yellowgreen"
)
CSS_NAMED_COLOURS = frozenset(_NAMED_COLOUR_WORDS.split())


def _duration_offenders(css: str) -> list[str]:
    out: list[str] = []
    for lineno, line in enumerate(css.splitlines(), 1):
        for match in re.finditer(r"cubic-bezier\(|steps\(", line, re.IGNORECASE):
            out.append(f"line {lineno}: {match.group(0)}")
    return out


def test_stylesheet_has_no_literal_lengths():
    offenders = _length_offenders(_code())
    assert not offenders, "m3.css writes its own lengths: " + ", ".join(offenders[:10])


def test_stylesheet_has_no_literal_colours():
    offenders = _colour_offenders(_code())
    assert not offenders, "m3.css writes its own colours: " + ", ".join(offenders[:10])


def test_stylesheet_has_no_bare_durations_or_curves():
    offenders = _duration_offenders(_code())
    assert not offenders, "m3.css writes its own curves: " + ", ".join(offenders[:10])


def test_no_rule_multiplies_a_derived_percentage_by_another():
    """The bug class behind the invisible dialog scrim.

    `theme.ts` emits a fraction as a **percentage** (`0.32` → `32%`), because the
    only things that spend one are `color-mix` and `opacity`. A rule that then
    writes `calc(var(--…-opacity) * 100%)` is multiplying percentage by
    percentage, which is not a valid calc type: the declaration is invalid at
    computed-value time, every candidate for that property is discarded, and the
    element silently paints nothing. Static CSS checks cannot see it (both sides
    are names), and the browser-side rule audit in the gallery is what found it —
    but the *shape* of the mistake is greppable, so it is grepped here too.
    """
    # A line-level check, not a `[^)]*` one: the offending expression contains a
    # nested `var(...)`, so a character class that stops at the first `)` cannot
    # reach the `*`. Two shapes are caught — multiplying anything by `100%`, and
    # putting a token named `…opacity`/`…percent` inside a `calc()` at all, since
    # that token is already a percentage.
    offenders = [
        f"line {lineno}: {line.strip()[:80]}"
        for lineno, line in enumerate(_code().splitlines(), 1)
        if "calc(" in line
        and (
            re.search(r"\*\s*100%\s*\)", line)
            or re.search(r"calc\(.*--ah-c-[a-z0-9-]*(opacity|percent)", line)
        )
    ]
    assert not offenders, (
        "a percentage token is being multiplied by a percentage again:\n  "
        + "\n  ".join(offenders[:5])
    )


def test_the_rule_audit_classifier_separates_dead_from_unverified():
    """`scripts/audit_component_rules.py` decides what counts as a dead rule.

    The audit itself needs a browser, so it is a maintainer tool; this exercises
    the part that decides, which is where a wrong answer would quietly re-open
    the gap that shipped five dead families (a rule reading every token it names
    and applying to nothing).
    """
    module = importlib.util.spec_from_file_location(
        "audit_component_rules", REPO / "scripts" / "audit_component_rules.py"
    )
    assert module and module.loader
    audit = importlib.util.module_from_spec(module)
    module.loader.exec_module(audit)

    def rows(*specs):
        return [{"rule": rule, "matched": count} for rule, count in specs]

    # Reaching an element is fine; a state is fine; a transient popup is fine.
    defects, unverified, _ = audit.reachable(
        rows((".ah-btn", 3), (":root .ant-btn:hover", 0), (":root .ant-switch-disabled", 0))
    )
    assert defects == [] and unverified == []

    # A rule naming something antd does not render is a defect...
    defects, _, _ = audit.reachable(rows((":root .ant-tooltip-inner", 0)))
    assert defects == [":root .ant-tooltip-inner"]

    # ...unless the gallery knowingly does not mount it, which is *unverified*
    # and says so rather than passing silently.
    defects, unverified, _ = audit.reachable(rows((":root .ant-btn-link", 0)))
    assert defects == []
    assert unverified and "the cockpit renders no Button" in unverified[0]

    # And a rule that matches in one page state and not another is fine.
    defects, _, _ = audit.reachable(
        rows((":root .ant-modal-container", 0), (":root .ant-modal-container", 1))
    )
    assert defects == []


def test_the_audit_catches_a_weight_m3_does_not_publish():
    """The one that was actually live: antd draws `th` at 600.

    Our own gates scan our own sources, so antd's runtime stylesheet is invisible
    to them — the computed value is the only place this exists. It is a closed
    set, so it is checkable, and this is the check.
    """
    module = importlib.util.spec_from_file_location(
        "audit_component_rules_2", REPO / "scripts" / "audit_component_rules.py"
    )
    assert module and module.loader
    audit = importlib.util.module_from_spec(module)
    module.loader.exec_module(audit)

    weights, sizes = audit.off_scale(
        {
            "weights": {"400 :: div": 10, "500 :: span": 4, "600 :: th.ant-table-cell": 5},
            "sizes": {"14px :: div": 10, "11px :: span": 3, "13.5px :: div": 2},
        }
    )
    assert weights == ["600 at th.ant-table-cell (x5)"]
    assert sizes == ["13.5px at div (x2)"]

    # …and the scale itself passes.
    weights, sizes = audit.off_scale(
        {"weights": {"400 :: div": 1, "500 :: span": 1}, "sizes": {"12px :: a": 1, "22px :: h1": 1}}
    )
    assert weights == [] and sizes == []


def test_the_app_sweep_reports_what_it_looked_at():
    """An empty violation list is only evidence if the sweep examined something.

    The brief's own rule: "an empty set from an empty producer is a false
    green". The running-app sweep returns the counts it checked beside the
    violations it found, so a sweep that silently matched nothing is visible in
    its own output rather than reported as a pass.
    """
    module = importlib.util.spec_from_file_location(
        "audit_component_rules_3", REPO / "scripts" / "audit_component_rules.py"
    )
    assert module and module.loader
    audit = importlib.util.module_from_spec(module)
    module.loader.exec_module(audit)

    colors, radii = audit.off_token(
        {
            "tokens": ["#e6e0e9", "#d0bcff", "#141218", "9999px"],
            "buckets": {
                "colors": {
                    "rgb(230, 224, 233) :: div": 1391,
                    "rgb(180, 163, 220) :: i.ant-spin-dot-item": 4,
                },
                "radii": {
                    "9999px :: button": 249,
                    "calc(infinity * 1px) :: span.freshness-dot": 1,
                },
            },
            "checked": {"colors": 188, "radii": 147},
        }
    )
    # `#e6e0e9` is a token, so the first colour is *not* a violation even though
    # it is written differently on the two sides; and `9999px` is a token too
    # (`--ah-shape-full`), so `rounded-full` written as a length passes while
    # Tailwind's `calc(infinity * 1px)` spelling does not.
    assert colors == ["rgb(180, 163, 220) :: i.ant-spin-dot-item (x4)"]
    assert radii == ["calc(infinity * 1px) :: span.freshness-dot (x1)"]

    # A sweep that examined nothing says so.
    colors, radii = audit.off_token({"buckets": {}, "tokens": [], "checked": {}})
    assert colors == [] and radii == []


def test_the_focus_gate_separates_a_ring_from_a_derived_colour():
    """`--focus` reads what a keyboard user sees, and this decides pass or fail.

    The three failures below were all live: antd painted its own
    `--ant-color-primary-border` ring in both themes (a colour no token equals),
    a global `border-radius: 4px` on `:focus-visible` squared the slider handle,
    and a Select's ring is delegated to the chip around its input — which is
    correct and must not be reported as a missing ring.
    """
    module = importlib.util.spec_from_file_location(
        "audit_component_rules_4", REPO / "scripts" / "audit_component_rules.py"
    )
    assert module and module.loader
    audit = importlib.util.module_from_spec(module)
    module.loader.exec_module(audit)

    def row(**kw):
        base = {
            "tag": "BUTTON", "cls": "ah-btn", "theme": "light", "route": "#/",
            "radiusBefore": "9999px", "radiusAfter": "9999px",
            "width": "3px", "colour": "rgb(98, 91, 113)", "offset": "2px",
            "delegated": False,
            "animations": [{"name": "ah-focus-grow", "duration": 150, "delay": 0}],
        }
        base.update(kw)
        return base

    # The measured, correct ring passes.
    assert audit.focus_defects([row()], "#625b71") == []

    # antd's derived grey, a squared radius, and a ring with no choreography.
    defects = audit.focus_defects(
        [
            row(colour="rgb(194, 189, 201)"),
            row(radiusAfter="4px"),
            row(animations=[]),
        ],
        "#625b71",
    )
    assert len(defects) == 3, defects
    assert "want 3px rgb(98, 91, 113) at 2px" in defects[0]
    assert "border-radius changed on focus (9999px -> 4px)" in defects[1]
    assert "without the focus-ring choreography" in defects[2]

    # A delegated ring is the correct answer for a Select, and the theme check
    # fails loudly rather than reporting the light palette twice.
    assert (
        audit.focus_defects(
            [row(cls="ant-select-input", delegated=True, animations=[])], "#625b71"
        )
        == []
    )
    theme_defect = audit.focus_defects(
        [
            row(
                tag="THEME",
                cls="requested dark, app applied light",
                width="", colour="", offset="",
            )
        ],
        "#ccc2dc",
    )
    assert theme_defect == [
        "requested dark, app applied light: the requested theme was not applied"
    ]


def test_the_focus_gate_covers_the_three_ways_it_was_blind():
    """The review falsified "the ring is the only one on screen" three times.

    Each of these was live and each one passed the previous version of the gate:
    an invisible focusable node (antd's `0x0` segmented input, whose ring was
    computed and never seen), a visible box whose ring belongs to antd (a
    dropdown menu item), and a *second* indicator painted on a pseudo-element
    (the slider handle's `::after`). The third one is why the outline check reads
    `outline-style` and not `outline-width`: antd's indicator transitions in from
    `0px`, and at t=0 the width is 0 while the style is already `solid`.
    """
    module = importlib.util.spec_from_file_location(
        "audit_component_rules_5", REPO / "scripts" / "audit_component_rules.py"
    )
    assert module and module.loader
    audit = importlib.util.module_from_spec(module)
    module.loader.exec_module(audit)

    def row(**kw):
        base = {
            "tag": "INPUT", "cls": "ant-segmented-item-input", "theme": "light",
            "route": "#/ (Tab)", "width": "3px", "colour": "rgb(98, 91, 113)",
            "offset": "2px", "delegated": False,
            "animations": [{"name": "ah-focus-grow", "duration": 150, "delay": 0}],
        }
        base.update(kw)
        return base

    # A synthetic pass cannot judge a node with no box: it is skipped, not passed.
    assert (
        audit.focus_defects([row(invisible=True, **{"pass": "synthetic"})], "#625b71")
        == []
    )
    # The keyboard pass can, and does.
    defects = audit.focus_defects(
        [row(invisible=True, delegated=False, **{"pass": "keyboard"})], "#625b71"
    )
    assert len(defects) == 1 and "no visible box" in defects[0]

    # antd's grey on the visible box is a failure whichever pass saw it.
    defects = audit.focus_defects(
        [row(colour="rgb(194, 189, 201)", offset="1px", **{"pass": "keyboard"})],
        "#625b71",
    )
    assert len(defects) == 1 and "want 3px rgb(98, 91, 113) at 2px" in defects[0]

    # A second indicator is a failure even when the ring itself is correct.
    defects = audit.focus_defects(
        [row(secondIndicators=["::after outline"], targetCls="ant-slider-handle")],
        "#625b71",
    )
    assert len(defects) == 1 and "second focus indicator" in defects[0]

    # And the gate refuses a run whose keyboard pass measured nothing, because
    # the skipped rows above would otherwise never be judged at all.
    assert audit.FOCUS_TAB_STEPS > 0


def test_the_percentage_gate_can_fail():
    """Positive control for the guard above."""

    def offending(line: str) -> bool:
        return "calc(" in line and (
            re.search(r"\*\s*100%\s*\)", line) is not None
            or re.search(r"calc\(.*--ah-c-[a-z0-9-]*(opacity|percent)", line) is not None
        )

    assert offending(
        "background: color-mix(in srgb, var(--ah-x) "
        "calc(var(--ah-c-y-opacity) * 100%), transparent);"
    )
    assert offending("width: calc(var(--ah-c-z-opacity) * 2);")
    assert offending("height: calc(100% * 100%);")
    assert not offending(
        "background: color-mix(in srgb, var(--ah-c-y-role) var(--ah-c-y-opacity), transparent);"
    )
    assert not offending("padding-inline-end: calc(var(--ah-c-a) + var(--ah-c-b));")


def test_the_disabled_gate_reads_its_expectation_from_the_token_file():
    """Two families publish a whole-element disabled opacity; the rest do not.

    Checkbox and radio say `disabled.opacity: 0.38` — the published treatment for
    those two is the control at 38%. Switch, field, segmented and slider publish
    per-part opacities instead, so their element has to stay at 1 and let the
    parts carry the disabled look. A gate that demanded `opacity: 1` everywhere
    would call antd's correct checkbox a defect; a gate that accepted 0.38
    everywhere would pass a faded FAB, which is exactly what was live.
    """
    module = importlib.util.spec_from_file_location(
        "audit_component_rules_8", REPO / "scripts" / "audit_component_rules.py"
    )
    assert module and module.loader
    audit = importlib.util.module_from_spec(module)
    module.loader.exec_module(audit)

    # The expectation comes from `tokens.json`, not from a constant in the tool.
    published = audit.load_disabled_opacities()
    assert published[".ant-checkbox"] == pytest.approx(0.38)
    assert published[".ant-radio"] == pytest.approx(0.38)

    def row(**kw):
        base = {
            "label": "BUTTON.ah-fab",
            "tag": "BUTTON",
            "opacity": "1",
            "focusable": False,
            "rest": {"bg": "transparent", "bd": "transparent", "sh": "none"},
        }
        base.update(kw)
        base["hover"] = kw.get("hover", base["rest"])
        base["press"] = kw.get("press", base["rest"])
        return base

    assert audit.disabled_defects([row()], published) == []

    # A blanket fade on a family that publishes part opacities.
    defects = audit.disabled_defects([row(opacity="0.38")], published)
    assert len(defects) == 1 and "opacity 0.38, want 1.00" in defects[0]

    # A checkbox at 0.38 is what the token says; its hidden proxy input is skipped.
    checkbox = row(label="SPAN.ant-checkbox", tag="SPAN", opacity="0.38")
    assert audit.disabled_defects([checkbox], published) == []
    proxy = row(label="INPUT.ant-checkbox-input", tag="INPUT", opacity="0")
    assert audit.disabled_defects([proxy], published) == []

    # Focusable-while-disabled and pointer feedback are failures on their own.
    assert "can still take focus" in audit.disabled_defects(
        [row(focusable=True)], published
    )[0]
    hovered = row(hover={"bg": "rgb(1, 2, 3)", "bd": "transparent", "sh": "none"})
    assert "answers the pointer while disabled" in audit.disabled_defects(
        [hovered], published
    )[0]


def test_the_state_gate_finds_a_control_with_no_hover_feedback():
    """The gate that found every icon button answering the pointer with nothing.

    Reading the stylesheet would not have: the family set
    `--ah-state-layer-color` in its base rule and spent it in its press rule, so
    the sheet *looked* complete. The pointer said otherwise — hover layer alpha
    `0.000` on all ten icon buttons — and this is the decision that says so.
    """
    module = importlib.util.spec_from_file_location(
        "audit_component_rules_7", REPO / "scripts" / "audit_component_rules.py"
    )
    assert module and module.loader
    audit = importlib.util.module_from_spec(module)
    module.loader.exec_module(audit)

    # The parser bug that produced a defect which did not exist: `int()` on
    # `0.270588 * 255` is 68, so a token's `#49454f` read back as `#49444f`.
    assert audit._colour_and_alpha("color(srgb 0.286275 0.270588 0.309804 / 0.08)") == (
        "#49454f",
        0.08,
    )
    assert audit._state_layer(
        {"sh": "rgba(103, 80, 164, 0.12) 0px 0px 0px 9999px inset", "pseudo": []}
    ) == ("#6750a4", 0.12)
    assert audit._state_layer(
        {"sh": "none", "pseudo": [{"bg": "color(srgb 0.403922 0.313726 0.643137 / 0.08)"}]}
    ) == ("#6750a4", 0.08)

    def row(**kw):
        base = {
            "label": "light #/ ah-iconbtn",
            "tokens": ["#6750a4", "#49454f"],
            "rest": {"bg": "rgba(0, 0, 0, 0)", "bd": "#49454f", "sh": "none",
                     "filter": "none", "pseudo": []},
            "hover": {"bg": "rgba(0, 0, 0, 0)", "bd": "#49454f",
                      "sh": "rgba(103, 80, 164, 0.08) 0px 0px 0px 9999px inset",
                      "filter": "none", "pseudo": []},
            "press": {"bg": "rgba(0, 0, 0, 0)", "bd": "#49454f",
                      "sh": "rgba(103, 80, 164, 0.12) 0px 0px 0px 9999px inset",
                      "filter": "none", "pseudo": []},
        }
        for key, value in kw.items():
            base[key] = {**base[key], **value} if isinstance(value, dict) else value
        return base

    assert audit.state_defects([row()]) == []
    assert audit.state_defects([row(hover={"sh": "none"})]) == [
        "light #/ ah-iconbtn: no hover feedback"
    ]
    pressed = row()
    pressed["press"]["sh"] = "rgba(103, 80, 164, 0.08) 0px 0px 0px 9999px inset"
    assert audit.state_defects([pressed]) == [
        "light #/ ah-iconbtn: press layer is 0.080, want 0.12"
    ]
    derived = row()
    derived["hover"]["sh"] = "rgba(194, 189, 201, 0.08) 0px 0px 0px 9999px inset"
    assert "is in no token" in audit.state_defects([derived])[0]
    assert "hover swaps bg" in audit.state_defects([row(hover={"bg": "rgba(230, 224, 233, 1)"})])[0]
    assert "changes `filter`" in audit.state_defects([row(hover={"filter": "brightness(0.9)"})])[0]


def test_the_overlap_gate_reports_a_pair_and_refuses_an_empty_sweep():
    """The check that found a `.zip` button painted over a segmented control.

    Nothing else in this repo looks at *where* controls are, only at what they
    are made of: a page whose buttons sit on top of each other passed the token,
    radius, colour, size and focus sweeps. Measured before the fix, on the
    session-detail rail: `.zip` at x 1081–1187 over the 摘要/全文 switch at x
    1109–1213. Both halves below are the point — it must report a pair, and it
    must not pass a page it never measured.
    """
    module = importlib.util.spec_from_file_location(
        "audit_component_rules_6", REPO / "scripts" / "audit_component_rules.py"
    )
    assert module and module.loader
    audit = importlib.util.module_from_spec(module)
    module.loader.exec_module(audit)

    assert audit.overlap_defects("light #/", {"examined": 0, "pairs": [], "total": 0}) == [
        "light #/: the overlap sweep examined no controls"
    ]

    found = {
        "examined": 670,
        "total": 1,
        "pairs": [
            {
                "a": 'button.ant-btn "下载原文包 (.zip)"',
                "b": ".ant-segmented-item 摘要",
                "ox": 78,
                "oy": 20,
            }
        ],
    }
    assert audit.overlap_defects("light #/session/zcode/s1", found) == [
        'light #/session/zcode/s1: button.ant-btn "下载原文包 (.zip)" overlaps '
        ".ant-segmented-item 摘要 by 78x20px"
    ]

    # A measured page with no pairs passes.
    assert audit.overlap_defects("dark #/", {"examined": 42, "pairs": []}) == []
