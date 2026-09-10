"""The support matrix is generated, so its two hand-kept dicts need guards.

`matrix.py` keeps exactly two pieces of human input: which on-disk *kind* each store
is, and which CLIs are still roadmap. Both can rot silently — a missing
`STORE_KINDS` key renders "unknown" in the shipped table beside a reader we ship,
and a `ROADMAP` entry naming a registered CLI is dropped on the floor (the measured
registration wins), which is how `opencode` and `qoder-ide` were listed as "no
reader" long after both had readers.
"""

from __future__ import annotations

from agent_handoff.matrix import ROADMAP, STORE_KINDS, STORE_ZH, build_rows
from agent_handoff.parsers import all_parsers


def test_every_registered_parser_has_a_store_kind():
    registered = {parser.cli for parser in all_parsers()}
    missing = sorted(registered - set(STORE_KINDS))
    assert not missing, f"readers ship without a store kind: {missing}"


def test_no_roadmap_entry_names_a_registered_parser():
    registered = {parser.cli for parser in all_parsers()}
    overlap = sorted(set(ROADMAP) & registered)
    assert not overlap, (
        f"{overlap} is in ROADMAP *and* registered — the row would be dropped silently"
    )


def test_every_store_kind_has_a_chinese_label():
    """The zh table must not silently fall back to English mid-table."""
    translated = {STORE_ZH.get(kind) for kind in STORE_KINDS.values()}
    untranslated = sorted(
        {kind for kind in STORE_KINDS.values() if kind not in STORE_ZH}
    )
    assert not untranslated, f"no zh label for: {untranslated}"
    assert None not in translated


def test_no_row_reports_an_unknown_store():
    """The end-to-end statement: the generated table has no `unknown` cell."""
    unknown = [row.cli for row in build_rows() if row.store == "unknown"]
    assert not unknown, f"rows with an unknown store kind: {unknown}"
