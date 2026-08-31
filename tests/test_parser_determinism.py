"""A listing must not depend on when the files were copied.

Regression: `updated_at` was taken from `stat().st_mtime`, so a fresh clone - where
every fixture's mtime is the checkout instant - ordered sessions differently and
measured different top-six sessions than the machine that produced the fixtures.
The published evidence therefore disagreed with `pytest` on a clean checkout, and
any restored or WSL-mounted store showed every session as "just now".
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from agent_handoff.parsers.jsonl_family import CodebuddyParser


def _session(root: Path, sid: str, last_at: int) -> Path:
    project = root / "projects" / "C--demo"
    project.mkdir(parents=True, exist_ok=True)
    path = project / f"{sid}.jsonl"
    rows = [
        {"type": "user", "sessionId": sid, "cwd": "C:/demo", "timestamp": last_at - 5000,
         "message": {"role": "user", "content": [{"type": "text", "text": f"ask {sid}"}]}},
        {"type": "assistant", "sessionId": sid, "timestamp": last_at,
         "message": {"role": "assistant", "content": [{"type": "text", "text": f"answer {sid}"}]}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _parser(tmp_path):
    root = tmp_path / ".codebuddy"
    for index, sid in enumerate(["s1", "s2", "s3"]):
        _session(root, sid, 1_780_000_000_000 + index * 1_000)
    return CodebuddyParser(root / "projects")


def test_ordering_ignores_filesystem_mtime(tmp_path):
    parser = _parser(tmp_path)
    files = sorted((tmp_path / ".codebuddy" / "projects" / "C--demo").glob("*.jsonl"))
    before = [(m.session_id, m.updated_at) for m in parser.list_sessions()]
    assert len(before) == 3

    # Reverse the mtimes: newest content first on disk, oldest on the clock.
    for rank, path in enumerate(reversed(files)):
        stamp = 1_700_000_000 + rank * 60
        os.utime(path, (stamp, stamp))
    after = [(m.session_id, m.updated_at) for m in parser.list_sessions()]
    assert after == before, "list order followed mtime instead of the records"


def test_updated_at_is_the_last_record_not_the_copy_time(tmp_path):
    parser = _parser(tmp_path)
    path = next(p for p in (tmp_path / ".codebuddy" / "projects" / "C--demo").glob("s1.jsonl"))
    os.utime(path, (1_500_000_000, 1_500_000_000))  # pretend it was copied in 2017
    meta = next(m for m in parser.list_sessions() if m.session_id == "s1")
    assert meta.updated_at is not None
    assert meta.updated_at.startswith("2026-"), meta.updated_at
    raw = parser.load("s1")
    assert raw is not None and raw.meta.updated_at == meta.updated_at


def test_a_store_without_timestamps_still_reports_something(tmp_path):
    project = tmp_path / ".codebuddy" / "projects" / "C--demo"
    project.mkdir(parents=True)
    (project / "s9.jsonl").write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": "s9",
                "message": {"role": "user", "content": [{"type": "text", "text": "no stamp"}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    meta = CodebuddyParser(tmp_path / ".codebuddy" / "projects").list_sessions()
    assert meta and meta[0].updated_at, "mtime is the only date left, and it must still be used"
