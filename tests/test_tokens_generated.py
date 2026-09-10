"""tokens.json is generated, not hand-edited — and now nothing in it is orphaned.

It used to be neither. `shape` and the four tonal containers lived only in the
committed JSON, so the regeneration command that `docs/theming.md` tells
contributors to run deleted them (shape silently, because theme.ts falls back to
hardcoded values; the CLI colours loudly, because a test catches those), and
`CLI_HUES` was stale by nine CLIs. These tests make that class of loss loud:

* the committed file must equal a fresh generator run, byte for byte;
* the pieces that used to be orphaned must survive and stay in sync;
* every CLI the parsers expose must have an identity.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOKENS = REPO / "web" / "src" / "tokens.json"

_spec = importlib.util.spec_from_file_location("gen_tokens", REPO / "scripts" / "gen_tokens.py")
assert _spec and _spec.loader
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def _committed() -> dict:
    return json.loads(TOKENS.read_text(encoding="utf-8"))


def test_committed_tokens_equal_a_fresh_build():
    fresh, problems = gen.build()
    assert problems == [], problems
    assert _committed() == fresh, "tokens.json drifted from scripts/gen_tokens.py — regenerate"


def test_the_generator_reproduces_the_file_byte_for_byte():
    """Key order included: `--check` compares text, so this is the real gate."""
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_tokens.py"), "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_tonal_containers_survive_regeneration(theme: str):
    """These were orphaned: present in the file, absent from the generator."""
    committed, fresh = _committed(), gen.build()[0]
    for key in ("accentContainer", "okContainer", "warnContainer", "errContainer"):
        assert fresh["themes"][theme][key] == committed["themes"][theme][key], key


def test_shape_scale_survives_regeneration():
    committed, fresh = _committed(), gen.build()[0]
    assert fresh["shape"] == committed["shape"]
    assert committed["shape"] == {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 28, "pill": 999}


def test_every_parser_cli_has_an_identity():
    ids = gen.cli_ids()
    assert set(_committed()["cli"]) == set(ids), "the identity list is not the parser registry"
    missing = [c for c in ids if c not in gen.CLI_HUES and c not in gen.CLI_PINNED]
    assert missing == [], f"no identity for {missing}: add a hue or pin the colour"


def test_motion_tokens_are_well_formed():
    motion = _committed()["motion"]
    assert motion["duration"]["short1"] == "50ms"
    assert motion["duration"]["medium2"] == "300ms"
    assert motion["duration"]["extra-long4"] == "1000ms"
    assert motion["easing"]["standard"] == "cubic-bezier(0.2, 0, 0, 1)"
    assert motion["easing"]["emphasized-accelerate"] == "cubic-bezier(0.3, 0, 0.8, 0.15)"
    assert all(v.endswith("ms") for v in motion["duration"].values())
    assert all(v.startswith("cubic-bezier(") for v in motion["easing"].values())
