"""Every per-component number we spend, checked against Google's own files.

`tests/test_official_palette.py` does this for colour roles and
`tests/test_official_layers.py` for shape / elevation / state / type / motion.
This is the same idea one layer up: the ~370 values in `gen_tokens.COMPONENTS`,
the anatomy of every control the cockpit draws.

The reason this file exists is that a component number is *plausible* far more
often than it is right. A 40dp button height, an 8dp chip corner, a 0.38
disabled ink — each of those renders, looks like Material, and can be wrong in a
way no screenshot shows. So each one is pointed at the exact member of an exact
Google file, and the test says what it cost when it disagrees.

Three kinds of evidence, all vendored verbatim under `tests/fixtures/m3spec/`
and pinned by sha256 in `PINS.tsv` (`scripts/fetch_m3spec.py` refetches them):

  * `androidx/*.kt` — the per-component token files, and `Chip.kt`, the one
    implementation vendored because it settles a disagreement between two of
    those token files.
  * `materialweb/tokens-*.scss` — material-web's published token sets, for the
    geometry androidx does not publish (field spacing, checkbox corner, tab
    indicator, menu item's shape).
  * `materialweb/*-internal-*.scss` — the CSS that actually paints those
    tokens, used for the two values that only exist as a formula there.

Anything we spend that Google does not publish is not silently mapped to
something similar: it goes in `OURS` (whole families) or `UNMAPPED_OK` (single
keys) with a reason, and `test_every_component_value_is_accounted_for` fails if
a new value appears in one of Google's families without an entry here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "tests" / "fixtures" / "m3spec"
ANDROIDX = "androidx/"
WEB = "materialweb/"

# androidx publishes `CornerExtraSmall` where material-web publishes
# `corner-extra-small`; our tokens use the short key from `SHAPE`. One table so
# the three spellings cannot drift apart.
SHAPE_FROM_OURS = {
    "none": "none",
    "xs": "extra-small",
    "sm": "small",
    "md": "medium",
    "lg": "large",
    "xl": "extra-large",
    "full": "full",
}
SHAPE_FROM_KOTLIN = {f"Corner{name.title().replace('-', '')}": name for name in SHAPE_FROM_OURS.values()}

# The shape scale's five *composed* corners are not one radius: each is a
# four-value list, so they are compared by name and checked in
# `test_the_composed_corners_are_still_the_official_five`.
COMPOSED_CORNERS = {"extra-small-top", "large-top", "large-start", "large-end", "extra-large-top"}


# ── The parsers ──────────────────────────────────────────────────────────────
#
# Kotlin token files are machine-generated and rigid: a member is either
# `inline val Name: <type>\n get() = <expr>` or `const val Name = <expr>`. They
# are read with regexes rather than a Kotlin parser on purpose — a real parser
# would be a dependency, and a rigid format is exactly what a regex is for.

_KOTLIN_VAL = re.compile(r"^[ \t]*(?:inline )?val (\w+): [^\n]+\n[ \t]*get\(\) = ([^\n]+)$", re.M)
_KOTLIN_CONST = re.compile(r"^[ \t]*const val (\w+) = ([^\n]+)$", re.M)
_KOTLIN_OBJECT = re.compile(r"internal object (\w+) \{")


def _kotlin_members(text: str) -> dict[str, str]:
    """`{"ObjectTokens.Member": "40.0.dp"}` for every object in the file."""

    members: dict[str, str] = {}
    for match in _KOTLIN_OBJECT.finditer(text):
        start = match.end()
        depth, cursor = 1, start
        while depth and cursor < len(text):
            if text[cursor] == "{":
                depth += 1
            elif text[cursor] == "}":
                depth -= 1
            cursor += 1
        body = text[start:cursor]
        for pattern in (_KOTLIN_VAL, _KOTLIN_CONST):
            for member in pattern.finditer(body):
                members[f"{match.group(1)}.{member.group(1)}"] = member.group(2).strip()
    return members


def _scss_pairs(text: str) -> dict[str, str]:
    """The `'key': value,` pairs of a token file's `values()` function.

    Two shapes exist in the same repository and both are handled: the pinned
    `versions/v0_192/` files `@return (` their map, while the current `tokens/`
    files assign it to `$tokens: (` and `@return $tokens;` at the end. Only the
    body of the function is scanned, and only pairs with a colon count, so the
    `$supported-tokens` list of bare names — a different map, listing what the
    component accepts — is not mistaken for values.

    Values are joined onto one line and comments are dropped, because a Sass
    value here wraps freely: `'container-shape':\n  map.get(...)` is one pair,
    and `map.get($deps, 'md-sys-color', 'on-surface')` contains a comma that
    must not end it.
    """

    if "@function values" not in text:
        return {}
    body = text.split("@function values", 1)[1]

    def skip_noise(index: int) -> int:
        while index < len(body):
            if body.startswith("//", index):
                index = body.find("\n", index)
                if index < 0:
                    return len(body)
                continue
            if body.startswith("/*", index):
                end = body.find("*/", index)
                index = len(body) if end < 0 else end + 2
                continue
            break
        return index

    pairs: dict[str, str] = {}
    cursor = 0
    while cursor < len(body):
        cursor = skip_noise(cursor)
        if cursor >= len(body):
            break
        if body[cursor] != "'":
            cursor += 1
            continue
        key_end = body.find("'", cursor + 1)
        key = body[cursor + 1 : key_end]
        after = skip_noise(key_end + 1)
        if after >= len(body) or body[after] != ":":
            cursor = key_end + 1
            continue
        start, depth, scan = after + 1, 0, after + 1
        while scan < len(body):
            char = body[scan]
            if char in "([{":
                depth += 1
            elif char in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif char == "," and depth == 0:
                break
            scan += 1
        value = body[start:scan]
        value = re.sub(r"//[^\n]*", " ", value)
        value = re.sub(r"/\*(?:.|\n)*?\*/", " ", value)
        pairs[key] = " ".join(value.split())
        cursor = scan + 1
    return pairs


def _kebab(name: str) -> str:
    """`OnSurfaceVariant` → `on-surface-variant`, `Level3` → `level3`."""

    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def _official_kotlin(expression: str):
    """A vendored Kotlin value, as the same shape our tokens use."""

    if expression.startswith("ColorSchemeKeyTokens."):
        return ("role", _kebab(expression.split(".", 1)[1]))
    if expression.startswith("ShapeKeyTokens."):
        rung = expression.split(".", 1)[1]
        if rung not in SHAPE_FROM_KOTLIN:
            raise KeyError(f"unknown corner rung {rung!r}")
        return ("shape", SHAPE_FROM_KOTLIN[rung])
    if expression.startswith("ElevationTokens."):
        return ("elev", expression.split(".", 1)[1].lower())
    if expression.startswith("TypographyKeyTokens."):
        return ("type", _kebab(expression.split(".", 1)[1]))
    number = re.fullmatch(r"([0-9.]+)\.dp", expression)
    if number:
        return ("num", float(number.group(1)))
    opacity = re.fullmatch(r"([0-9.]+)f", expression)
    if opacity:
        return ("num", float(opacity.group(1)))
    raise KeyError(f"unhandled Kotlin token value {expression!r}")


_TYPESCALE_SUFFIX = re.compile(r"-(size|line-height|tracking|weight|font)$")


def _official_scss(expression: str, indirections: dict[str, dict[str, str]]):
    """A material-web token value, resolved through at most one indirection."""

    layered = re.fullmatch(r"map\.get\((\$[\w-]+), '([^']+)', '([^']+)'\)", expression)
    if layered:
        _, layer, key = layered.groups()
        if layer == "md-sys-color":
            return ("role", key)
        if layer == "md-sys-shape":
            name = key[len("corner-") :] if key.startswith("corner-") else key
            return ("corner" if name in COMPOSED_CORNERS else "shape", name)
        if layer == "md-sys-elevation":
            return ("elev", key)
        if layer == "md-sys-typescale":
            return ("type", _TYPESCALE_SUFFIX.sub("", key))
        if layer == "md-sys-state":
            return ("state", key.replace("-state-layer-opacity", ""))
        raise KeyError(f"unknown dependency layer {layer!r}")
    indirect = re.fullmatch(r"map\.get\((\$[\w-]+), '([^']+)'\)", expression)
    if indirect:
        table_name, key = indirect.groups()
        if table_name not in indirections:
            raise KeyError(f"no vendored table for ${table_name}")
        return _official_scss(indirections[table_name][key], indirections)
    hardcoded = re.fullmatch(r"if\(\$exclude-hardcoded-values, null, ([0-9.]+)(?:px)?\)", expression)
    if hardcoded:
        return ("num", float(hardcoded.group(1)))
    plain = re.fullmatch(r"([0-9.]+)(?:px)?", expression)
    if plain:
        return ("num", float(plain.group(1)))
    if expression == "null":
        return None
    raise KeyError(f"unhandled Sass token value {expression!r}")


def _ours(value: object):
    """Our authored token, as the same shape: `@role:x` → `("role", "x")`."""

    if isinstance(value, str) and value.startswith("@"):
        kind, _, name = value[1:].partition(":")
        if kind == "role":
            return ("role", name)
        if kind == "shape":
            if name not in SHAPE_FROM_OURS:
                raise KeyError(f"unknown shape {name!r}")
            return ("shape", SHAPE_FROM_OURS[name])
        if kind == "corner":
            return ("corner", name)
        if kind == "elev":
            return ("elev", name)
        if kind == "type":
            return ("type", name)
        raise KeyError(f"unhandled reference @{kind}:{name}")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return ("num", float(value))
    return value


# ── The mapping ──────────────────────────────────────────────────────────────
#
# Our dotted token path → (vendored file, that file's member or token key).
# Grouped by family, in `COMPONENTS` order.

MAPPING: dict[str, tuple[str, str]] = {
    # material-web's focus ring is its own component with its own token set.
    "focusRing.width": (WEB + "tokens-_md-comp-focus-ring.scss", "width"),
    "focusRing.activeWidth": (WEB + "tokens-_md-comp-focus-ring.scss", "active-width"),
    "focusRing.color": (WEB + "tokens-_md-comp-focus-ring.scss", "color"),
    "focusRing.outwardOffset": (WEB + "tokens-_md-comp-focus-ring.scss", "outward-offset"),
    # Button: the three published sizes, then the colours each variant file
    # publishes for the one filled/tonal/elevated/outlined/text button.
    "button.sizes.small.height": (ANDROIDX + "ButtonSmallTokens.kt", "ButtonSmallTokens.ContainerHeight"),
    "button.sizes.small.leading": (ANDROIDX + "ButtonSmallTokens.kt", "ButtonSmallTokens.LeadingSpace"),
    "button.sizes.small.trailing": (ANDROIDX + "ButtonSmallTokens.kt", "ButtonSmallTokens.TrailingSpace"),
    "button.sizes.small.icon": (ANDROIDX + "ButtonSmallTokens.kt", "ButtonSmallTokens.IconSize"),
    "button.sizes.small.gap": (ANDROIDX + "ButtonSmallTokens.kt", "ButtonSmallTokens.IconLabelSpace"),
    "button.sizes.small.shape": (ANDROIDX + "ButtonSmallTokens.kt", "ButtonSmallTokens.ContainerShapeRound"),
    "button.sizes.small.shapeSquare": (ANDROIDX + "ButtonSmallTokens.kt", "ButtonSmallTokens.ContainerShapeSquare"),
    "button.sizes.small.shapePressed": (ANDROIDX + "ButtonSmallTokens.kt", "ButtonSmallTokens.PressedContainerShape"),
    "button.sizes.small.outlineWidth": (ANDROIDX + "ButtonSmallTokens.kt", "ButtonSmallTokens.OutlinedOutlineWidth"),
    "button.sizes.medium.height": (ANDROIDX + "ButtonMediumTokens.kt", "ButtonMediumTokens.ContainerHeight"),
    "button.sizes.medium.leading": (ANDROIDX + "ButtonMediumTokens.kt", "ButtonMediumTokens.LeadingSpace"),
    "button.sizes.medium.trailing": (ANDROIDX + "ButtonMediumTokens.kt", "ButtonMediumTokens.TrailingSpace"),
    "button.sizes.medium.icon": (ANDROIDX + "ButtonMediumTokens.kt", "ButtonMediumTokens.IconSize"),
    "button.sizes.medium.gap": (ANDROIDX + "ButtonMediumTokens.kt", "ButtonMediumTokens.IconLabelSpace"),
    "button.sizes.medium.shape": (ANDROIDX + "ButtonMediumTokens.kt", "ButtonMediumTokens.ContainerShapeRound"),
    "button.sizes.medium.shapeSquare": (ANDROIDX + "ButtonMediumTokens.kt", "ButtonMediumTokens.ContainerShapeSquare"),
    "button.sizes.medium.shapePressed": (ANDROIDX + "ButtonMediumTokens.kt", "ButtonMediumTokens.PressedContainerShape"),
    "button.sizes.medium.outlineWidth": (ANDROIDX + "ButtonMediumTokens.kt", "ButtonMediumTokens.OutlinedOutlineWidth"),
    "button.sizes.large.height": (ANDROIDX + "ButtonLargeTokens.kt", "ButtonLargeTokens.ContainerHeight"),
    "button.sizes.large.leading": (ANDROIDX + "ButtonLargeTokens.kt", "ButtonLargeTokens.LeadingSpace"),
    "button.sizes.large.trailing": (ANDROIDX + "ButtonLargeTokens.kt", "ButtonLargeTokens.TrailingSpace"),
    "button.sizes.large.icon": (ANDROIDX + "ButtonLargeTokens.kt", "ButtonLargeTokens.IconSize"),
    "button.sizes.large.gap": (ANDROIDX + "ButtonLargeTokens.kt", "ButtonLargeTokens.IconLabelSpace"),
    "button.sizes.large.shape": (ANDROIDX + "ButtonLargeTokens.kt", "ButtonLargeTokens.ContainerShapeRound"),
    "button.sizes.large.shapeSquare": (ANDROIDX + "ButtonLargeTokens.kt", "ButtonLargeTokens.ContainerShapeSquare"),
    "button.sizes.large.shapePressed": (ANDROIDX + "ButtonLargeTokens.kt", "ButtonLargeTokens.PressedContainerShape"),
    "button.sizes.large.outlineWidth": (ANDROIDX + "ButtonLargeTokens.kt", "ButtonLargeTokens.OutlinedOutlineWidth"),
    "button.typeRole": (ANDROIDX + "FilledTonalButtonTokens.kt", "FilledTonalButtonTokens.LabelTextFont"),
    "button.disabledContainer": (ANDROIDX + "FilledButtonTokens.kt", "FilledButtonTokens.DisabledContainerOpacity"),
    "button.disabledContent": (ANDROIDX + "FilledButtonTokens.kt", "FilledButtonTokens.DisabledLabelTextOpacity"),
    "button.elevation.rest": (ANDROIDX + "FilledButtonTokens.kt", "FilledButtonTokens.ContainerElevation"),
    "button.elevation.hover": (ANDROIDX + "FilledButtonTokens.kt", "FilledButtonTokens.HoveredContainerElevation"),
    "button.elevation.pressed": (ANDROIDX + "FilledButtonTokens.kt", "FilledButtonTokens.PressedContainerElevation"),
    "button.elevationElevated.rest": (ANDROIDX + "ElevatedButtonTokens.kt", "ElevatedButtonTokens.ContainerElevation"),
    "button.elevationElevated.hover": (ANDROIDX + "ElevatedButtonTokens.kt", "ElevatedButtonTokens.HoveredContainerElevation"),
    "button.elevationElevated.pressed": (ANDROIDX + "ElevatedButtonTokens.kt", "ElevatedButtonTokens.PressedContainerElevation"),
    "button.variant.filled.container": (ANDROIDX + "FilledButtonTokens.kt", "FilledButtonTokens.ContainerColor"),
    "button.variant.filled.content": (ANDROIDX + "FilledButtonTokens.kt", "FilledButtonTokens.LabelTextColor"),
    "button.variant.tonal.container": (ANDROIDX + "FilledTonalButtonTokens.kt", "FilledTonalButtonTokens.ContainerColor"),
    "button.variant.tonal.content": (ANDROIDX + "FilledTonalButtonTokens.kt", "FilledTonalButtonTokens.LabelTextColor"),
    "button.variant.elevated.container": (ANDROIDX + "ElevatedButtonTokens.kt", "ElevatedButtonTokens.ContainerColor"),
    "button.variant.elevated.content": (ANDROIDX + "ElevatedButtonTokens.kt", "ElevatedButtonTokens.LabelTextColor"),
    "button.variant.outlined.content": (ANDROIDX + "OutlinedButtonTokens.kt", "OutlinedButtonTokens.LabelTextColor"),
    "button.variant.outlined.outline": (ANDROIDX + "OutlinedButtonTokens.kt", "OutlinedButtonTokens.OutlineColor"),
    "button.variant.text.content": (ANDROIDX + "TextButtonTokens.kt", "TextButtonTokens.LabelColor"),
    # Icon button.
    "iconButton.small.height": (ANDROIDX + "SmallIconButtonTokens.kt", "SmallIconButtonTokens.ContainerHeight"),
    "iconButton.small.icon": (ANDROIDX + "SmallIconButtonTokens.kt", "SmallIconButtonTokens.IconSize"),
    "iconButton.small.shape": (ANDROIDX + "SmallIconButtonTokens.kt", "SmallIconButtonTokens.ContainerShapeRound"),
    "iconButton.small.shapeSquare": (ANDROIDX + "SmallIconButtonTokens.kt", "SmallIconButtonTokens.ContainerShapeSquare"),
    "iconButton.small.shapePressed": (ANDROIDX + "SmallIconButtonTokens.kt", "SmallIconButtonTokens.PressedContainerShape"),
    "iconButton.small.space.narrow": (ANDROIDX + "SmallIconButtonTokens.kt", "SmallIconButtonTokens.NarrowLeadingSpace"),
    "iconButton.small.space.default": (ANDROIDX + "SmallIconButtonTokens.kt", "SmallIconButtonTokens.DefaultLeadingSpace"),
    "iconButton.small.space.wide": (ANDROIDX + "SmallIconButtonTokens.kt", "SmallIconButtonTokens.WideLeadingSpace"),
    "iconButton.small.outlineWidth": (ANDROIDX + "SmallIconButtonTokens.kt", "SmallIconButtonTokens.OutlinedOutlineWidth"),
    "iconButton.disabledContainer": (ANDROIDX + "FilledIconButtonTokens.kt", "FilledIconButtonTokens.DisabledContainerOpacity"),
    "iconButton.disabledContent": (ANDROIDX + "FilledIconButtonTokens.kt", "FilledIconButtonTokens.DisabledOpacity"),
    "iconButton.variant.standard.content": (ANDROIDX + "IconButtonTokens.kt", "StandardIconButtonTokens.Color"),
    "iconButton.variant.filled.container": (ANDROIDX + "FilledIconButtonTokens.kt", "FilledIconButtonTokens.ContainerColor"),
    "iconButton.variant.filled.content": (ANDROIDX + "FilledIconButtonTokens.kt", "FilledIconButtonTokens.Color"),
    "iconButton.variant.tonal.container": (ANDROIDX + "FilledTonalIconButtonTokens.kt", "FilledTonalIconButtonTokens.ContainerColor"),
    "iconButton.variant.tonal.content": (ANDROIDX + "FilledTonalIconButtonTokens.kt", "FilledTonalIconButtonTokens.Color"),
    "iconButton.variant.outlined.content": (ANDROIDX + "OutlinedIconButtonTokens.kt", "OutlinedIconButtonTokens.Color"),
    "iconButton.variant.outlined.outline": (ANDROIDX + "OutlinedIconButtonTokens.kt", "OutlinedIconButtonTokens.OutlineColor"),
    # FAB. `sizes.medium.shape` is deliberately absent: FabMediumTokens.kt has
    # its `ContainerShape` commented out behind a missing corner rung, so the
    # 16dp we spend there is ours and is flagged as ours in the generator.
    "fab.sizes.small.size": (ANDROIDX + "FabSmallTokens.kt", "FabSmallTokens.ContainerWidth"),
    "fab.sizes.small.shape": (ANDROIDX + "FabSmallTokens.kt", "FabSmallTokens.ContainerShape"),
    "fab.sizes.small.icon": (ANDROIDX + "FabSmallTokens.kt", "FabSmallTokens.IconSize"),
    "fab.sizes.regular.size": (ANDROIDX + "FabBaselineTokens.kt", "FabBaselineTokens.ContainerWidth"),
    "fab.sizes.regular.shape": (ANDROIDX + "FabBaselineTokens.kt", "FabBaselineTokens.ContainerShape"),
    "fab.sizes.regular.icon": (ANDROIDX + "FabBaselineTokens.kt", "FabBaselineTokens.IconSize"),
    "fab.sizes.medium.size": (ANDROIDX + "FabMediumTokens.kt", "FabMediumTokens.ContainerWidth"),
    "fab.sizes.medium.icon": (ANDROIDX + "FabMediumTokens.kt", "FabMediumTokens.IconSize"),
    "fab.sizes.large.size": (ANDROIDX + "FabLargeTokens.kt", "FabLargeTokens.ContainerWidth"),
    "fab.sizes.large.shape": (ANDROIDX + "FabLargeTokens.kt", "FabLargeTokens.ContainerShape"),
    "fab.sizes.large.icon": (ANDROIDX + "FabLargeTokens.kt", "FabLargeTokens.IconSize"),
    "fab.container": (ANDROIDX + "FabPrimaryContainerTokens.kt", "FabPrimaryContainerTokens.ContainerColor"),
    "fab.content": (ANDROIDX + "FabPrimaryContainerTokens.kt", "FabPrimaryContainerTokens.IconColor"),
    "fab.elevation.rest": (ANDROIDX + "FabPrimaryContainerTokens.kt", "FabPrimaryContainerTokens.ContainerElevation"),
    "fab.elevation.hover": (ANDROIDX + "FabPrimaryContainerTokens.kt", "FabPrimaryContainerTokens.HoveredContainerElevation"),
    # Chip. The shapes come from the M3E base file because `Chip.kt` says so:
    # `Shapes.defaultChipShapes` builds the morphing chip from
    # `ChipsTokens.UnselectedShape / SelectedShape / PressedShape` (Chip.kt
    # line ~2889), one set for assist, filter and input alike.
    "chip.height": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.Height"),
    "chip.icon": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.LeadingIconSize"),
    "chip.avatar": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.AvatarSize"),
    "chip.typeRole": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.LabelText"),
    "chip.variant.assist.shape": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.UnselectedShape"),
    "chip.variant.filter.shape": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.UnselectedShape"),
    "chip.variant.input.shape": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.UnselectedShape"),
    "chip.variant.assist.shapePressed": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.PressedShape"),
    "chip.variant.filter.shapePressed": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.PressedShape"),
    "chip.variant.input.shapePressed": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.PressedShape"),
    "chip.variant.assist.content": (ANDROIDX + "AssistChipTokens.kt", "AssistChipTokens.LabelTextColor"),
    "chip.variant.assist.iconColor": (ANDROIDX + "AssistChipTokens.kt", "AssistChipTokens.IconColor"),
    "chip.variant.assist.outline": (ANDROIDX + "AssistChipTokens.kt", "AssistChipTokens.FlatOutlineColor"),
    "chip.variant.filter.content": (ANDROIDX + "FilterChipTokens.kt", "FilterChipTokens.UnselectedLabelTextColor"),
    "chip.variant.filter.outline": (ANDROIDX + "FilterChipTokens.kt", "FilterChipTokens.FlatUnselectedOutlineColor"),
    "chip.variant.input.content": (ANDROIDX + "InputChipTokens.kt", "InputChipTokens.UnselectedLabelTextColor"),
    "chip.variant.input.outline": (ANDROIDX + "InputChipTokens.kt", "InputChipTokens.UnselectedOutlineColor"),
    "chip.selected.shape": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.SelectedShape"),
    "chip.selected.container": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.SelectedContainerColor"),
    "chip.selected.content": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.SelectedLabelTextColor"),
    "chip.selected.iconColor": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.SelectedLeadingIconColor"),
    "chip.selected.outlineWidth": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.SelectedOutlineWidth"),
    "chip.unselectedOutlineWidth": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.UnselectedOutlineWidth"),
    "chip.disabledContainer": (ANDROIDX + "ChipsTokens.kt", "ChipsTokens.SelectedDisabledContainerOpacity"),
    "chip.disabledContent": (ANDROIDX + "FilterChipTokens.kt", "FilterChipTokens.DisabledLabelTextOpacity"),
    # List item.
    "listItem.height.oneLine": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemOneLineContainerHeight"),
    "listItem.height.twoLine": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemTwoLineContainerHeight"),
    "listItem.height.threeLine": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemThreeLineContainerHeight"),
    "listItem.leadingSpace": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemLeadingSpace"),
    "listItem.trailingSpace": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemTrailingSpace"),
    "listItem.icon": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemLeadingIconSize"),
    "listItem.avatar": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemLeadingAvatarSize"),
    "listItem.gap": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemBetweenSpace"),
    "listItem.typeRole.label": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemLabelTextFont"),
    "listItem.typeRole.supporting": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemSupportingTextFont"),
    "listItem.typeRole.overline": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemOverlineFont"),
    "listItem.shape.rest": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemContainerExpressiveShape"),
    "listItem.shape.hover": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemHoveredContainerExpressiveShape"),
    "listItem.shape.active": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemFocusedContainerExpressiveShape"),
    "listItem.container": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemContainerColor"),
    "listItem.label": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemLabelTextColor"),
    "listItem.supporting": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemSupportingTextColor"),
    "listItem.iconColor": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemLeadingIconColor"),
    "listItem.disabledContent": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemDisabledLabelTextOpacity"),
    # Switch.
    "switch.track.width": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.TrackWidth"),
    "switch.track.height": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.TrackHeight"),
    "switch.track.outlineWidth": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.TrackOutlineWidth"),
    "switch.track.shape": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.TrackShape"),
    "switch.handle.selected": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.SelectedHandleHeight"),
    "switch.handle.unselected": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.UnselectedHandleHeight"),
    "switch.handle.pressed": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.PressedHandleHeight"),
    "switch.handle.icon": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.SelectedIconSize"),
    "switch.stateLayer": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.StateLayerSize"),
    "switch.selected.track": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.SelectedTrackColor"),
    "switch.selected.handle": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.SelectedHandleColor"),
    "switch.selected.icon": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.SelectedIconColor"),
    "switch.unselected.track": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.UnselectedTrackColor"),
    "switch.unselected.handle": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.UnselectedHandleColor"),
    "switch.unselected.outline": (
        ANDROIDX + "SwitchTokens.kt",
        "SwitchTokens.UnselectedTrackOutlineColor",
    ),
    "switch.unselected.icon": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.UnselectedIconColor"),
    "switch.disabled.trackOpacity": (ANDROIDX + "SwitchTokens.kt", "SwitchTokens.DisabledTrackOpacity"),
    "switch.disabled.contentOpacity": (
        ANDROIDX + "SwitchTokens.kt",
        "SwitchTokens.DisabledUnselectedHandleOpacity",
    ),
    # Checkbox. The corner is the one value androidx does not publish at all.
    "checkbox.size": (ANDROIDX + "CheckboxTokens.kt", "CheckboxTokens.ContainerSize"),
    "checkbox.outlineWidth": (ANDROIDX + "CheckboxTokens.kt", "CheckboxTokens.UnselectedOutlineWidth"),
    "checkbox.stateLayer": (ANDROIDX + "CheckboxTokens.kt", "CheckboxTokens.StateLayerSize"),
    "checkbox.icon": (ANDROIDX + "CheckboxTokens.kt", "CheckboxTokens.IconSize"),
    "checkbox.selected.container": (ANDROIDX + "CheckboxTokens.kt", "CheckboxTokens.SelectedContainerColor"),
    "checkbox.selected.icon": (ANDROIDX + "CheckboxTokens.kt", "CheckboxTokens.SelectedIconColor"),
    "checkbox.unselected.outline": (
        ANDROIDX + "CheckboxTokens.kt",
        "CheckboxTokens.UnselectedOutlineColor",
    ),
    "checkbox.disabled.opacity": (
        ANDROIDX + "CheckboxTokens.kt",
        "CheckboxTokens.SelectedDisabledContainerOpacity",
    ),
    "checkbox.radius": (WEB + "tokens-versions-v0_192-_md-comp-checkbox.scss", "container-shape"),
    # Radio.
    "radio.size": (ANDROIDX + "RadioButtonTokens.kt", "RadioButtonTokens.IconSize"),
    "radio.stateLayer": (ANDROIDX + "RadioButtonTokens.kt", "RadioButtonTokens.StateLayerSize"),
    "radio.selected.icon": (ANDROIDX + "RadioButtonTokens.kt", "RadioButtonTokens.SelectedIconColor"),
    "radio.unselected.icon": (ANDROIDX + "RadioButtonTokens.kt", "RadioButtonTokens.UnselectedIconColor"),
    "radio.disabled.opacity": (
        ANDROIDX + "RadioButtonTokens.kt",
        "RadioButtonTokens.DisabledSelectedIconOpacity",
    ),
    # Segmented button.
    "segmented.height": (ANDROIDX + "OutlinedSegmentedButtonTokens.kt", "OutlinedSegmentedButtonTokens.ContainerHeight"),
    "segmented.shape": (ANDROIDX + "OutlinedSegmentedButtonTokens.kt", "OutlinedSegmentedButtonTokens.Shape"),
    "segmented.outlineWidth": (ANDROIDX + "OutlinedSegmentedButtonTokens.kt", "OutlinedSegmentedButtonTokens.OutlineWidth"),
    "segmented.icon": (ANDROIDX + "OutlinedSegmentedButtonTokens.kt", "OutlinedSegmentedButtonTokens.IconSize"),
    "segmented.typeRole": (ANDROIDX + "OutlinedSegmentedButtonTokens.kt", "OutlinedSegmentedButtonTokens.LabelTextFont"),
    "segmented.outline": (ANDROIDX + "OutlinedSegmentedButtonTokens.kt", "OutlinedSegmentedButtonTokens.OutlineColor"),
    "segmented.selected.container": (
        ANDROIDX + "OutlinedSegmentedButtonTokens.kt",
        "OutlinedSegmentedButtonTokens.SelectedContainerColor",
    ),
    "segmented.selected.content": (
        ANDROIDX + "OutlinedSegmentedButtonTokens.kt",
        "OutlinedSegmentedButtonTokens.SelectedLabelTextColor",
    ),
    "segmented.unselected.content": (
        ANDROIDX + "OutlinedSegmentedButtonTokens.kt",
        "OutlinedSegmentedButtonTokens.UnselectedLabelTextColor",
    ),
    "segmented.disabled.content": (
        ANDROIDX + "OutlinedSegmentedButtonTokens.kt",
        "OutlinedSegmentedButtonTokens.DisabledLabelTextOpacity",
    ),
    "segmented.disabled.outline": (
        ANDROIDX + "OutlinedSegmentedButtonTokens.kt",
        "OutlinedSegmentedButtonTokens.DisabledOutlineOpacity",
    ),
    # Dialog, and the scrim it sits on.
    "dialog.shape": (ANDROIDX + "DialogTokens.kt", "DialogTokens.ContainerShape"),
    "dialog.container": (ANDROIDX + "DialogTokens.kt", "DialogTokens.ContainerColor"),
    "dialog.elevation": (ANDROIDX + "DialogTokens.kt", "DialogTokens.ContainerElevation"),
    "dialog.headline": (ANDROIDX + "DialogTokens.kt", "DialogTokens.HeadlineColor"),
    "dialog.supporting": (ANDROIDX + "DialogTokens.kt", "DialogTokens.SupportingTextColor"),
    "dialog.action": (ANDROIDX + "DialogTokens.kt", "DialogTokens.ActionLabelTextColor"),
    "dialog.icon": (ANDROIDX + "DialogTokens.kt", "DialogTokens.IconColor"),
    "dialog.iconSize": (ANDROIDX + "DialogTokens.kt", "DialogTokens.IconSize"),
    "dialog.headlineTypeRole": (ANDROIDX + "DialogTokens.kt", "DialogTokens.HeadlineFont"),
    "dialog.supportingTypeRole": (ANDROIDX + "DialogTokens.kt", "DialogTokens.SupportingTextFont"),
    "dialog.actionTypeRole": (ANDROIDX + "DialogTokens.kt", "DialogTokens.ActionLabelTextFont"),
    "dialog.scrim.role": (ANDROIDX + "ScrimTokens.kt", "ScrimTokens.ContainerColor"),
    "dialog.scrim.opacity": (ANDROIDX + "ScrimTokens.kt", "ScrimTokens.ContainerOpacity"),
    # Progress.
    "progress.linear.height": (ANDROIDX + "LinearProgressIndicatorTokens.kt", "LinearProgressIndicatorTokens.Height"),
    "progress.linear.trackSpace": (
        ANDROIDX + "LinearProgressIndicatorTokens.kt",
        "LinearProgressIndicatorTokens.TrackActiveSpace",
    ),
    "progress.linear.stop": (ANDROIDX + "LinearProgressIndicatorTokens.kt", "LinearProgressIndicatorTokens.StopSize"),
    "progress.linear.wavelength": (
        ANDROIDX + "LinearProgressIndicatorTokens.kt",
        "LinearProgressIndicatorTokens.ActiveWaveWavelength",
    ),
    "progress.circular.size": (ANDROIDX + "CircularProgressIndicatorTokens.kt", "CircularProgressIndicatorTokens.Size"),
    "progress.circular.thickness": (
        ANDROIDX + "CircularProgressIndicatorTokens.kt",
        "CircularProgressIndicatorTokens.ActiveThickness",
    ),
    "progress.shape": (ANDROIDX + "ProgressIndicatorTokens.kt", "ProgressIndicatorTokens.ActiveShape"),
    "progress.active": (ANDROIDX + "ProgressIndicatorTokens.kt", "ProgressIndicatorTokens.ActiveIndicatorColor"),
    "progress.track": (ANDROIDX + "ProgressIndicatorTokens.kt", "ProgressIndicatorTokens.TrackColor"),
    "progress.stop": (ANDROIDX + "ProgressIndicatorTokens.kt", "ProgressIndicatorTokens.StopColor"),
    # Tooltip.
    "tooltip.container": (ANDROIDX + "PlainTooltipTokens.kt", "PlainTooltipTokens.ContainerColor"),
    "tooltip.content": (ANDROIDX + "PlainTooltipTokens.kt", "PlainTooltipTokens.SupportingTextColor"),
    "tooltip.shape": (ANDROIDX + "PlainTooltipTokens.kt", "PlainTooltipTokens.ContainerShape"),
    "tooltip.typeRole": (ANDROIDX + "PlainTooltipTokens.kt", "PlainTooltipTokens.SupportingTextFont"),
    # Badge.
    "badge.dot": (ANDROIDX + "BadgeTokens.kt", "BadgeTokens.Size"),
    "badge.large": (ANDROIDX + "BadgeTokens.kt", "BadgeTokens.LargeSize"),
    "badge.shape": (ANDROIDX + "BadgeTokens.kt", "BadgeTokens.LargeShape"),
    "badge.container": (ANDROIDX + "BadgeTokens.kt", "BadgeTokens.LargeColor"),
    "badge.content": (ANDROIDX + "BadgeTokens.kt", "BadgeTokens.LargeLabelTextColor"),
    "badge.typeRole": (ANDROIDX + "BadgeTokens.kt", "BadgeTokens.LargeLabelTextFont"),
    # Divider.
    "divider.thickness": (ANDROIDX + "DividerTokens.kt", "DividerTokens.Thickness"),
    "divider.color": (ANDROIDX + "DividerTokens.kt", "DividerTokens.Color"),
    # Snackbar.
    "snackbar.container": (ANDROIDX + "SnackbarTokens.kt", "SnackbarTokens.ContainerColor"),
    "snackbar.content": (ANDROIDX + "SnackbarTokens.kt", "SnackbarTokens.SupportingTextColor"),
    "snackbar.action": (ANDROIDX + "SnackbarTokens.kt", "SnackbarTokens.ActionLabelTextColor"),
    "snackbar.shape": (ANDROIDX + "SnackbarTokens.kt", "SnackbarTokens.ContainerShape"),
    "snackbar.elevation": (ANDROIDX + "SnackbarTokens.kt", "SnackbarTokens.ContainerElevation"),
    "snackbar.singleLine": (ANDROIDX + "SnackbarTokens.kt", "SnackbarTokens.SingleLineContainerHeight"),
    "snackbar.twoLine": (ANDROIDX + "SnackbarTokens.kt", "SnackbarTokens.TwoLinesContainerHeight"),
    "snackbar.iconSize": (ANDROIDX + "SnackbarTokens.kt", "SnackbarTokens.IconSize"),
    "snackbar.typeRole": (ANDROIDX + "SnackbarTokens.kt", "SnackbarTokens.SupportingTextFont"),
    "snackbar.actionTypeRole": (ANDROIDX + "SnackbarTokens.kt", "SnackbarTokens.ActionLabelTextFont"),
    # Top app bar.
    "appBar.small.height": (ANDROIDX + "AppBarSmallTokens.kt", "AppBarSmallTokens.ContainerHeight"),
    "appBar.small.titleTypeRole": (ANDROIDX + "AppBarSmallTokens.kt", "AppBarSmallTokens.TitleFont"),
    "appBar.small.subtitleTypeRole": (ANDROIDX + "AppBarSmallTokens.kt", "AppBarSmallTokens.SubtitleFont"),
    "appBar.medium.height": (ANDROIDX + "AppBarMediumTokens.kt", "AppBarMediumTokens.ContainerHeight"),
    # Navigation bar.
    "navigationBar.height": (ANDROIDX + "NavigationBarTokens.kt", "NavigationBarTokens.ContainerHeight"),
    "navigationBar.tallHeight": (ANDROIDX + "NavigationBarTokens.kt", "NavigationBarTokens.TallContainerHeight"),
    "navigationBar.container": (ANDROIDX + "NavigationBarTokens.kt", "NavigationBarTokens.ContainerColor"),
    "navigationBar.elevation": (ANDROIDX + "NavigationBarTokens.kt", "NavigationBarTokens.ContainerElevation"),
    "navigationBar.indicator.role": (
        ANDROIDX + "NavigationBarTokens.kt",
        "NavigationBarTokens.ItemActiveIndicatorColor",
    ),
    "navigationBar.indicator.height": (
        ANDROIDX + "NavigationBarHorizontalItemTokens.kt",
        "NavigationBarHorizontalItemTokens.ActiveIndicatorHeight",
    ),
    "navigationBar.indicator.shape": (
        ANDROIDX + "NavigationBarTokens.kt",
        "NavigationBarTokens.ItemActiveIndicatorShape",
    ),
    "navigationBar.indicator.leading": (
        ANDROIDX + "NavigationBarHorizontalItemTokens.kt",
        "NavigationBarHorizontalItemTokens.ActiveIndicatorLeadingSpace",
    ),
    "navigationBar.indicator.trailing": (
        ANDROIDX + "NavigationBarHorizontalItemTokens.kt",
        "NavigationBarHorizontalItemTokens.ActiveIndicatorTrailingSpace",
    ),
    "navigationBar.icon": (ANDROIDX + "NavigationBarHorizontalItemTokens.kt", "NavigationBarHorizontalItemTokens.IconSize"),
    "navigationBar.labelTypeRole": (ANDROIDX + "NavigationBarTokens.kt", "NavigationBarTokens.LabelTextFont"),
    "navigationBar.active.icon": (ANDROIDX + "NavigationBarTokens.kt", "NavigationBarTokens.ItemActiveIconColor"),
    "navigationBar.active.label": (ANDROIDX + "NavigationBarTokens.kt", "NavigationBarTokens.ItemActiveLabelTextColor"),
    "navigationBar.inactive.icon": (ANDROIDX + "NavigationBarTokens.kt", "NavigationBarTokens.ItemInactiveIconColor"),
    "navigationBar.inactive.label": (
        ANDROIDX + "NavigationBarTokens.kt",
        "NavigationBarTokens.ItemInactiveLabelTextColor",
    ),
    # Navigation rail.
    "navigationRail.item.height": (
        ANDROIDX + "NavigationRailBaselineItemTokens.kt",
        "NavigationRailBaselineItemTokens.ContainerHeight",
    ),
    "navigationRail.item.verticalSpace": (
        ANDROIDX + "NavigationRailBaselineItemTokens.kt",
        "NavigationRailBaselineItemTokens.ContainerVerticalSpace",
    ),
    "navigationRail.item.leading": (
        ANDROIDX + "NavigationRailBaselineItemTokens.kt",
        "NavigationRailBaselineItemTokens.ActiveIndicatorLeadingSpace",
    ),
    "navigationRail.item.trailing": (
        ANDROIDX + "NavigationRailBaselineItemTokens.kt",
        "NavigationRailBaselineItemTokens.ActiveIndicatorTrailingSpace",
    ),
    "navigationRail.item.iconLabelSpace": (
        ANDROIDX + "NavigationRailBaselineItemTokens.kt",
        "NavigationRailBaselineItemTokens.ActiveIndicatorIconLabelSpace",
    ),
    "navigationRail.item.icon": (ANDROIDX + "NavigationRailBaselineItemTokens.kt", "NavigationRailBaselineItemTokens.IconSize"),
    "navigationRail.item.headerSpace": (
        ANDROIDX + "NavigationRailBaselineItemTokens.kt",
        "NavigationRailBaselineItemTokens.HeaderSpaceMinimum",
    ),
    "navigationRail.indicator.shape": (
        ANDROIDX + "NavigationRailBaselineItemTokens.kt",
        "NavigationRailBaselineItemTokens.ActiveIndicatorShape",
    ),
    # Slider: the M3E handle is a bar, not a knob.
    "slider.handle.width": (ANDROIDX + "SliderTokens.kt", "SliderTokens.HandleWidth"),
    "slider.handle.height": (ANDROIDX + "SliderTokens.kt", "SliderTokens.HandleHeight"),
    "slider.handle.pressedWidth": (ANDROIDX + "SliderTokens.kt", "SliderTokens.PressedHandleWidth"),
    "slider.handle.focusWidth": (ANDROIDX + "SliderTokens.kt", "SliderTokens.FocusHandleWidth"),
    "slider.handle.shape": (ANDROIDX + "SliderTokens.kt", "SliderTokens.HandleShape"),
    "slider.track.height": (ANDROIDX + "SliderTokens.kt", "SliderTokens.ActiveTrackHeight"),
    "slider.track.shape": (ANDROIDX + "SliderTokens.kt", "SliderTokens.ActiveTrackShape"),
    "slider.stop.size": (ANDROIDX + "SliderTokens.kt", "SliderTokens.StopIndicatorSize"),
    "slider.stop.trailingSpace": (ANDROIDX + "SliderTokens.kt", "SliderTokens.StopIndicatorTrailingSpace"),
    "slider.active": (ANDROIDX + "SliderTokens.kt", "SliderTokens.ActiveTrackColor"),
    "slider.inactive": (ANDROIDX + "SliderTokens.kt", "SliderTokens.InactiveTrackColor"),
    "slider.handleColor": (ANDROIDX + "SliderTokens.kt", "SliderTokens.HandleColor"),
    "slider.stopColor": (ANDROIDX + "SliderTokens.kt", "SliderTokens.StopIndicatorColor"),
    "slider.valueIndicator.container": (
        ANDROIDX + "SliderTokens.kt",
        "SliderTokens.ValueIndicatorContainerColor",
    ),
    "slider.valueIndicator.content": (
        ANDROIDX + "SliderTokens.kt",
        "SliderTokens.ValueIndicatorLabelTextColor",
    ),
    "slider.valueIndicator.typeRole": (
        ANDROIDX + "SliderTokens.kt",
        "SliderTokens.ValueIndicatorLabelTextFont",
    ),
    "slider.disabled.activeTrack": (ANDROIDX + "SliderTokens.kt", "SliderTokens.DisabledActiveTrackOpacity"),
    "slider.disabled.inactiveTrack": (ANDROIDX + "SliderTokens.kt", "SliderTokens.DisabledInactiveTrackOpacity"),
    "slider.disabled.handle": (ANDROIDX + "SliderTokens.kt", "SliderTokens.DisabledHandleOpacity"),
    # Search bar.
    "searchBar.height": (ANDROIDX + "SearchBarTokens.kt", "SearchBarTokens.ContainerHeight"),
    "searchBar.shape": (ANDROIDX + "SearchBarTokens.kt", "SearchBarTokens.ContainerShape"),
    "searchBar.container": (ANDROIDX + "SearchBarTokens.kt", "SearchBarTokens.ContainerColor"),
    "searchBar.elevation": (ANDROIDX + "SearchBarTokens.kt", "SearchBarTokens.ContainerElevation"),
    "searchBar.leadingIconColor": (ANDROIDX + "SearchBarTokens.kt", "SearchBarTokens.LeadingIconColor"),
    "searchBar.trailingIconColor": (ANDROIDX + "SearchBarTokens.kt", "SearchBarTokens.TrailingIconColor"),
    "searchBar.inputColor": (ANDROIDX + "SearchBarTokens.kt", "SearchBarTokens.InputTextColor"),
    "searchBar.supportingColor": (ANDROIDX + "SearchBarTokens.kt", "SearchBarTokens.SupportingTextColor"),
    "searchBar.avatarSize": (ANDROIDX + "SearchBarTokens.kt", "SearchBarTokens.AvatarSize"),
    "searchBar.avatarShape": (ANDROIDX + "SearchBarTokens.kt", "SearchBarTokens.AvatarShape"),
    "searchBar.typeRole": (ANDROIDX + "SearchBarTokens.kt", "SearchBarTokens.InputTextFont"),
    # Primary tab.
    "primaryTab.height": (ANDROIDX + "PrimaryNavigationTabTokens.kt", "PrimaryNavigationTabTokens.ContainerHeight"),
    "primaryTab.iconHeight": (
        ANDROIDX + "PrimaryNavigationTabTokens.kt",
        "PrimaryNavigationTabTokens.IconAndLabelTextContainerHeight",
    ),
    "primaryTab.indicator.height": (
        ANDROIDX + "PrimaryNavigationTabTokens.kt",
        "PrimaryNavigationTabTokens.ActiveIndicatorHeight",
    ),
    "primaryTab.indicator.color": (
        ANDROIDX + "PrimaryNavigationTabTokens.kt",
        "PrimaryNavigationTabTokens.ActiveIndicatorColor",
    ),
    "primaryTab.container": (ANDROIDX + "PrimaryNavigationTabTokens.kt", "PrimaryNavigationTabTokens.ContainerColor"),
    "primaryTab.elevation": (ANDROIDX + "PrimaryNavigationTabTokens.kt", "PrimaryNavigationTabTokens.ContainerElevation"),
    "primaryTab.icon": (ANDROIDX + "PrimaryNavigationTabTokens.kt", "PrimaryNavigationTabTokens.IconSize"),
    "primaryTab.typeRole": (ANDROIDX + "PrimaryNavigationTabTokens.kt", "PrimaryNavigationTabTokens.LabelTextFont"),
    "primaryTab.active.icon": (ANDROIDX + "PrimaryNavigationTabTokens.kt", "PrimaryNavigationTabTokens.ActiveIconColor"),
    "primaryTab.active.label": (
        ANDROIDX + "PrimaryNavigationTabTokens.kt",
        "PrimaryNavigationTabTokens.ActiveLabelTextColor",
    ),
    "primaryTab.inactive.icon": (
        ANDROIDX + "PrimaryNavigationTabTokens.kt",
        "PrimaryNavigationTabTokens.InactiveIconColor",
    ),
    "primaryTab.inactive.label": (
        ANDROIDX + "PrimaryNavigationTabTokens.kt",
        "PrimaryNavigationTabTokens.InactiveLabelTextColor",
    ),
    # Docked toolbar.
    "dockedToolbar.height": (ANDROIDX + "DockedToolbarTokens.kt", "DockedToolbarTokens.ContainerHeight"),
    "dockedToolbar.container": (ANDROIDX + "DockedToolbarTokens.kt", "DockedToolbarTokens.ContainerColor"),
    "dockedToolbar.shape": (ANDROIDX + "DockedToolbarTokens.kt", "DockedToolbarTokens.ContainerShape"),
    "dockedToolbar.leadingSpace": (ANDROIDX + "DockedToolbarTokens.kt", "DockedToolbarTokens.ContainerLeadingSpace"),
    "dockedToolbar.trailingSpace": (
        ANDROIDX + "DockedToolbarTokens.kt",
        "DockedToolbarTokens.ContainerTrailingSpace",
    ),
    "dockedToolbar.minSpacing": (ANDROIDX + "DockedToolbarTokens.kt", "DockedToolbarTokens.ContainerMinSpacing"),
    "dockedToolbar.maxSpacing": (ANDROIDX + "DockedToolbarTokens.kt", "DockedToolbarTokens.ContainerMaxSpacing"),
    # Loading indicator.
    "loadingIndicator.container.width": (
        ANDROIDX + "LoadingIndicatorTokens.kt",
        "LoadingIndicatorTokens.ContainerWidth",
    ),
    "loadingIndicator.container.height": (
        ANDROIDX + "LoadingIndicatorTokens.kt",
        "LoadingIndicatorTokens.ContainerHeight",
    ),
    "loadingIndicator.container.shape": (
        ANDROIDX + "LoadingIndicatorTokens.kt",
        "LoadingIndicatorTokens.ContainerShape",
    ),
    "loadingIndicator.container.color": (
        ANDROIDX + "LoadingIndicatorTokens.kt",
        "LoadingIndicatorTokens.ContainedContainerColor",
    ),
    "loadingIndicator.active.size": (ANDROIDX + "LoadingIndicatorTokens.kt", "LoadingIndicatorTokens.ActiveSize"),
    "loadingIndicator.active.color": (
        ANDROIDX + "LoadingIndicatorTokens.kt",
        "LoadingIndicatorTokens.ContainedActiveColor",
    ),
    "loadingIndicator.active.shape": (
        ANDROIDX + "LoadingIndicatorTokens.kt",
        "LoadingIndicatorTokens.ContainerShape",
    ),
    "loadingIndicator.uncontained.size": (
        ANDROIDX + "LoadingIndicatorTokens.kt",
        "LoadingIndicatorTokens.ActiveSize",
    ),
    "loadingIndicator.uncontained.color": (
        ANDROIDX + "LoadingIndicatorTokens.kt",
        "LoadingIndicatorTokens.ActiveIndicatorColor",
    ),
    # Menu. The item's own shape and type are the list item's, which is where
    # M3 puts them — see the family's `_source`.
    "menu.container": (ANDROIDX + "MenuTokens.kt", "MenuTokens.ContainerColor"),
    "menu.shape": (ANDROIDX + "MenuTokens.kt", "MenuTokens.ContainerShape"),
    "menu.elevation": (ANDROIDX + "MenuTokens.kt", "MenuTokens.ContainerElevation"),
    "menu.itemShape": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemContainerExpressiveShape"),
    "menu.typeRole": (ANDROIDX + "ListTokens.kt", "ListTokens.ItemLabelTextFont"),
    "menu.content": (ANDROIDX + "StandardMenuTokens.kt", "StandardMenuTokens.ItemLabelTextColor"),
    "menu.selectedContainer": (ANDROIDX + "MenuTokens.kt", "MenuTokens.ListItemSelectedContainerColor"),
    "menu.selectedContent": (ANDROIDX + "MenuTokens.kt", "MenuTokens.ListItemSelectedLabelTextColor"),
    "menu.leadingIconColor": (
        ANDROIDX + "MenuTokens.kt",
        "MenuTokens.MenuListItemLeadingIconColor",
    ),
}

# The field family is compared against material-web's Sass rather than
# androidx's, because androidx publishes the field's *roles* and material-web
# publishes its spacing. `map.get($text-field, ...)` in the field token set is
# an indirection into the text-field token set, so that table comes along.
_FIELD_MAPS = {
    "$text-field": {
        "filled": WEB + "tokens-versions-v0_192-_md-comp-filled-text-field.scss",
        "outlined": WEB + "tokens-versions-v0_192-_md-comp-outlined-text-field.scss",
    }
}

FIELD_MAPPING = {
    "filled": {
        "space.top": "top-space",
        "space.bottom": "bottom-space",
        "space.leading": "leading-space",
        "space.trailing": "trailing-space",
        "space.content": "content-space",
        "withLabel.top": "with-label-top-space",
        "withLabel.bottom": "with-label-bottom-space",
        "supporting.top": "supporting-text-top-space",
        "supporting.leading": "supporting-text-leading-space",
        "supporting.trailing": "supporting-text-trailing-space",
        "filled.shape": "container-shape",
        "filled.container": "container-color",
        "filled.indicator": "active-indicator-color",
        "filled.indicatorHeight": "active-indicator-height",
        "filled.focusIndicator": "focus-active-indicator-color",
        "filled.focusIndicatorHeight": "focus-active-indicator-height",
        "filled.label": "label-text-color",
        "filled.labelFocus": "focus-label-text-color",
        "filled.input": "content-color",
        "disabled.container": "disabled-container-opacity",
        # `leading-icon-size` lives in the text-field set the field set delegates
        # to, so it is named as a (set, key) pair rather than a bare key.
        "iconSize": ("text-field", "leading-icon-size"),
        "error.color": ("text-field", "error-label-text-color"),
        "error.content": ("text-field", "error-input-text-color"),
        "disabled.content": ("text-field", "disabled-input-text-opacity"),
    },
    "outlined": {
        "labelPaddingBottom": "label-text-padding-bottom",
        "outlineLabelPadding": "outline-label-padding",
        "outlined.shape": "container-shape",
        "outlined.outline": "outline-color",
        "outlined.outlineWidth": "outline-width",
        "outlined.focusOutline": "focus-outline-color",
        "outlined.focusOutlineWidth": "focus-outline-width",
        "outlined.hoverOutline": "hover-outline-color",
        "outlined.label": "label-text-color",
        "outlined.labelFocus": "focus-label-text-color",
        "outlined.input": "content-color",
        "disabled.outline": "disabled-outline-opacity",
    },
}

# Values we spend that Google publishes somewhere other than a token member, or
# that are ours and stay ours. Every one names why, and the test checks the path
# still exists so a stale reason cannot outlive the value it excuses.
UNMAPPED_OK: dict[str, str] = {
    "fab.sizes.medium.shapeOurs": "a flag, not a value: it marks the 16dp above as ours",
    "fab.sizes.medium.shape": (
        "ours: FabMediumTokens.kt leaves ContainerShape commented out behind "
        "`ShapeKeyTokens.CornerLargeIncreased`, which no published set defines"
    ),
    "button.minWidth": (
        "the rendered minimum comes out of material-web button/internal/_shared.scss "
        "(`min-width: calc(64px - leading - trailing)`, which is 64px of box); "
        "test_only_css_formulas_still_hold reads that line"
    ),
    "chip.touchTarget": "material-web chips/internal/_shared.scss pads the 32dp chip to 48px",
    "focusRing.duration": "the same motion token the motion layer's own gate checks",
    "focusRing.easing": "focus/internal/_focus-ring.scss easing-emphasized, read by test_only_css_formulas_still_hold",
    "dialog.enter": "a spring, checked against androidx by tests/test_official_layers.py",
    "dialog.exit": "a spring, checked against androidx by tests/test_official_layers.py",
    "textField.height": "composed: top-space + body-large line-height + bottom-space = 16 + 24 + 16, checked below",
    "textField.heightDense": "ours: M3 publishes no dense field; the container spaces halve to 8 + 24 + 8",
    "textField.denseSpaces": "ours: the halved container space above",
    "textField.labelTypeRole": "label-text-font in the text-field token set",
    "textField.populatedTypeRole": "label-text-populated-size in the text-field token set",
    "textField.inputTypeRole": "input-text-font in the text-field token set",
    "textField.supportingTypeRole": "supporting-text-font in the text-field token set",
    "primaryTab.indicator.shape": (
        "3dp on the top corners only, which no shape rung can express; "
        "test_the_outlined_tab_indicator_is_three_on_top reads it from material-web"
    ),
    "primaryTab.stateLayer.shape": "ours: androidx publishes the tab's indicator, not a state-layer shape",
    "primaryTab.stateLayer.size": "ours: 40dp, the state-layer size M3 uses for a 24dp icon",
}

# Places where the honest answer is that Google publishes *nothing*: an outlined
# or text button has no container, and neither the standard nor the outlined
# icon button has one. Each entry names the member that must stay absent, so
# Google adding one shows up here rather than as a silently stale `None`.
NOT_PUBLISHED: dict[str, tuple[str, str, str]] = {
    "button.variant.outlined.container": (
        ANDROIDX + "OutlinedButtonTokens.kt",
        "OutlinedButtonTokens.ContainerColor",
        "an outlined button paints no container",
    ),
    "button.variant.text.container": (
        ANDROIDX + "TextButtonTokens.kt",
        "TextButtonTokens.ContainerColor",
        "a text button paints no container",
    ),
    "iconButton.variant.standard.container": (
        ANDROIDX + "IconButtonTokens.kt",
        "StandardIconButtonTokens.ContainerColor",
        "a standard icon button paints no container",
    ),
    "iconButton.variant.outlined.container": (
        ANDROIDX + "OutlinedIconButtonTokens.kt",
        "OutlinedIconButtonTokens.ContainerColor",
        "an outlined icon button paints no container",
    ),
    "chip.variant.assist.container": (
        ANDROIDX + "AssistChipTokens.kt",
        "AssistChipTokens.ContainerColor",
        "only the elevated assist chip has a container; we ship the flat one",
    ),
    "chip.variant.filter.container": (
        ANDROIDX + "FilterChipTokens.kt",
        "FilterChipTokens.ContainerColor",
        "only the elevated filter chip has a container; ours is flat and paints on selection",
    ),
    "chip.variant.input.container": (
        ANDROIDX + "InputChipTokens.kt",
        "InputChipTokens.ContainerColor",
        "an unselected input chip paints no container",
    ),
}

OURS_FAMILIES = {
    "emptyState": "M3 publishes no empty state; the mark borrows M3's 48dp container size",
    "spacing": "M3 publishes no spacing scale; this is the 4dp grid its geometry is built on",
}

# Where Google disagrees with itself, both sides are pinned, so the choice we
# documented cannot quietly become a description of nothing.
# One Google value is a corner rung we deliberately do not put on the scale:
# `CornerNone` is 0, and a seventh public `--ah-shape-*` for zero would be a
# token in search of a reader. The mapping still points at the official member;
# this set says the 0 and the `corner-none` are the same thing.
ZERO_IS_CORNER_NONE = {"dockedToolbar.shape"}

CONFLICTS: dict[str, tuple[str, str, object]] = {
    "chip rest corner: per-variant files vs the M3E base": (
        ANDROIDX + "AssistChipTokens.kt",
        "AssistChipTokens.ContainerShape",
        ("shape", "small"),
    ),
    "chip rest corner: the base file Chip.kt actually reads": (
        ANDROIDX + "ChipsTokens.kt",
        "ChipsTokens.UnselectedShape",
        ("shape", "medium"),
    ),
    "field focus outline: pinned v0_192 vs the current field token set": (
        WEB + "tokens-versions-v0_192-_md-comp-outlined-text-field.scss",
        "focus-outline-width",
        ("num", 2.0),
    ),
    "field focus outline: what the current set spends instead": (
        WEB + "tokens-_md-comp-outlined-field.scss",
        "focus-outline-width",
        ("num", 3.0),
    ),
    "list disabled ink: androidx vs material-web": (
        WEB + "tokens-versions-v0_192-_md-comp-list.scss",
        "list-item-disabled-label-text-opacity",
        ("num", 0.3),
    ),
    "menu selected ink: base menu vs the standard menu with icons": (
        ANDROIDX + "StandardMenuTokens.kt",
        "StandardMenuTokens.ItemSelectedContainerColor",
        ("role", "tertiary-container"),
    ),
}


def _field_source(table_name: str, table: dict, path: str) -> tuple[str, str] | None:
    """Where one `textField` value lives: the field set, or the text-field set.

    material-web splits the field in two: `tokens/_md-comp-<x>-field.scss`
    publishes the spacing and the outline, and delegates every ink and the
    container shape to `tokens/versions/v0_192/_md-comp-<x>-text-field.scss`. A
    mapping entry is a bare key in the first, or a `(set, key)` pair naming the
    second.
    """

    if not path.startswith("textField."):
        return None
    suffix = path.split(".", 1)[1]
    if suffix not in table:
        return None
    entry = table[suffix]
    if isinstance(entry, tuple):
        set_name, token_key = entry
        return (WEB + f"tokens-versions-v0_192-_md-comp-{table_name}-{set_name}.scss", token_key)
    return (WEB + f"tokens-_md-comp-{table_name}-field.scss", entry)


def _generator():
    module = importlib.util.spec_from_file_location(
        "gen_tokens_for_components", REPO / "scripts" / "gen_tokens.py"
    )
    assert module and module.loader
    gen = importlib.util.module_from_spec(module)
    module.loader.exec_module(gen)
    return gen


def _kotlin(path: str) -> dict[str, str]:
    return _kotlin_members((SPEC / path).read_text(encoding="utf-8"))


def _scss(path: str) -> dict[str, str]:
    return _scss_pairs((SPEC / path).read_text(encoding="utf-8"))


def _flat_ours(family: dict, prefix: str = "") -> dict[str, object]:
    flat: dict[str, object] = {}
    for key, value in family.items():
        if key == "_source":
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flat_ours(value, path))
        else:
            flat[path] = value
    return flat


def _official_for(gen, our_path: str, source: tuple[str, str]):
    file, key = source
    if file.startswith(ANDROIDX):
        table = _kotlin(file)
        if key not in table:
            raise AssertionError(f"{our_path}: {file} has no member {key!r}")
        return _official_kotlin(table[key])
    table = _scss(file)
    if key not in table:
        raise AssertionError(f"{our_path}: {file} has no token {key!r}")
    if file.startswith(WEB + "tokens-_md-comp-filled-field.scss"):
        indirections = {"$text-field": _scss(_FIELD_MAPS["$text-field"]["filled"])}
    elif file.startswith(WEB + "tokens-_md-comp-outlined-field.scss"):
        indirections = {"$text-field": _scss(_FIELD_MAPS["$text-field"]["outlined"])}
    else:
        indirections = {}
    return _official_scss(table[key], indirections)


def test_the_component_fixtures_are_the_pinned_files():
    """PINS.tsv covers every vendored file, in both directions."""

    pins: dict[str, str] = {}
    for line in (SPEC / "PINS.tsv").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        digest, name = line.split("\t")
        pins[name] = digest
    on_disk = {
        path.relative_to(SPEC).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for folder in ("androidx", "materialweb")
        for path in (SPEC / folder).rglob("*")
        if path.is_file()
    }
    assert len(pins) >= 140, f"only {len(pins)} pinned files; the corpus shrank"
    assert set(on_disk) == set(pins), {
        "added": sorted(set(on_disk) - set(pins))[:10],
        "removed": sorted(set(pins) - set(on_disk))[:10],
    }
    changed = {name: (pins[name], on_disk[name]) for name in pins if pins[name] != on_disk[name]}
    assert not changed, changed


def test_every_mapped_value_matches_the_official_file():
    """The mechanical part: our value, Google's value, and the difference."""

    gen = _generator()
    differences = {}
    compared = 0
    for family, spec in gen.COMPONENTS.items():
        ours = _flat_ours(spec, family)
        for path, value in sorted(ours.items()):
            source = MAPPING.get(path)
            if source is None and family == "textField":
                for table_file, table in FIELD_MAPPING.items():
                    source = _field_source(table_file, table, path)
                    if source is not None:
                        break
            if source is None:
                continue
            compared += 1
            mine, theirs = _ours(value), _official_for(gen, path, source)
            if path in ZERO_IS_CORNER_NONE and mine == ("num", 0.0) and theirs == ("shape", "none"):
                continue
            if mine != theirs:
                differences[path] = {"ours": mine, "official": theirs, "source": source}
    assert compared >= 150, f"only {compared} values were compared; the mapping shrank"
    assert not differences, differences


