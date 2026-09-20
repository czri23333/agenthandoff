"""What the doctor probe says a store holds.

`discover()` is the one surface that answers "what is real on YOUR machine", so
two of its failures are bugs here rather than display choices: a reader with no
probe at all (which is how `qoder-ide` - 2,259 of the 3,322 sessions on the
maintainer's machine - went unreported), and a file count that leaves the reader
wondering where the rest of a store's transcripts went.

The stores here are built under `AGENTHANDOFF_HOME`, so no test reads a real one.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agent_handoff import locations

SID = "3ab39e22-5d8e-4a64-a971-e7e359c58c45"
SID2 = "44bcc164-4d8f-4608-96fc-470677406307"


@pytest.fixture
def home_(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTHANDOFF_HOME", str(tmp_path))
    return tmp_path


def _write(p: Path, text: str = "{}") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _cwd(root: Path, dirname: str = ".probe") -> Path:
    d = root / dirname / "projects" / "D--demo"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_a_state_dir_with_no_transcript_is_counted_not_silently_absent(home_):
    """19 such dirs sit in the real ~/.qoder store; none of them was visible."""
    cwd = _cwd(home_)
    _write(cwd / f"{SID}.jsonl", '{"role":"user"}\n')
    _write(cwd / f"{SID}.state", "")
    _write(cwd / SID / "state.json")
    # A second session that left only its sidecar behind.
    _write(cwd / SID2 / "state.json")
    detail = locations._projects_store("probe", ".probe").detail
    assert detail.startswith("1 session file(s)")
    assert "1 dir(s) with session state and no transcript" in detail, detail


def test_a_transcript_beside_the_state_dir_is_not_counted(home_):
    """The normal case: <uuid>.jsonl sits next to the <uuid>/ directory."""
    cwd = _cwd(home_)
    _write(cwd / f"{SID}.jsonl", '{"role":"user"}\n')
    _write(cwd / SID / "state.json")
    _write(cwd / SID / "subagents" / "agent-a1.jsonl", '{"role":"user"}\n')
    detail = locations._projects_store("probe", ".probe").detail
    assert "no transcript" not in detail, detail
    assert "1 transcript(s) under subagents/" in detail, detail


def test_a_state_file_that_is_not_a_session_dir_is_ignored(home_):
    """`jobs/<shortid>/state.json` has no transcript by design, so counting it
    would report a gap that is not one."""
    cwd = _cwd(home_)
    _write(cwd / f"{SID}.jsonl", '{"role":"user"}\n')
    _write(cwd.parent / "jobs" / "a1b2c3" / "state.json")
    _write(cwd.parent / "state.json")
    detail = locations._projects_store("probe", ".probe").detail
    assert "no transcript" not in detail, detail


def test_qoder_ide_has_a_probe_of_its_own(home_):
    """It had a parser and a 2,259-session store and no probe, so `doctor` was
    silent about the largest thing on this machine."""
    cwd = _cwd(home_, ".qoder")
    _write(cwd / f"{SID}.jsonl", '{"role":"user"}\n')
    info = locations.qoder_ide_store()
    assert info is not None
    assert info.cli == "qoder-ide"
    assert info.readable is True
    assert info.detail.startswith("1 session file(s)")


def test_opencode_has_a_probe_of_its_own(home_):
    db = home_ / ".local" / "share" / "opencode" / "opencode.db"
    assert locations.opencode_store() is None
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE session (id TEXT)")
    con.commit()
    con.close()
    info = locations.opencode_store()
    assert info is not None
    assert info.cli == "opencode"
    assert info.readable is True


def test_the_sqlite_probe_hands_its_parser_a_root_that_resolves(home_):
    """`_doctor_rows` feeds `StoreInfo.path` to `with_root`, so a probe that
    reports a path its own parser cannot use makes the doctor say `parses yes
    (0)` about a store that lists 222 sessions - which is exactly what this
    probe did on its first run."""
    from agent_handoff.parsers.opencode import OpenCodeParser

    db = _write(home_ / ".local" / "share" / "opencode" / "opencode.db", "")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE session (id TEXT)")
    con.commit()
    con.close()
    info = locations.opencode_store()
    assert OpenCodeParser().with_root(Path(info.path))._db() == db


def test_the_wake_probe_says_who_lists_the_shared_transcripts(home_):
    cwd = _cwd(home_, ".qoder")
    _write(cwd / f"{SID}.jsonl", '{"role":"user"}\n')
    detail = locations.qoderwake_store().detail
    assert "shared store .qoder: 1 transcript file(s)" in detail
    assert "listed as qoder-ide" in detail, detail
