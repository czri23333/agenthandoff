"""The cockpit's type must sit on Google's M3 scale, and that has to be enforceable.

`tests/test_tokens_m3official.py` proves the *token file* carries Google's numbers.
This file proves the *frontend* spends them: every font size in the CSS and the
JSX resolves to an official role, every weight is one M3 actually uses (400 or
500 — there is no 600), and every role name referenced from CSS exists in
tokens.json, so a rename cannot leave a silently-invalid declaration behind.

The rule is deliberately narrow: it does not police typography taste, only the
scale. Sizes come from material-web `tokens/versions/v0_192/_md-sys-typescale.scss`
(size in rem × 16): 11 (label-small), 12 (body-small, label-medium), 14
(body-medium, label-large, title-small), 16 (title-medium), 22 (title-large).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web" / "src"
TOKENS = json.loads((WEB / "tokens.json").read_text(encoding="utf-8"))

OFFICIAL_SIZES = {11, 12, 14, 16, 22, 24}
M3_WEIGHTS = {400, 500}
# Relative sizes are fine: they inherit a role's size and scale with it.
RELATIVE_SIZE = re.compile(r"font-size:\s*(?:[\d.]+em|[\d.]+rem|inherit)\b")

# The stylesheet is split in two, and both halves are type-bearing: `index.css`
# carries the cockpit's own surfaces, `m3.css` the M3 component anatomy. An
# earlier version of this file read only `index.css`, which is exactly the
# blind spot the m3components slice would have walked into.
STYLESHEETS = ("index.css", "m3.css")


def css() -> str:
    return "\n".join((WEB / name).read_text(encoding="utf-8") for name in STYLESHEETS)


def css_with_line_numbers() -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for name in STYLESHEETS:
        for lineno, line in enumerate((WEB / name).read_text(encoding="utf-8").splitlines(), 1):
            out.append((name, lineno, line))
    return out


def _kebab(key: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", key).lower()


def component_type_vars() -> dict[str, str]:
    """`--ah-c-<path>-size` (and -line/-tracking/-weight) → the type role it names.

    The component layer does not repeat a type role's numbers any more than it
    repeats a colour: it *references* one, and `theme.ts` expands that reference
    into four custom properties. This map is the reverse of that expansion, so a
    component pointing at a role that does not exist fails here rather than
    rendering at the browser's default size.
    """
    out: dict[str, str] = {}

    def walk(node: object, path: list[str]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).startswith("_"):
                    continue
                walk(value, [*path, str(key)])
            return
        if not isinstance(node, str) or not node.startswith("type:"):
            return
        name = "--ah-c-" + "-".join(_kebab(part) for part in path)
        for suffix in ("size", "line", "tracking", "weight"):
            out[f"{name}-{suffix}"] = node[len("type:") :]

    walk(TOKENS["component"], [])
    return out


def test_no_literal_pixel_size_survives_in_the_stylesheet():
    """Every size must come from a role token — that is what makes it reviewable."""
    offenders = [
        value
        for value in re.findall(r"font-size:\s*(\d+(?:\.\d+)?)px", css())
        if float(value) not in OFFICIAL_SIZES
    ]
    assert not offenders, f"off-scale literal sizes in index.css: {offenders}"


def test_every_font_size_is_either_a_role_token_or_relative():
    for name, lineno, line in css_with_line_numbers():
        if "font-size:" not in line:
            continue
        stripped = line.strip()
        ok = (
            "var(--ah-type-" in stripped
            # A component reads its role through its own token, which the
            # generator resolved to one of the four `--ah-type-*` properties.
            or "var(--ah-c-" in stripped
            or "font-size: inherit" in stripped
            or RELATIVE_SIZE.search(stripped) is not None
        )
        assert ok, f"{name}:{lineno}: size is neither a role nor relative: {stripped}"


def test_every_role_referenced_from_css_exists_in_the_token_file():
    roles = set(TOKENS["typescale"]["roles"])
    referenced = set(re.findall(r"var\(--ah-type-([a-z-]+)-(?:size|line|tracking|weight)\)", css()))
    unknown = {role for role in referenced if role not in roles and role != "cjk-floor"}
    assert not unknown, f"CSS references type roles that do not exist: {sorted(unknown)}"

    # The component layer's own type references, resolved the same way.
    by_var = component_type_vars()
    component_roles = {
        by_var[var]
        for var in re.findall(r"var\((--ah-c-[A-Za-z0-9-]+)\)", css())
        if var in by_var
    }
    assert component_roles, "no component in m3.css references a type role"
    assert component_roles <= roles, (
        f"m3.css reads component type roles that do not exist: {sorted(component_roles - roles)}"
    )

    # The mirror: a role nobody spends is either new or a leftover. `label-small`
    # is 11px and therefore mono-only by construction — it is spent in the JSX,
    # beside the mono family, not from the stylesheet, so it counts as used when
    # at least one 11px mono site exists.
    jsx_11px = any(
        re.search(r"text-\[11px\]", path.read_text(encoding="utf-8"))
        for path in WEB.rglob("*.tsx")
    )
    spent = referenced | component_roles | ({"label-small"} if jsx_11px else set())
    unspent = roles - spent
    assert not unspent, f"type roles defined but never spent: {sorted(unspent)}"


def test_letter_spacing_comes_from_a_role_or_is_explicitly_off():
    """`letter-spacing: 0` is a documented opt-out; anything else must be a role."""
    for name, lineno, line in css_with_line_numbers():
        if "letter-spacing:" not in line:
            continue
        value = line.split("letter-spacing:", 1)[1].strip().rstrip(";")
        from_role = value.startswith("var(--ah-type-") or value.startswith("var(--ah-c-")
        assert from_role or value in {"0", "normal"}, (
            f"{name}:{lineno}: tracking must come from a role or be explicitly off: {value}"
        )


def test_jsx_uses_only_official_sizes():
    offenders: list[str] = []
    for path in sorted(WEB.rglob("*.tsx")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in re.finditer(r"text-\[(\d+(?:\.\d+)?)px\]", line):
                if float(match.group(1)) not in OFFICIAL_SIZES:
                    offenders.append(f"{path.name}:{lineno}: {match.group(0)}")
    assert not offenders, "off-scale sizes in JSX:\n  " + "\n  ".join(offenders[:10])


def test_no_weight_heavier_than_m3s_medium():
    """M3 publishes regular (400) and medium (500) — nothing else.

    Checked as a *closed set* on the declaration's value rather than as a numeric
    range: an independent review showed the earlier `font-weight:\\s*(\\d+)` pattern
    let the CSS keyword `bold` through, which is the same off-scale weight spelled
    a different way.
    """
    offenders: list[str] = []
    for path in [*[WEB / name for name in STYLESHEETS], *sorted(WEB.rglob("*.tsx"))]:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in re.finditer(r"font-weight:\s*([^;}\n]+)", line):
                value = match.group(1).strip()
                # A weight may be the number M3 publishes or a reference to a
                # role that carries one; the component layer's own
                # `--ah-c-<path>-weight` expands to `--ah-type-<role>-weight`.
                named = re.fullmatch(
                    r"var\(--ah-(?:type-[a-z-]+-weight|c-[A-Za-z0-9-]+-weight)\)", value
                )
                if value not in {"400", "500"} and not named:
                    offenders.append(f"{path.name}:{lineno}: font-weight {value}")
            for match in re.finditer(r"font-(?:semibold|bold|extrabold|black)\b", line):
                offenders.append(f"{path.name}:{lineno}: utility {match.group(0)}")
    assert not offenders, "weights M3 does not define:\n  " + "\n  ".join(offenders[:10])


def test_jsx_has_no_inline_font_size():
    """An inline `fontSize` bypasses the role exactly as an inline tracking would."""
    offenders = [
        f"{path.name}:{lineno}"
        for path in sorted(WEB.rglob("*.tsx"))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"fontSize", line)
    ]
    assert not offenders, f"inline font-size bypasses the role: {offenders}"


def test_jsx_has_no_hand_written_letter_spacing():
    """Tracking belongs to the role: an inline `letterSpacing` overrides it silently."""
    offenders = [
        f"{path.name}:{lineno}"
        for path in sorted(WEB.rglob("*.tsx"))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"letterSpacing", line)
    ]
    assert not offenders, f"inline letter-spacing bypasses the role: {offenders}"