def test_every_component_value_is_accounted_for():
    """No value in one of Google's families may be missing from the mapping.

    This is what stops the mapping rotting: add a number to a Google-sourced
    family and it fails here until it is either mapped to a file or excused in
    `UNMAPPED_OK` with a reason.
    """

    gen = _generator()
    unaccounted: dict[str, object] = {}
    for family, spec in gen.COMPONENTS.items():
        if family in OURS_FAMILIES:
            continue
        for path, value in sorted(_flat_ours(spec, family).items()):
            if path in MAPPING or path in UNMAPPED_OK or path in NOT_PUBLISHED:
                continue
            if family == "textField" and path.split(".", 1)[1] in {
                key for table in FIELD_MAPPING.values() for key in table
            }:
                continue
            unaccounted[path] = value
    assert not unaccounted, unaccounted

    stale = sorted(
        path
        for path in UNMAPPED_OK
        if path not in {
            leaf
            for family, spec in gen.COMPONENTS.items()
            for leaf in _flat_ours(spec, family)
        }
    )
    assert not stale, f"UNMAPPED_OK excuses paths that no longer exist: {stale}"
    assert set(OURS_FAMILIES) <= set(gen.COMPONENTS)


def test_the_variants_with_no_container_really_have_none():
    """`None` is a claim about Google's files, so it is checked like one."""

    gen = _generator()
    for path, (file, member, reason) in NOT_PUBLISHED.items():
        table = _kotlin(file) if file.startswith(ANDROIDX) else _scss(file)
        assert member not in table, f"{path}: {file} now publishes {member} ({reason})"
        node: object = gen.COMPONENTS
        for step in path.split("."):
            node = node[step]  # type: ignore[index]
        assert node is None, (
            f"{path}: we now spend {node!r}, so 'Google publishes no such member' "
            "is no longer the reason it is unmapped"
        )


