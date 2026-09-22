"""Codex agent_message and message phase fields, from hand-written JSONL.

The store writes inter-agent messages with a ``content`` block (not ``text`` or
``message``), so the parser must read that spelling. It also stamps
``response_item/message`` rows with the product's own ``phase`` split.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_handoff.parsers.codex import CodexParser

SID = "019fac0f-0000-7000-8000-0000000000bb"


def _row(rtype: str, payload: dict, at: str | None = None) -> dict:
    row: dict = {"type": rtype, "payload": payload}
    if at is not None:
        row["timestamp"] = at
    return row


def _header() -> dict:
    return {
        "type": "session_meta",
        "payload": {
            "id": SID,
            "timestamp": "2026-08-31T10:00:00.000Z",
            "cwd": "D:/demo",
        },
    }


def _store(tmp_path: Path, records: list[dict]) -> CodexParser:
    root = tmp_path / "sessions" / "2026" / "08" / "31"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"rollout-2026-08-31T10-00-00-{SID}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return CodexParser(tmp_path / "sessions")


def test_agent_message_content_is_kept_and_routed(tmp_path):
    records = [
        _header(),
        _row(
            "response_item",
            {
                "type": "agent_message",
                "author": "/root/nav_rail",
                "recipient": "/root",
                "content": [
                    {"type": "input_text", "text": "child body"},
                    {"type": "encrypted_content", "encrypted_content": "cipher"},
                ],
            },
        ),
    ]
    raw = _store(tmp_path, records).load(SID)
    assert raw is not None
    assert len(raw.messages) == 1
    text = raw.messages[0].text
    assert "[多代理 /root/nav_rail → /root]" in text
    assert "child body" in text
    assert "cipher" not in text


def test_legacy_text_and_message_spellings_still_work(tmp_path):
    records = [
        _header(),
        _row(
            "response_item",
            {"type": "agent_message", "author": "a", "recipient": "b", "text": "legacy text"},
        ),
        _row(
            "event_msg",
            {"type": "agent_message", "message": "legacy message"},
        ),
    ]
    raw = _store(tmp_path, records).load(SID)
    assert raw is not None
    texts = [m.text for m in raw.messages]
    assert any("legacy text" in t for t in texts)
    assert any("legacy message" in t for t in texts)


def test_same_author_and_recipient_has_no_prefix(tmp_path):
    records = [
        _header(),
        _row(
            "response_item",
            {
                "type": "agent_message",
                "author": "/root",
                "recipient": "/root",
                "content": [{"type": "input_text", "text": "self note"}],
            },
        ),
    ]
    raw = _store(tmp_path, records).load(SID)
    assert raw is not None
    assert len(raw.messages) == 1
    assert raw.messages[0].text == "self note"


def test_message_phase_is_recorded_or_none(tmp_path):
    records = [
        _header(),
        _row(
            "response_item",
            {"type": "message", "role": "user", "content": "hi", "phase": "commentary"},
        ),
        _row(
            "response_item",
            {"type": "message", "role": "assistant", "content": "reply", "phase": "final_answer"},
        ),
        _row(
            "response_item",
            {"type": "message", "role": "assistant", "content": "no phase"},
        ),
    ]
    raw = _store(tmp_path, records).load(SID)
    assert raw is not None
    by_text = {m.text: m.phase for m in raw.messages}
    assert by_text == {"hi": "commentary", "reply": "final_answer", "no phase": None}
    assert [m.role for m in raw.messages] == ["user", "assistant", "assistant"]
