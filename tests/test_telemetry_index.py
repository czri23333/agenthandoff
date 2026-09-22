"""Round 62: the ai-stats telemetry index, and what it must not do.

`telemetry_anchors` used to answer one session's question by reading every file in
`~/.qoder-cli/ai-stats/projects`: measured on this machine, 3,331 files and 74 MB per
detail page — 12 answered pages cost 39,972 reads and 1.1 GB. It now builds the
session→file index once and re-reads only when the tree's `(path, size, mtime)`
signature moves.

The tests below are mostly about the two ways that rewrite can be wrong without
showing: an index that answers one session from another's rows, and a cache that
keeps serving an answer the tree has outgrown. Equivalence with the old per-session
scan is asserted on the same fixture rather than left to a scratch measurement.
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter
from pathlib import Path

import pytest

from agent_handoff.parsers import jsonl_family as jf
from agent_handoff.parsers.jsonl_family import QoderIdeParser


@pytest.fixture(autouse=True)
def _no_index_carried_over():
    jf._TELE_INDEX.clear()
    yield
    jf._TELE_INDEX.clear()


def _row(file_path: str, *session_ids, lines: int = 1) -> str:
    return json.dumps(
        {
            "filePath": file_path,
            "lineDetails": [{"sessionId": s, "lines": lines} for s in session_ids],
        }
    )


def _tree(root: Path, files: dict[str, list[str]]) -> Path:
    """Write `projects/<name>/<commit>.jsonl` files; `files` maps a name to rows."""
    for name, rows in files.items():
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "c1.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return root


def _old_scan(session_id: str, base: Path) -> Counter[str]:
    """The per-session implementation Round 62 replaced, verbatim, as the oracle."""
    out: Counter[str] = Counter()
    for path in base.rglob("*.jsonl"):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            fp = row.get("filePath")
            if not isinstance(fp, str) or not fp.strip():
                continue
            for ld in row.get("lineDetails") or []:
                if isinstance(ld, dict) and ld.get("sessionId") == session_id:
                    out[fp] += 1
                    break
    return out


FIXTURE_FILES = {
    "projA": [
        _row("src/own.ts", "sid-1"),
        _row("src/shared.ts", "sid-1", "sid-2"),
        _row("src/duo.ts", "sid-1", "sid-3"),
        _row("src/twice.ts", "sid-2", "sid-2"),
        _row("src/nobody.ts"),
        _row("   ", "sid-1"),
        "{ not json",
        _row("src/other.ts", "sid-9"),
    ],
    "projB": [
        _row("src/shared.ts", "sid-2"),
        _row("src/b-only.ts", "sid-1"),
    ],
}


def _parser(tmp_path: Path) -> tuple[QoderIdeParser, Path]:
    base = _tree(tmp_path / "projects", FIXTURE_FILES)
    return QoderIdeParser(), base


def test_the_index_answers_exactly_what_the_per_session_scan_did(tmp_path):
    """Every session in the fixture, both ways, on real mixed rows."""
    p, base = _parser(tmp_path)
    for sid in ("sid-1", "sid-2", "sid-3", "sid-9", "sid-missing"):
        assert p.telemetry_anchors(sid, stats_dir=base) == _old_scan(sid, base), sid


def test_a_row_naming_two_sessions_counts_both(tmp_path):
    """The trap in generalising a per-session loop: the `break` was scoped to the
    session being asked, not to the row.

    `src/duo.ts` is named by no other row, so dropping either session from the
    answer shows up as a missing file rather than as a count that some other
    project happens to supply.
    """
    p, base = _parser(tmp_path)
    assert "src/duo.ts" in p.telemetry_anchors("sid-1", stats_dir=base)
    assert "src/duo.ts" in p.telemetry_anchors("sid-3", stats_dir=base)


def test_a_row_naming_the_same_session_twice_counts_once(tmp_path):
    p, base = _parser(tmp_path)
    assert p.telemetry_anchors("sid-2", stats_dir=base)["src/twice.ts"] == 1


def test_blank_and_unparsable_rows_are_not_files(tmp_path):
    p, base = _parser(tmp_path)
    got = p.telemetry_anchors("sid-1", stats_dir=base)
    assert "   " not in got and "src/nobody.ts" not in got
    assert got == {"src/own.ts": 1, "src/shared.ts": 1, "src/duo.ts": 1,
                "src/b-only.ts": 1}


def test_a_second_ask_over_the_same_tree_opens_nothing(tmp_path, monkeypatch):
    """The whole point: the reads happen once per tree change, not per page view."""
    p, base = _parser(tmp_path)
    opened: list[str] = []
    real = pathlib.Path.open

    def counting(self, *a, **k):
        opened.append(str(self))
        return real(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "open", counting)
    assert p.telemetry_anchors("sid-1", stats_dir=base)
    first = len(opened)
    assert p.telemetry_anchors("sid-2", stats_dir=base)
    assert len(opened) == first, f"the warm ask re-read {len(opened) - first} files"
    assert first == 2, f"the cold ask read {first} files, expected the tree's two"


def test_an_appended_row_is_not_an_answer_the_index_keeps_missing(tmp_path):
    """A JSONL log grows by append, which moves both size and mtime."""
    p, base = _parser(tmp_path)
    assert "src/later.ts" not in p.telemetry_anchors("sid-1", stats_dir=base)
    grown = base / "projA" / "c1.jsonl"
    with grown.open("a", encoding="utf-8") as fh:
        fh.write(_row("src/later.ts", "sid-1") + "\n")
    assert p.telemetry_anchors("sid-1", stats_dir=base)["src/later.ts"] == 1


def test_a_rewritten_file_is_noticed_by_its_bytes_not_its_name(tmp_path):
    """A rewrite that changes the size moves the signature.

    What is NOT detected is the case the signature cannot see: the same size and
    the same mtime with different bytes. That is accepted here and named in
    `limitations.md` — the store is an append-only JSONL log, so reaching that
    state would mean truncating a session's history into the same byte count,
    and detecting it would cost the read the index exists to avoid.
    """
    p, base = _parser(tmp_path)
    assert p.telemetry_anchors("sid-1", stats_dir=base)["src/own.ts"] == 1
    target = base / "projA" / "c1.jsonl"
    before = target.stat()
    rows = [
        ln for ln in target.read_text(encoding="utf-8").splitlines()
        if '"src/own.ts"' not in ln
    ]
    rows.append(_row("src/renamed.ts", "sid-1"))
    payload = ("\n".join(rows) + "\n").encode("utf-8")
    assert len(payload) != before.st_size, "the fixture no longer tests a size change"
    target.write_bytes(payload)
    got = p.telemetry_anchors("sid-1", stats_dir=base)
    assert "src/own.ts" not in got and got["src/renamed.ts"] == 1


def test_a_deleted_row_file_leaves_the_index(tmp_path):
    p, base = _parser(tmp_path)
    assert p.telemetry_anchors("sid-1", stats_dir=base)["src/b-only.ts"] == 1
    (base / "projB" / "c1.jsonl").unlink()
    assert "src/b-only.ts" not in p.telemetry_anchors("sid-1", stats_dir=base)


def test_two_stats_dirs_do_not_share_one_index(tmp_path):
    other = _tree(tmp_path / "other", {"projC": [_row("src/c.ts", "sid-1")]})
    p = QoderIdeParser()
    assert p.telemetry_anchors("sid-1", stats_dir=other) == Counter({"src/c.ts": 1})
    assert "src/c.ts" not in p.telemetry_anchors(
        "sid-1", stats_dir=_tree(tmp_path / "projects", FIXTURE_FILES)
    )


def test_the_answer_is_a_copy_the_caller_can_wreck_freely(tmp_path):
    """`load()` merges these counts into its own tally.

    Handing out the index's own Counter would let one page view edit the cache:
    the next ask would report a file the first one added to it, for a session that
    never touched it.
    """
    p, base = _parser(tmp_path)
    got = p.telemetry_anchors("sid-1", stats_dir=base)
    got["src/invented.ts"] += 5
    again = p.telemetry_anchors("sid-1", stats_dir=base)
    assert "src/invented.ts" not in again
    assert again == {"src/own.ts": 1, "src/shared.ts": 1, "src/duo.ts": 1,
                 "src/b-only.ts": 1}


def test_a_missing_store_dir_answers_empty_rather_than_crashing(tmp_path):
    assert QoderIdeParser().telemetry_anchors("sid-1", stats_dir=tmp_path / "nope") == {}
