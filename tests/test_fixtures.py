"""The fixture-backed evidence layer: parseability, privacy, and drift.

These tests are what make the README's check marks reproducible: clone, install,
and either they pass on your machine too, or the claim was never true. They also
guard the guards - a leak scan that matches nothing and a fingerprint that only
ever says "ok" would be worse than no claim at all, because they look like proof.

The fixtures under `tests/fixtures/sanitized/` are sanitized samples of real
vendor stores (built by `scripts/sanitize_fixtures.py`), so the layout, key names,
record types and enum vocabulary are the vendors', not invented by us.
"""

from __future__ import annotations

import pytest

from agent_handoff import conformance, evidence, fixtures, privacy
from agent_handoff import matrix as ah_matrix
from agent_handoff.parsers import all_parsers

PRESENT = fixtures.available()


def _parser(cli: str):
    return next(p for p in all_parsers() if p.cli == cli)


def test_fixtures_are_shipped():
    """At least one fixture, or someone removed the evidence layer."""
    assert PRESENT, f"no fixtures under {fixtures.FIXTURE_ROOT}"


@pytest.mark.parametrize("cli", PRESENT)
def test_fixture_parses_without_losing_content(cli: str):
    measured = fixtures.measure(_parser(cli))
    if measured.codec_missing:
        pytest.skip(f"{cli}: needs the optional codec (`pip install '.[zstd]'`)")
    assert measured.error == "", measured.error
    assert measured.sessions > 0, f"{cli}: fixture lists no sessions"
    if measured.source_messages:
        assert measured.nonempty > 0, (
            f"{cli}: the source sessions held {measured.source_messages} "
            "messages and the fixture yields none - content was lost in the build"
        )


@pytest.mark.parametrize("cli", PRESENT)
def test_fixture_is_safe_to_publish(cli: str):
    """Machine-independent privacy invariants on every byte of the fixture."""
    problems = privacy.scan_tree(fixtures.cli_dir(cli))
    assert not problems, "\n".join(problems[:12])


def test_privacy_scan_catches_what_it_claims_to():
    """A gate that matches nothing is not a gate."""
    dirty = [
        r"C:\Users\alice\Documents\project\main.py",
        "D--Users-bob-Desktop-note.txt",
        "/home/carol/.config/app/state.json",
        "contact me at alice@example.org",
        "sk-" + "A" * 24,
    ]
    for sample in dirty:
        assert privacy.scan_text(sample), f"not flagged: {sample}"


def test_privacy_scan_leaves_our_synthetic_paths_alone():
    """The false-positive class that once reported ~100 fake leaks: `e:\\n`."""
    clean = [
        r"C:\work\qiriv\foo.jsonl",
        "/srv/vumabi/bar.md",
        '{"text": "note:\\nsee the grep output:\\n128:\\n"}',
        "person123@example.test",
        "REDACTED-0123456789ab",
        "the user asked about home cooking and var icons",
    ]
    for sample in clean:
        assert not privacy.scan_text(sample), f"false positive: {sample}"


@pytest.mark.parametrize("cli", PRESENT)
def test_conformance_baseline_matches_fixture(cli: str):
    """Format drift in the fixture, or a regression in our parser, fails here."""
    verdict = conformance.check([cli])[cli]
    assert verdict["status"] != "no-baseline", f"{cli}: run `--write` and commit it"
    differences = verdict["diff"]
    detail = "\n".join(
        f"    {kind}: {item}" for kind in ("lost", "added", "changed") for item in differences[kind]
    )
    assert verdict["status"] in ("ok", "codec-skipped"), f"{cli}:\n{detail}"


def test_matrix_status_is_derived_from_evidence():
    """No row may claim more than its fixture proves, and the two cannot diverge."""
    rows = {row.cli: row for row in ah_matrix.build_rows()}
    for cli in PRESENT:
        measured = fixtures.measure(_parser(cli))
        row = rows[cli]
        # Re-derive rather than trust the field: a hand-set status would not
        # survive this comparison.
        assert row.fixture_ok == measured.proven or row.codec_missing
        assert row.status == ah_matrix.derive_status(row), f"{cli}: {row.status}"
    for row in rows.values():
        if row.status == "stable":
            assert row.fixture_ok, f"{row.cli} claims stable without a parsing fixture"
        if row.status == "unverified":
            assert not row.fixtures, f"{row.cli}: unverified despite having fixtures"


def test_readme_and_matrix_json_are_current():
    """The published claim must equal the measurement; staleness fails CI."""
    problems = evidence.stale_targets()
    assert not problems, "stale artifacts:\n  " + "\n  ".join(problems)


def test_measure_ignores_listing_order(monkeypatch):
    """The measured subset must be chosen by session id, not by enumeration order.

    A fresh checkout stamps every fixture file with the same mtime, so a
    parser's "newest first" listing is a full tie and falls back to filesystem
    enumeration order - which differs between APFS, NTFS and ext4. That made the
    committed evidence (matrix rows, conformance fingerprints) machine-dependent
    and intermittently red on one CI leg only.
    """
    parser = _parser("codex")
    baseline = fixtures.measure(parser)
    original = type(parser).list_sessions
    monkeypatch.setattr(
        type(parser), "list_sessions", lambda self: list(reversed(original(self)))
    )
    assert fixtures.measure(parser) == baseline


def test_every_unproven_reader_is_visible():
    """A reader with no fixture is listed as a gap, never silently ✅."""
    gaps = set(ah_matrix.unproven())
    for parser in all_parsers():
        if parser.cli not in PRESENT:
            assert parser.cli in gaps, f"{parser.cli} has no fixture and is not flagged"


def test_matrix_ignores_live_stores(monkeypatch, tmp_path):
    """Committed evidence must say the same thing on every machine.

    Regression: build_rows() used to probe live stores for fixture-less
    CLIs, so the committed matrix matched no single machine (empty-store
    verdicts from one author machine leaked into artifacts that failed on
    store-less CI runners and vice versa).
    """
    import os

    def snapshot() -> list[tuple]:
        return sorted(
            (r.cli, r.status, r.empty_store, tuple(r.notes)) for r in ah_matrix.build_rows()
        )

    live = snapshot()
    empty = tmp_path / "no-stores-here"
    empty.mkdir()
    monkeypatch.setenv("AGENTHANDOFF_HOME", str(empty))
    monkeypatch.setenv("APPDATA", str(empty))
    if "HOME" in os.environ:
        monkeypatch.setenv("HOME", str(empty))
    assert snapshot() == live


def test_live_overlay_stays_out_of_committed_rows():
    """The verified-empty verdict exists, but only the live command may add it."""
    rows = ah_matrix.build_rows()
    assert all(not r.empty_store for r in rows)
    overlaid = ah_matrix.with_live_overlay([r for r in rows])
    assert all(r.status == ah_matrix.derive_status(r) for r in overlaid)