def test_the_ones_we_do_not_spend_are_still_what_we_said():
    """Both sides of every documented disagreement, pinned."""

    for label, (file, key, expected) in CONFLICTS.items():
        if file.startswith(ANDROIDX):
            table = _kotlin(file)
            assert key in table, f"{label}: {key!r} left {file}"
            found = _official_kotlin(table[key])
        else:
            table = _scss(file)
            assert key in table, f"{label}: {key!r} left {file}"
            indirections = {}
            if file.endswith("tokens-_md-comp-outlined-field.scss"):
                indirections = {"$text-field": _scss(_FIELD_MAPS["$text-field"]["outlined"])}
            found = _official_scss(table[key], indirections)
        assert found == expected, f"{label}: {file} now says {found}, not {expected}"


def test_the_chip_shape_comes_from_the_expressive_defaults():
    """The one place an implementation decides which token file wins.

    `AssistChipDefaults.shape` reads `AssistChipTokens.ContainerShape`
    (corner-small), but the morphing chip every M3E surface gets is built by
    `Shapes.defaultChipShapes` from `ChipsTokens.UnselectedShape` (corner-medium).
    We implement the morph — the press changes the corner — so the base file is
    ours, and this test is why we know that is not an opinion.
    """

    text = (SPEC / "androidx" / "Chip.kt").read_text(encoding="utf-8")
    expressive = text.split("internal val Shapes.defaultChipShapes", 1)
    assert len(expressive) == 2, "defaultChipShapes disappeared from Chip.kt"
    block = expressive[1][:400]
    for member in ("ChipsTokens.UnselectedShape", "ChipsTokens.SelectedShape", "ChipsTokens.PressedShape"):
        assert member in block, f"defaultChipShapes no longer reads {member}"
    for variant in ("Assist", "Filter", "Input"):
        assert f"get() = {variant}ChipTokens.ContainerShape.value" in text, (
            f"{variant}ChipDefaults.shape no longer reads its own token file"
        )


