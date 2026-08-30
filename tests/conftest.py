"""Synthetic fixture builders — no real session transcripts ever."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def zcode_store(tmp_path: Path) -> Path:
    """Build a minimal ZCode-style SQLite store with two sessions."""
    db = tmp_path / "zcode" / "cli" / "db" / "db.sqlite"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE session (id TEXT, project_id TEXT, title TEXT, directory TEXT,
            time_created INTEGER, time_updated INTEGER);
        CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER,
            data TEXT, sequence INTEGER);
        CREATE TABLE part (id TEXT, message_id TEXT, session_id TEXT,
            data TEXT, sequence INTEGER);
        CREATE TABLE todo (session_id TEXT, content TEXT, status TEXT,
            priority TEXT, position INTEGER);
        """
    )
    con.execute(
        "INSERT INTO session VALUES ('sess_a','p','Fix login loop','D:/demo',"
        "1756500000000,1756503600000)"
    )
    msgs = [
        ("m1", "user", 1756500001000,
         [("text", "Fix the login redirect loop. 不要引入新的依赖")], 0),
        ("m2", "assistant", 1756500002000, [("text", "Root cause: middleware order.")], 1),
        ("m3", "assistant", 1756500003000, [("text", "Patched auth middleware.")], 2),
    ]
    for mid, role, ts, parts, seq in msgs:
        con.execute(
            "INSERT INTO message VALUES (?,?,?,?,?)",
            (mid, "sess_a", ts,
             json.dumps({"role": role, "tokens": {"input": 10, "output": 5}}), seq),
        )
        for pi, (ptype, text) in enumerate(parts):
            con.execute(
                "INSERT INTO part VALUES (?,?,?,?,?)",
                (f"{mid}p{pi}", mid, "sess_a", json.dumps({"type": ptype, "text": text}), pi),
            )
    # tool part with file path
    con.execute(
        "INSERT INTO part VALUES ('m2tool','m2','sess_a',?,3)",
        (
            json.dumps(
                {
                    "type": "tool",
                    "tool": "Edit",
                    "state": {"status": "completed", "input": {"file_path": "src/auth.ts"}},
                }
            ),
        ),
    )
    con.execute("INSERT INTO todo VALUES ('sess_a','reproduce bug','completed','high',0)")
    con.execute("INSERT INTO todo VALUES ('sess_a','patch middleware','in_progress','high',1)")
    con.execute("INSERT INTO todo VALUES ('sess_a','write regression test','pending','medium',2)")
    con.commit()
    con.close()
    return tmp_path


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


@pytest.fixture
def claude_store(tmp_path: Path) -> Path:
    root = tmp_path / "claude" / "projects" / "D--demo"
    _jsonl(
        root / "abc123.jsonl",
        [
            {"type": "summary", "summary": "Demo session", "leafUuid": "x"},
            {
                "type": "user",
                "sessionId": "abc123",
                "cwd": "D:/demo",
                "timestamp": "2026-08-30T10:00:00Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "hello, do the thing"}],
                },
            },
            {
                "type": "assistant",
                "sessionId": "abc123",
                "cwd": "D:/demo",
                "timestamp": "2026-08-30T10:00:05Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Working on it."},
                        {"type": "tool_use", "name": "Read", "input": {"file_path": "src/main.py"}},
                        {"type": "tool_use", "name": "TodoWrite", "input": {"todos": [
                            {"content": "step one", "status": "completed", "priority": "high"},
                            {"content": "step two", "status": "in_progress", "priority": "high"},
                        ]}},
                    ],
                },
            },
            {"type": "file-history-snapshot", "id": "s1", "snapshot": {}},
            "this line is not json and must be skipped\n",
        ],
    )
    # corrupt trailing line: read_jsonl must tolerate it
    with open(root / "abc123.jsonl", "a", encoding="utf-8") as f:
        f.write("{broken json\n")
    return tmp_path


@pytest.fixture
def codebuddy_store(tmp_path: Path) -> Path:
    root = tmp_path / "codebuddy" / "projects" / "d--demo"
    _jsonl(
        root / "def456.jsonl",
        [
            {
                "type": "message",
                "role": "user",
                "sessionId": "def456",
                "cwd": "D:/demo",
                "timestamp": 1756548000000,
                "content": [{"type": "input_text", "text": "codebuddy turn"}],
            },
            {
                "type": "message",
                "role": "assistant",
                "sessionId": "def456",
                "cwd": "D:/demo",
                "timestamp": 1756548005000,
                "content": [{"type": "output_text", "text": "done"}],
            },
        ],
    )
    return tmp_path


@pytest.fixture
def dsh_store(tmp_path: Path) -> Path:
    zstd = pytest.importorskip("zstandard")
    roll = tmp_path / "dsh" / "sessions" / "--D--demo--" / "11112222" / "session.jsonl.zstd"
    roll.parent.mkdir(parents=True)
    rows = [
        {"type": "session", "id": "11112222", "createdAt": 1756548000000, "cwd": "D:/demo"},
        {"type": "session/title", "data": {"title": "dsh demo task"}},
        {"type": "user/message", "seq": 1, "time": 1756548001000,
         "data": {"content": [{"type": "text", "text": "dsh user ask"}]}},
        {"type": "assistant/chunk", "seq": 2, "time": 1756548002000,
         "data": {"chunk": {"type": "text", "text": "dsh reply"}}},
        {"type": "assistant/chunk", "seq": 3, "time": 1756548002500,
         "data": {"chunk": {"type": "usage", "usage": {"inputTokens": 5}}}},
        {"type": "turn/start", "seq": 4},
    ]
    data = ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)).encode("utf-8")
    roll.write_bytes(zstd.ZstdCompressor().compress(data))
    return tmp_path


@pytest.fixture
def codex_store(tmp_path: Path) -> Path:
    root = tmp_path / "codex" / "sessions"
    _jsonl(
        root / "rollout-2026-08-01T22-28-02-aaa.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {
                    "session_id": "aaa",
                    "timestamp": "2026-08-01T14:28:02.495Z",
                    "cwd": "D:/demo",
                },
            },
            {"type": "response_item", "payload": {"type": "message", "role": "developer",
                "content": [{"type": "input_text", "text": "<app-context> injected"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "codex ask"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": "codex answer"}]}},
        ],
    )
    return tmp_path
