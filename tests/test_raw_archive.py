"""The verbatim layer: parser.raw_archive must hand back the vendor's own
storage, byte-faithful — the thing the summarized brief sits above.

A handoff that re-derives its context from a parser is only as lossless as
the newest parser version; carrying the original lines (tool calls, system
rows, unknown future fields) makes "handoff" an identity, not a summary.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_handoff.model import HandoffBundle
from agent_handoff.parsers.jsonl_family import QodercnIdeParser
from agent_handoff.parsers.zcode import ZcodeParser
from agent_handoff.render import parse_bundle_markdown, render_markdown


def _write_session(rootdir: Path, name: str, sid: str, text: str) -> Path:
    rootdir.mkdir(parents=True, exist_ok=True)
    rows = [
        {"type": "runtime-config", "sessionId": sid, "timestamp": 1},
        {"type": "user", "timestamp": "2026-08-30T10:00:00Z",
         "message": {"role": "user", "content": [{"type": "text", "text": text}]}},
        {"type": "assistant", "timestamp": "2026-08-30T10:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "ok"},
             {"type": "tool_use", "name": "Edit",
              "input": {"file_path": "src/main.py", "old_string": "x"}}]}},
    ]
    target = rootdir / f"{name}.jsonl"
    with open(target, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return target


def test_jsonl_raw_archive_is_byte_faithful(tmp_path):
    """Archiving must return the file's own bytes, hash-verified, and the
    tool_use block must still be present (the parsed transcript drops it)."""
    store = tmp_path / ".qoder-cn" / "projects" / "D----x" / "transcript"
    src = _write_session(store, "rawme1", "rawme1", "fix the thing")
    p = QodercnIdeParser(tmp_path / ".qoder-cn")
    archive = p.raw_archive("rawme1")
    assert archive is not None and len(archive) == 1
    entry = archive[0]
    data = str(entry["text"]).encode("utf-8", "surrogateescape")
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert data == src.read_bytes()  # identical, not just hash-equal
    assert '"type": "tool_use"' in entry["text"]  # verbatim keeps the tool call
    assert entry["encoding"] == "utf-8"
    assert entry["path"].replace("\\", "/").endswith("transcript/rawme1.jsonl")


def test_hybrid_archive_includes_subagents(tmp_path):
    """codebuddy layout: session dir with subagents + flat main file. The raw
    archive must carry BOTH files the parser merges."""
    root = tmp_path / ".codebuddy" / "projects" / "D--demo"
    flat = root / "def456.jsonl"
    _write_session(root / "def456" / "subagents", "agent-abc123", "agent-abc123", "side work")
    with open(flat, "w", encoding="utf-8") as fh:
        for row in [
            {"type": "runtime-config", "sessionId": "def456", "timestamp": 1},
            {"type": "user", "timestamp": "2026-08-30T10:00:00Z",
             "message": {"role": "user", "content": [{"type": "text", "text": "main turn"}]}},
        ]:
            fh.write(json.dumps(row) + "\n")
    from agent_handoff.parsers.jsonl_family import CodebuddyParser

    p = CodebuddyParser(tmp_path / ".codebuddy")
    archive = p.raw_archive("def456")
    assert archive is not None and len(archive) == 2
    names = sorted(a["path"].replace("\\", "/") for a in archive)
    assert any(n.endswith("def456.jsonl") for n in names)
    assert any("subagents" in n and "agent-abc123.jsonl" in n for n in names)


def test_sqlite_records_archive_keeps_every_column(zcode_store):
    """SQLite stores have no per-session file, so the archive is record-level
    JSON lines — every column of every row, including columns the parser
    never reads (e.g. todo.position / project_id)."""
    p = ZcodeParser(zcode_store / "zcode" / "cli" / "db" / "db.sqlite")
    archive = p.raw_archive("sess_a")
    assert archive is not None and len(archive) == 1
    entry = archive[0]
    assert entry["encoding"] == "json"
    assert entry["path"].endswith("sess_a.records.jsonl")

    records = [json.loads(line) for line in entry["text"].splitlines()]
    tables = {r["table"] for r in records}
    assert "todo" in tables and "message" in tables and "model_usage" in tables
    msg = next(r["row"] for r in records if r["table"] == "message")
    # columns the parser never SELECTs must be present anyway (verbatim)
    assert "sequence" in msg and "project_id" in next(
        r["row"] for r in records if r["table"] == "session"
    )
    todo_positions = {r["row"]["position"] for r in records if r["table"] == "todo"}
    assert todo_positions == {0, 1, 2}  # all three rows, positions included

    missing = p.raw_archive("nope")
    assert missing is None  # honest: nothing to archive, never a fake copy


def test_bundle_roundtrip_preserves_raw(tmp_path):
    """A bundle rendered to markdown and parsed back keeps the raw archive
    hash-identical — the sentinel block rides the same round-trip as the
    full transcript instead of being truncated by it."""
    store = tmp_path / ".qoder-cn" / "projects" / "D----x"
    _write_session(store / "transcript", "rt1", "rt1", "round trip me")
    p = QodercnIdeParser(tmp_path / ".qoder-cn")
    meta = p.list_sessions()[0]
    raw = p.raw_archive(meta.session_id)
    bundle = HandoffBundle(meta=meta)
    bundle.full_transcript = [("user", "before"), ("assistant", "after")]
    bundle.raw_files = raw or []

    text = render_markdown(bundle)
    back = parse_bundle_markdown(text)
    assert [r for r, _t in back.full_transcript] == ["user", "assistant"]
    assert len(back.raw_files) == len(raw or [])
    for a, b in zip(back.raw_files, raw or [], strict=True):
        assert a["sha256"] == b["sha256"]
        assert a["text"] == b["text"]


def test_dump_raw_files_extracts_and_verifies(tmp_path):
    """Extraction writes the original bytes back and reports hash mismatches
    honestly instead of silently extracting a corrupted copy."""
    from agent_handoff import cli
    from agent_handoff.model import SessionMeta

    payload = b"hello\nverbatim\n"
    meta = SessionMeta(
        cli="x", session_id="s", title="t", cwd="",
        source_path="x",
    )
    bundle = HandoffBundle(
        meta=meta,
        raw_files=[{
            "path": "a/b/c.jsonl",
            "encoding": "utf-8",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "text": payload.decode("utf-8", "surrogateescape"),
        }],
    )
    out = cli.dump_raw_files(bundle, tmp_path / "dump")
    assert out is not None and len(out) == 1
    written, ok = out[0]
    assert ok
    assert Path(written).read_bytes() == payload

    # corrupt hash => the report says so (never a silent pass)
    bundle.raw_files[0]["sha256"] = "0" * 64
    out = cli.dump_raw_files(bundle, tmp_path / "dump2")
    assert out is not None and out[0][1] is False

    assert cli.dump_raw_files(HandoffBundle(meta=meta), tmp_path / "dump3") is None
