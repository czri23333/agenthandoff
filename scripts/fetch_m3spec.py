"""Re-fetch the vendored Google spec files under `tests/fixtures/m3spec/`.

Every number this project attributes to Google lives next to a first-hand copy
of the file it came from, and `tests/test_official_*.py` assert those copies by
sha256. This script is how those copies got there, so the pins can be re-derived
instead of believed: run it, diff the tree, and a changed file shows up as a
changed hash in the test.

    python scripts/fetch_m3spec.py            # fetch everything, print hashes
    python scripts/fetch_m3spec.py --only button

Sources, both public:

  * androidx `compose/material3/material3/src/commonMain/kotlin/androidx/compose/
    material3/tokens/` on `androidx-main` — the per-component token files, each
    stamped `// VERSION: v0_14_0`. Apache-2.0.
  * material-components/material-web on `main` — `tokens/versions/v0_192/` for
    the published CSS token sets and `<component>/internal/*.scss` for the
    geometry its own CSS uses. Apache-2.0.

The network is the only nondeterministic part, so the script retries and falls
back to jsDelivr's mirror of the same commit before giving up.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "tests" / "fixtures" / "m3spec"

ANDROIDX_TOKENS = (
    "https://raw.githubusercontent.com/androidx/androidx/androidx-main/"
    "compose/material3/material3/src/commonMain/kotlin/androidx/compose/material3/tokens/"
)
ANDROIDX_MIRROR = (
    "https://cdn.jsdelivr.net/gh/androidx/androidx@androidx-main/"
    "compose/material3/material3/src/commonMain/kotlin/androidx/compose/material3/tokens/"
)
# One level up from `tokens/`: the component implementations themselves.
ANDROIDX_MATERIAL3 = ANDROIDX_TOKENS.rsplit("tokens/", 1)[0]
ANDROIDX_MATERIAL3_MIRROR = ANDROIDX_MIRROR.rsplit("tokens/", 1)[0]
MATERIAL_WEB = "https://raw.githubusercontent.com/material-components/material-web/main/"
MATERIAL_WEB_MIRROR = "https://cdn.jsdelivr.net/gh/material-components/material-web@main/"

# local path under tests/fixtures/m3spec/  ->  (primary URL, mirror URL)
MANIFEST: dict[str, tuple[str, str]] = {}


def _androidx(*names: str) -> None:
    for name in names:
        MANIFEST[f"androidx/{name}"] = (
            ANDROIDX_TOKENS + name,
            ANDROIDX_MIRROR + name,
        )


def _androidx_impl(*names: str) -> None:
    """A component implementation, which lives one directory above `tokens/`."""
    for name in names:
        MANIFEST[f"androidx/{name}"] = (
            ANDROIDX_MATERIAL3 + name,
            ANDROIDX_MATERIAL3_MIRROR + name,
        )


def _web(path: str) -> None:
    flat = path.replace("/", "-")
    MANIFEST[f"materialweb/{flat}"] = (MATERIAL_WEB + path, MATERIAL_WEB_MIRROR + path)


def _web_versioned(*names: str) -> None:
    for name in names:
        _web(f"tokens/versions/v0_192/{name}")


def _web_current(*names: str) -> None:
    for name in names:
        _web(f"tokens/{name}")


def _web_internal(*paths: str) -> None:
    for path in paths:
        MANIFEST[f"materialweb/{path.replace('/', '-')}"] = (
            MATERIAL_WEB + path,
            MATERIAL_WEB_MIRROR + path,
        )


# ── Button family ────────────────────────────────────────────────────────────
_androidx(
    "BaselineButtonTokens.kt",
    "ButtonXSmallTokens.kt",
    "ButtonSmallTokens.kt",
    "ButtonMediumTokens.kt",
    "ButtonLargeTokens.kt",
    "ButtonXLargeTokens.kt",
    "FilledButtonTokens.kt",
    "FilledTonalButtonTokens.kt",
    "TonalButtonTokens.kt",
    "ElevatedButtonTokens.kt",
    "OutlinedButtonTokens.kt",
    "TextButtonTokens.kt",
)
_web_internal("button/internal/_shared.scss")
_web_versioned(
    "_md-comp-filled-button.scss",
    "_md-comp-filled-tonal-button.scss",
    "_md-comp-elevated-button.scss",
    "_md-comp-outlined-button.scss",
    "_md-comp-text-button.scss",
)

# ── Icon button family ───────────────────────────────────────────────────────
_androidx(
    "IconButtonTokens.kt",
    "XSmallIconButtonTokens.kt",
    "SmallIconButtonTokens.kt",
    "MediumIconButtonTokens.kt",
    "LargeIconButtonTokens.kt",
    "XLargeIconButtonTokens.kt",
    "FilledIconButtonTokens.kt",
    "FilledTonalIconButtonTokens.kt",
    "OutlinedIconButtonTokens.kt",
)
_web_internal("iconbutton/internal/_shared.scss")
_web_versioned(
    "_md-comp-icon-button.scss",
    "_md-comp-filled-icon-button.scss",
    "_md-comp-filled-tonal-icon-button.scss",
    "_md-comp-outlined-icon-button.scss",
)

# ── FAB family ───────────────────────────────────────────────────────────────
_androidx(
    "FabBaselineTokens.kt",
    "FabSmallTokens.kt",
    "FabMediumTokens.kt",
    "FabLargeTokens.kt",
    "FabPrimaryContainerTokens.kt",
    "FabSecondaryContainerTokens.kt",
)
_web_internal("fab/internal/_fab.scss")
_web_versioned(
    "_md-comp-fab-primary.scss",
    "_md-comp-fab-primary-small.scss",
    "_md-comp-fab-primary-large.scss",
    "_md-comp-fab-secondary.scss",
    "_md-comp-fab-secondary-small.scss",
    "_md-comp-fab-secondary-large.scss",
)

# ── Chip family ──────────────────────────────────────────────────────────────
_androidx(
    "ChipsTokens.kt",
    "AssistChipTokens.kt",
    "SuggestionChipTokens.kt",
    "FilterChipTokens.kt",
    "InputChipTokens.kt",
)
_web_internal("chips/internal/_shared.scss")
_web_versioned(
    "_md-comp-assist-chip.scss",
    "_md-comp-suggestion-chip.scss",
    "_md-comp-filter-chip.scss",
    "_md-comp-input-chip.scss",
)

# ── List, menu, tab, toolbar, loading ────────────────────────────────────────
_androidx(
    "ListTokens.kt",
    "MenuTokens.kt",
    "StandardMenuTokens.kt",
    "VibrantMenuTokens.kt",
    "PrimaryNavigationTabTokens.kt",
    "SecondaryNavigationTabTokens.kt",
    "DockedToolbarTokens.kt",
    "LoadingIndicatorTokens.kt",
    "ExpandedListTokens.kt",
    "ReorderListTokens.kt",
    "RevealListTokens.kt",
)
_web_internal("list/internal/_list.scss")
_web_internal("menu/internal/_menu.scss")
_web_current("_md-comp-list-item.scss", "_md-comp-menu-item.scss", "_md-comp-item.scss")
_web_versioned(
    "_md-comp-list.scss",
    "_md-comp-menu.scss",
    "_md-comp-primary-navigation-tab.scss",
    "_md-comp-secondary-navigation-tab.scss",
)

# ── Text field ───────────────────────────────────────────────────────────────
_androidx("FilledTextFieldTokens.kt", "OutlinedTextFieldTokens.kt")
_web_internal("field/internal/_shared.scss")
_web_current(
    "_md-comp-filled-field.scss",
    "_md-comp-outlined-field.scss",
    # The `field` token sets above delegate their inks and the container shape to
    # the `text-field` set in the same directory; both layers are cited, so both
    # are vendored.
    "_md-comp-filled-text-field.scss",
    "_md-comp-outlined-text-field.scss",
)
_web_versioned("_md-comp-filled-text-field.scss", "_md-comp-outlined-text-field.scss")

# ── Selection controls ───────────────────────────────────────────────────────
_androidx(
    "SwitchTokens.kt",
    "CheckboxTokens.kt",
    "RadioButtonTokens.kt",
    "OutlinedSegmentedButtonTokens.kt",
    "SliderTokens.kt",
)
_web_internal(
    "switch/internal/_switch.scss",
    "checkbox/internal/_checkbox.scss",
    "radio/internal/_radio.scss",
    "slider/internal/_slider.scss",
)
_web_versioned(
    "_md-comp-switch.scss",
    "_md-comp-checkbox.scss",
    "_md-comp-radio-button.scss",
    "_md-comp-outlined-segmented-button.scss",
    "_md-comp-slider.scss",
)

# ── Dialog, scrim, focus ring ────────────────────────────────────────────────
_androidx("DialogTokens.kt", "ScrimTokens.kt")
_web_internal("dialog/internal/_dialog.scss", "focus/internal/_focus-ring.scss")
_web_current("_md-comp-focus-ring.scss")
_web_versioned("_md-comp-dialog.scss", "_md-comp-scrim.scss")

# ── Progress, tooltip, badge, divider, snackbar ──────────────────────────────
_androidx(
    "LinearProgressIndicatorTokens.kt",
    "CircularProgressIndicatorTokens.kt",
    "ProgressIndicatorTokens.kt",
    "PlainTooltipTokens.kt",
    "BadgeTokens.kt",
    "DividerTokens.kt",
    "SnackbarTokens.kt",
)
_web_internal("progress/internal/_linear-progress.scss", "divider/internal/_divider.scss")
_web_versioned(
    "_md-comp-linear-progress-indicator.scss",
    "_md-comp-circular-progress-indicator.scss",
    "_md-comp-plain-tooltip.scss",
    "_md-comp-badge.scss",
    "_md-comp-divider.scss",
    "_md-comp-snackbar.scss",
)

# ── Structure: bars, rails, search ───────────────────────────────────────────
_androidx(
    "AppBarTokens.kt",
    "AppBarSmallTokens.kt",
    "AppBarMediumTokens.kt",
    "NavigationBarTokens.kt",
    "NavigationBarHorizontalItemTokens.kt",
    "NavigationBarVerticalItemTokens.kt",
    "NavigationRailBaselineItemTokens.kt",
    "NavigationRailCollapsedTokens.kt",
    "NavigationRailColorTokens.kt",
    "SearchBarTokens.kt",
)
_web_versioned(
    "_md-comp-top-app-bar-small.scss",
    "_md-comp-top-app-bar-medium.scss",
    "_md-comp-navigation-bar.scss",
    "_md-comp-navigation-rail.scss",
    "_md-comp-search-bar.scss",
)

# ── The state layer both layers are painted with ─────────────────────────────
_web_internal("ripple/internal/_ripple.scss", "elevation/internal/_elevation.scss")

# ── The one implementation file that decides a disagreement ──────────────────
# The chip token files contradict each other: per-variant files publish
# `ContainerShape = CornerSmall`, while the M3E base `ChipsTokens` publishes
# `UnselectedShape = CornerMedium`. `Chip.kt` is what settles it, so it is
# vendored too: the expressive `defaultChipShapes` reads the base file, and the
# per-variant `ContainerShape` is only the outlined variant's own default.
_androidx_impl("Chip.kt")

# ── The system layers the component files reference by name ──────────────────
_androidx(
    "ColorSchemeKeyTokens.kt",
    "ShapeKeyTokens.kt",
    "ShapeTokens.kt",
    "ElevationTokens.kt",
    "StateTokens.kt",
    "TypeScaleTokens.kt",
    "TypefaceTokens.kt",
    "TypographyKeyTokens.kt",
    "MotionTokens.kt",
    "MotionSchemeKeyTokens.kt",
)


def fetch(url: str, attempts: int = 4) -> bytes | None:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "agenthandoff-m3spec/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except Exception as error:  # noqa: BLE001 — the message is what matters
            last = error
            time.sleep(1.5 * (attempt + 1))
    print(f"  FAILED  {url} — {last}")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--only",
        default=None,
        help="fetch just the entries whose local path contains this substring",
    )
    parser.add_argument(
        "--pins",
        action="store_true",
        help="rewrite PINS.tsv from what is on disk (the tests compare against it)",
    )
    args = parser.parse_args(argv)

    if args.pins:
        rows = []
        for path in sorted(SPEC.rglob("*")):
            if not path.is_file() or path.parent == SPEC or path.name == "PINS.tsv":
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append(f"{digest}\t{path.relative_to(SPEC).as_posix()}")
        pins = SPEC / "PINS.tsv"
        header = (
            "# sha256 of every vendored Google file under androidx/ and materialweb/.\n"
            "# Written by scripts/fetch_m3spec.py --pins; asserted by\n"
            "# tests/test_official_components.py.\n"
        )
        pins.write_text(
            header + "\n".join(rows) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"{len(rows)} files pinned into {pins}")
        return 0

    wanted = {
        local: urls
        for local, urls in MANIFEST.items()
        if args.only is None or args.only.lower() in local.lower()
    }
    if not wanted:
        print(f"nothing matches {args.only!r}; {len(MANIFEST)} entries in the manifest")
        return 1

    fetched = unchanged = failed = 0
    for local, (primary, mirror) in sorted(wanted.items()):
        target = SPEC / local
        data = fetch(primary)
        if data is None:
            data = fetch(mirror)
        if data is None:
            failed += 1
            continue
        digest = hashlib.sha256(data).hexdigest()
        old = target.read_bytes() if target.exists() else None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        state = "same" if old == data else ("updated" if old is not None else "new")
        fetched += 1
        unchanged += state == "same"
        print(f"{state:7} {len(data):>7}  {digest[:16]}  {local}")
    print(
        f"\n{len(wanted)} in the manifest, {fetched} on disk, "
        f"{unchanged} byte-identical, {failed} could not be fetched"
    )
    if failed:
        print("re-run to pick up the ones the network dropped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