def test_only_css_formulas_still_hold():
    """The two values that exist only as a formula in material-web's CSS."""

    button = (SPEC / "materialweb" / "button-internal-_shared.scss").read_text(encoding="utf-8")
    # material-web subtracts the paddings from the 64px, because its `min-width`
    # applies to the content box: the *button* is still 64px wide.
    assert re.search(
        r"min-width:\s*calc\(64px - var\(--_leading-space\) - var\(--_trailing-space\)\);", button
    ), "the button min-width left material-web"

    chips = (SPEC / "materialweb" / "chips-internal-_shared.scss").read_text(encoding="utf-8")
    assert re.search(r"margin:\s*max\(0,\s*\(48px - \$height\) / 2\)", chips) or re.search(
        r"48px", chips
    ), "the chip touch target left material-web"

    ring = (SPEC / "materialweb" / "focus-internal-_focus-ring.scss").read_text(encoding="utf-8")
    assert "animation-duration: calc($duration * 0.25), calc($duration * 0.75);" in ring
    assert "map.get($_md-sys-motion, 'easing-emphasized')" in ring


def test_the_field_geometry_adds_up_to_the_height_we_publish():
    """56dp is not a token in the field set: it is three tokens added up.

    The sum is what the cockpit's field actually renders at, so it is checked
    rather than asserted: top-space + the body-large line-height + bottom-space.
    """

    gen = _generator()
    values = _scss(WEB + "tokens-versions-v0_192-_md-comp-filled-text-field.scss")
    assert _official_scss(values["input-text-line-height"], {}) == (
        "type",
        "body-large",
    ), "the filled field's content line-height is no longer body-large"
    line = gen.TYPESCALE["body-large"]["line"]
    composed = (
        gen.COMPONENTS["textField"]["space"]["top"]
        + line
        + gen.COMPONENTS["textField"]["space"]["bottom"]
    )
    assert composed == gen.COMPONENTS["textField"]["height"], (
        f"{composed} != the published {gen.COMPONENTS['textField']['height']}dp field height"
    )


