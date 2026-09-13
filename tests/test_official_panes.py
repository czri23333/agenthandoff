"""The pane layout's official numbers, and every breakpoint in the sheets.

androidx keeps two things this repo had been guessing at. The adaptive pane
directive (`PaneScaffoldDirective.kt`) says how many panes a window width gets,
how wide a pane prefers to be and how much space sits between partitions; the
window size classes (`WindowSizeClass.kt`) say where those widths begin.

Both are vendored under `tests/fixtures/m3spec/androidx/` with a pinned sha256,
so this runs offline. The second test is the one that finds drift: a breakpoint
in `web/src/*.css` that is not one of the official bounds is an invented
threshold, and inventing thresholds is how a layout stops being Material.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "tests" / "fixtures" / "m3spec" / "androidx"
TOKENS = ROOT / "web" / "src" / "tokens.json"
SHEETS = (ROOT / "web" / "src" / "m3.css", ROOT / "web" / "src" / "index.css")


def _dp(name: str) -> int:
    """`internal val <name> = <n>.dp`, or a failure that names the file."""
    text = (SPEC / "PaneScaffoldDirective.kt").read_text(encoding="utf-8")
    found = re.search(rf"{name}\s*=\s*(\d+)\.dp", text)
    assert found, f"PaneScaffoldDirective.kt no longer publishes {name}"
    return int(found.group(1))


def _directive_branch(class_name: str) -> tuple[int, int]:
    """(max horizontal partitions, spacer in dp) for one width size class."""
    text = (SPEC / "PaneScaffoldDirective.kt").read_text(encoding="utf-8")
    start = text.index("when (windowAdaptiveInfo.windowSizeClass.minWidth)")
    end = text.index("val maxVerticalPartitions", start)
    block = text[start:end]
    marker = f"WidthSizeClasses.{class_name} ->"
    if marker in block:
        body = block.split(marker, 1)[1]
        body = body[: body.index("}")]
    else:
        # `else -> { … }` is the cap Large and Extra Large fall into.
        body = block.split("else ->", 1)[1]
        body = body[: body.index("}")]
    partitions = re.search(r"maxHorizontalPartitions\s*=\s*(\d+)", body)
    spacer = re.search(r"horizontalPartitionSpacerSize\s*=\s*(\d+)\.dp", body)
    assert partitions and spacer, f"the {class_name} branch changed shape"
    return int(partitions.group(1)), int(spacer.group(1))


def _size_class_bounds() -> dict[str, int]:
    text = (SPEC / "WindowSizeClass.kt").read_text(encoding="utf-8")
    wanted = (
        "WIDTH_DP_MEDIUM_LOWER_BOUND",
        "WIDTH_DP_EXPANDED_LOWER_BOUND",
        "WIDTH_DP_LARGE_LOWER_BOUND",
        "WIDTH_DP_EXTRA_LARGE_LOWER_BOUND",
        "HEIGHT_DP_MEDIUM_LOWER_BOUND",
        "HEIGHT_DP_EXPANDED_LOWER_BOUND",
    )
    out: dict[str, int] = {}
    for name in wanted:
        found = re.search(rf"const val {name}: Int = (\d+)", text)
        assert found, f"WindowSizeClass.kt no longer publishes {name}"
        out[name] = int(found.group(1))
    return out


def _pane_tokens() -> dict:
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    pane = data["component"].get("pane")
    assert pane, "tokens.json has no `pane` block"
    return pane


def test_the_pane_widths_and_spacer_are_the_official_numbers():
    pane = _pane_tokens()
    assert pane["preferredWidth"] == _dp("DefaultPreferredWidth") == 360
    assert pane["preferredWidthXL"] == _dp("DefaultPreferredWidthXL") == 412
    assert pane["spacer"] == 24, "the Expanded branches use a 24dp partition spacer"
    assert _dp("DefaultPreferredHeight") == 420


def test_the_partition_counts_are_the_official_ones():
    assert _directive_branch("Compact") == (1, 0)
    assert _directive_branch("Medium") == (1, 0)
    assert _directive_branch("Expanded") == (2, 24)
    # the `else` branch: Large and Extra Large, three partitions at most
    assert _directive_branch("Large") == (3, 24)


@pytest.mark.parametrize("sheet", SHEETS, ids=lambda p: p.name)
def test_every_breakpoint_in_the_sheets_is_a_size_class_bound(sheet: Path):
    """A threshold that is not an official bound is an invented one.

    `max-width: N` is the last width *below* a bound, so it is allowed to be
    `bound - 1`; that is the same threshold written the other way round.
    """
    bounds = {
        name: value
        for name, value in _size_class_bounds().items()
        if name.startswith("WIDTH_DP_")
    }
    official = set(bounds.values()) | {value - 1 for value in bounds.values()}
    text = sheet.read_text(encoding="utf-8")
    found = {int(n) for n in re.findall(r"@media \(m(?:in|ax)-width: (\d+)px\)", text)}
    assert found, f"{sheet.name} declares no width breakpoint"
    invented = sorted(found - official)
    assert not invented, (
        f"{sheet.name}: {invented} is not one of androidx.window's width size class "
        f"bounds {sorted(bounds.values())} (or one below one, for max-width)"
    )


def test_the_pane_layout_switches_at_the_official_boundaries():
    """The list-detail layout has to start where Expanded does, not near it."""
    m3 = (ROOT / "web" / "src" / "m3.css").read_text(encoding="utf-8")
    expanded = _size_class_bounds()["WIDTH_DP_EXPANDED_LOWER_BOUND"]
    assert f"@media (min-width: {expanded}px)" in m3, (
        f"m3.css has no breakpoint at the Expanded bound ({expanded}px): the pane "
        "layout would be keyed on an invented width"
    )
