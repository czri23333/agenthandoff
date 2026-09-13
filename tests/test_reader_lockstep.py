"""Adding a reader means touching six places, and missing one is a red check.

§6 of the brief names the lockstep: `parsers/__init__.py` (two registration
functions), `matrix.STORE_KINDS`, the `locations.py` doctor probe, a fixture plus
`scripts/sanitize_fixtures.py`, and the token generator (the CLI identity
colour) — after which `conformance --write` and `evidence --write` have to run.

Those steps were a checklist in a document, which means they were enforced by
whoever remembered them. They are asserted here instead, so the sixth one is a
failing test rather than a drifted table. This file is *expected to fail* when a
reader is added carelessly — that is its job — and it failed on the state it was
written against, which is how the three missing doctor probes below were found.

What each check is for:

* **one registry.** `available_parsers()` and `all_parsers()` each spelled the
  same twenty constructors out by hand. Two lists that must agree and are not
  derived from each other are a drift waiting to happen, so they now share one
  `PARSER_CLASSES` tuple and the gate asserts it.
* **store kind.** `matrix.py` reads `STORE_KINDS.get(cli, "unknown")`, so a
  reader missing from that table renders as "unknown" in the support matrix —
  visible, but only if someone reads the table.
* **doctor probe.** `handoff doctor` is the one command the limitations doc tells
  a user to run to find out whether a store is real on *their* machine. A reader
  with no probe is a reader the doctor cannot report, which is the difference
  between "unverified" and "invisible".
* **matrix row.** `config/support-matrix.json` is what the README tables are
  generated from; a reader with no row cannot be described to a user at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent_handoff import matrix
from agent_handoff.parsers import PARSER_CLASSES, all_parsers, available_parsers

REPO = Path(__file__).resolve().parent.parent
LOCATIONS = (REPO / "src" / "agent_handoff" / "locations.py").read_text(encoding="utf-8")
MATRIX_JSON = json.loads((REPO / "config" / "support-matrix.json").read_text(encoding="utf-8"))

READERS = sorted({parser.cli for parser in all_parsers()})


def _probed_clis() -> set[str]:
    """Every cli `locations.discover()` can report, read out of its source.

    Static on purpose: the doctor's answer depends on the machine, and this gate
    has to hold on a machine where nothing is installed.
    """
    probes = re.search(r"probes = \[(.*?)\]", LOCATIONS, re.S)
    assert probes, "locations.discover() no longer builds a `probes` list"
    names = re.findall(r"(\w+),", probes.group(1))
    assert len(names) >= 10, f"only {len(names)} probes parsed out of the list"

    # Each probe names its cli either as its first argument
    # (`_projects_store("claude", ".claude")`) or only through the path it looks
    # in (`home() / ".zcode" / "cli" / "db" / "db.sqlite"`). Collect every quoted
    # string in the body and match the cli against those, so both spellings work
    # without the gate having to understand the code.
    bodies: list[str] = []
    for name in names:
        match = re.search(rf"\ndef {name}\(\)[^:]*:\n(.*?)(?=\n\ndef |\n\n#)", LOCATIONS, re.S)
        assert match, f"locations.{name} has no body this gate can read"
        bodies.append(match.group(1))
    haystack = "\n".join(" ".join(re.findall(r'"([^"]*)"', body)) for body in bodies)

    found: set[str] = set()
    for cli in READERS:
        if re.search(rf"(?<![\w-]){re.escape(cli)}(?![\w-])", haystack):
            found.add(cli)
    return found


def test_the_registry_is_one_list():
    """The two public constructors must be views of one registry."""
    assert {type(p) for p in all_parsers()} == set(PARSER_CLASSES)
    assert [type(p) for p in all_parsers()] == list(PARSER_CLASSES)
    # `available_parsers` is the same registry filtered by what exists here.
    assert {type(p) for p in available_parsers()} <= set(PARSER_CLASSES)
    assert len(PARSER_CLASSES) == len(set(PARSER_CLASSES)), "a parser is registered twice"


def test_no_two_readers_claim_the_same_cli():
    """Two classes with one `cli` would make `resolve_session` order-dependent."""
    clis = [cls.cli for cls in PARSER_CLASSES]
    assert len(clis) == len(set(clis)), sorted({c for c in clis if clis.count(c) > 1})


@pytest.mark.parametrize("cli", READERS)
def test_every_reader_has_a_store_kind(cli: str):
    """`matrix.py` renders a missing kind as "unknown" in the support table."""
    assert cli in matrix.STORE_KINDS or cli in matrix.ROADMAP, (
        f"{cli} has no STORE_KINDS entry, so the support matrix calls its storage "
        '"unknown"'
    )


@pytest.mark.parametrize("cli", READERS)
def test_every_reader_has_a_matrix_row(cli: str):
    rows = {row["cli"] for row in MATRIX_JSON["rows"]}
    assert cli in rows, f"{cli} is a reader with no row in config/support-matrix.json"


@pytest.mark.parametrize("cli", READERS)
def test_every_reachable_reader_has_a_doctor_probe(cli: str):
    """A roadmap reader has no store *by definition*; anything else needs a probe.

    `ROADMAP` is the documented list of formats with nothing on disk to read
    (`opencode` storage is undocumented, Qoder IDE keeps its sessions in an
    Electron leveldb), so those are exempt and everything else is not.
    """
    if cli in matrix.ROADMAP:
        pytest.skip(f"{cli} is roadmap: {matrix.ROADMAP[cli]}")
    assert cli in _probed_clis(), (
        f"handoff doctor cannot report {cli}: add a probe to locations.discover()"
    )


def test_every_unproven_reader_says_what_would_prove_it():
    """`unverified` on its own is a dead end for whoever picks the work up.

    The row has to name why the reader is unproven *here* and the command that
    would close it, because "no fixture" is a fact about the machine that built
    the fixtures rather than about the reader. `matrix.UNPROVEN` also has to stay
    free of entries for readers that have since been proven 鈥?a reason that
    outlives its gap is the same defect in the other direction.
    """

    rows = matrix.build_rows()
    unproven = [row for row in rows if row.status == "unverified"]
    # No `assert unproven`: all readers proven is the *good* outcome, and a gate
    # that fails on it would punish the work it is asking for.
    unexplained = [row.cli for row in unproven if not row.notes]
    assert not unexplained, (
        f"{unexplained} are unverified with no reason: add them to matrix.UNPROVEN "
        "with what would prove them"
    )
    for row in unproven:
        text = " ".join(row.notes)
        assert "scripts/sanitize_fixtures.py" in text, (
            f"{row.cli}'s reason does not name the command that would prove it: {text}"
        )

    proven = {row.cli for row in rows if row.status in {"stable", "shape-only"}}
    stale = sorted(proven & set(matrix.UNPROVEN))
    assert not stale, (
        f"{stale} have fixtures now, so their UNPROVEN reason is stale: delete it"
    )