def test_the_outlined_tab_indicator_is_three_on_top():
    """M3E's tab indicator rounds only its top corners, at the indicator's own
    height — which is why the generator refuses to point it at `@shape:xs`."""

    gen = _generator()
    values = _scss(WEB + "tokens-versions-v0_192-_md-comp-primary-navigation-tab.scss")
    shape = values["active-indicator-shape"]
    numbers = [float(n) for n in re.findall(r"([0-9.]+)px", shape)]
    assert numbers[:2] == [gen.COMPONENTS["primaryTab"]["indicator"]["shape"]] * 2, shape
    assert numbers[2:] == [0.0, 0.0], shape


def test_the_composed_corners_are_still_the_official_five():
    """A composed corner is four radii, so it is compared by name, not by value.

    The five names come from material-web's shape file (`corner-extra-small-top`
    and friends — the ones whose value is a four-number list); if Google adds or
    removes one, the comparison in the mapping above would silently start
    treating it as a simple corner, so this pins the list.
    """

    gen = _generator()
    pairs = _scss_pairs((SPEC / "md-sys-shape.scss").read_text(encoding="utf-8"))
    official = {
        key[len("corner-") :]
        for key, value in pairs.items()
        if key.startswith("corner-") and len(re.findall(r"[0-9.]+px", value)) == 4
    }
    assert official == COMPOSED_CORNERS, official ^ COMPOSED_CORNERS
    assert set(gen.COMPOSED_CORNERS) == COMPOSED_CORNERS


def test_each_google_family_has_at_least_one_mapped_value():
    """A family with no mapping is a family this file does not actually check."""

    gen = _generator()
    families = [name for name in gen.COMPONENTS if name not in OURS_FAMILIES]
    mapped = {path.split(".")[0] for path in MAPPING}
    # The field family is compared through FIELD_MAPPING, whose keys are
    # relative to the family, so it has no entries in MAPPING itself.
    mapped.add("textField")
    unmapped = [family for family in families if family not in mapped]
    assert not unmapped, unmapped
    assert len(families) >= 20, len(families)
