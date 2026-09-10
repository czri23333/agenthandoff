"""Legibility contract for the cockpit: every colour pair must pass WCAG AA.

This test exists because the shipped cockpit did not: `CliBadge` mapped zcode and
qodercn-ide to antd preset colour names that do not exist in v6 ("sky", "amber"),
antd fell back to a light-grey chip, and the agent identity rendered as white
text on a near-white chip — 1.1:1, effectively invisible. No amount of
eyeballing catches that; a gate on the token table does.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent_handoff.parsers import all_parsers

WEB = Path(__file__).resolve().parent.parent / "web"
TOKENS = json.loads((WEB / "src" / "tokens.json").read_text(encoding="utf-8"))

TEXT_PAIR_MIN = 4.5
GRAPHIC_MIN = 3.0
MIN_FONT_PX = 12.0

_COMMENT_PREFIXES = ("*", "//", "/*", "<!--")


def _rgb(color: str) -> tuple[float, float, float]:
    h = color.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def _lum(color: str) -> float:
    def chan(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(c) for c in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _is_comment(line: str) -> bool:
    return line.strip().startswith(_COMMENT_PREFIXES)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_text_tiers_pass_aa_on_every_surface(theme: str) -> None:
    p = TOKENS["themes"][theme]
    for tier in ("text1", "text2", "text3"):
        for surface in ("surface0", "surface1", "surface2"):
            r = ratio(p[tier], p[surface])
            assert r >= TEXT_PAIR_MIN, f"{theme}: {tier} on {surface} is {r:.2f}:1"


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_semantic_colors_pass_aa(theme: str) -> None:
    """Accent/ok/warn/err carry meaning, so they cannot be decoration."""
    p = TOKENS["themes"][theme]
    for key in ("accent", "ok", "warn", "err", "placeholder"):
        r = ratio(p[key], p["surface1"])
        assert r >= TEXT_PAIR_MIN, f"{theme}: {key} on surface1 is {r:.2f}:1"


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_cli_identity_chips_are_readable(theme: str) -> None:
    """The exact regression: agent badges measured 1.1:1 before the token table."""
    theme_tokens = TOKENS["themes"][theme]
    for cli, ink in theme_tokens["cli"].items():
        fg_bg = ratio(ink["fg"], ink["bg"])
        assert fg_bg >= TEXT_PAIR_MIN, f"{theme}/{cli}: chip text is {fg_bg:.2f}:1"
        border = ratio(ink["border"], theme_tokens["surface1"])
        assert border >= 1.15, f"{theme}/{cli}: chip border invisible ({border:.2f}:1)"


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_tonal_containers_carry_text_at_aa(theme: str) -> None:
    """M3E tonal containers are backgrounds for real text — bubbles, chips,
    banners — and nothing checked them: the gate only knew about surface0/1/2.
    A container that drifts too close to the text colour is unreadable text."""
    p = TOKENS["themes"][theme]
    for key in ("accentContainer", "okContainer", "warnContainer", "errContainer"):
        r = ratio(p["text1"], p[key])
        assert r >= TEXT_PAIR_MIN, f"{theme}: text1 on {key} is {r:.2f}:1"


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_every_supported_cli_has_an_identity(theme: str) -> None:
    """Add a parser without adding a colour, and this test tells you."""
    declared = set(TOKENS["themes"][theme]["cli"])
    shipped = {parser.cli for parser in all_parsers()}
    missing = shipped - declared - {"default"}
    assert not missing, f"CLIs without a token identity: {sorted(missing)}"


def test_borders_are_visible_but_quiet() -> None:
    for theme in ("dark", "light"):
        p = TOKENS["themes"][theme]
        assert ratio(p["line"], p["surface1"]) >= 1.15, f"{theme}: divider invisible"
        assert ratio(p["lineStrong"], p["surface1"]) >= 1.6, f"{theme}: focus/hover edge invisible"


def test_no_component_hardcodes_a_colour() -> None:
    """The palette lives in tokens.json; components consume it through theme.ts.

    Guards the class of bug where a component picks a colour name that its
    component library does not recognise and silently renders unreadable text.
    """
    offenders: list[str] = []
    for path in sorted((WEB / "src").rglob("*")):
        if path.suffix not in {".tsx", ".ts", ".css"}:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _is_comment(line):
                continue
            if "PRIMARY =" in line:
                continue  # the one deliberate shared accent, mirrored into antd tokens
            for pattern in (
                r"#[0-9a-fA-F]{6}\b",
                r"\b(?:bg|text|border)-(?:zinc|neutral|gray|slate|stone|sky|amber)-\d{2,3}",
                r'color="(?:sky|amber|volcano)"',  # presets that do not exist in antd v6
            ):
                if re.search(pattern, line):
                    offenders.append(f"{path.name}:{lineno}: {line.strip()[:60]}")
    assert not offenders, "colours outside the token table:\n  " + "\n  ".join(offenders[:10])


def test_font_floor_is_enforced_across_the_frontend() -> None:
    """CJK below ~12px is unreadable, and the rule has to hold where text is set.

    This used to scan `index.css` for `font-size: Npx` only. Two ways that fails:
    after the M3 typescale migration there are no literal pixel sizes left in the
    CSS at all (so an assertion over an empty set passes vacuously), and the
    JSX — where eleven files set `text-[11px]` — was never looked at. The floor
    now covers both, and it is enforced together with the scale: 11px is Google's
    `label-small`, which is legitimate for latin identifiers and monospace, so it
    is allowed only where the same element also sets a mono family.
    """
    css = (WEB / "src" / "index.css").read_text(encoding="utf-8")
    offenders: list[str] = []

    for value in re.findall(r"font-size:\s*(\d+(?:\.\d+)?)px", css):
        if float(value) < MIN_FONT_PX:
            offenders.append(f"index.css: literal {value}px is under the {MIN_FONT_PX}px floor")

    # The justification is read from the *class attribute*, not from the line: a
    # review showed a same-line check waves through a `text-[11px]` whose
    # `font-mono` sits on the next line of a wrapped attribute.
    for path in sorted((WEB / "src").rglob("*.tsx")):
        text = path.read_text(encoding="utf-8")
        for quoted, template in re.findall(r"className=(?:\"([^\"]*)\"|\{`([^`]*)`\})", text):
            classes = quoted or template
            sizes = [float(s) for s in re.findall(r"text-\[(\d+(?:\.\d+)?)px\]", classes)]
            if sizes and min(sizes) < MIN_FONT_PX and "font-mono" not in classes:
                offenders.append(
                    f"{path.name}: {classes.strip()[:60]}… sets {min(sizes)}px without font-mono"
                )

    assert not offenders, "text under the CJK floor:\n  " + "\n  ".join(offenders[:10])


def test_theme_tokens_drive_antd() -> None:
    """theme.ts must map every palette surface/text tier into antd, or antd
    components will render with library defaults on our themed pages."""
    text = (WEB / "src" / "theme.ts").read_text(encoding="utf-8")
    required = (
        "colorText:",
        "colorTextSecondary:",
        "colorBgContainer:",
        "colorTextPlaceholder:",
    )
    for token in required:
        assert token in text, f"antd bridge missing {token}"


def test_token_contract_documents_itself() -> None:
    """The file must state its own contract, or the next contributor edits blindly."""
    assert "WCAG" in TOKENS["_readme"]
    assert TOKENS["contrast"]["text"] == TEXT_PAIR_MIN
    assert set(TOKENS["themes"]) == {"dark", "light"}
