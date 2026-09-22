"""Codex's cheap list-page probes: `peek_status` and `peek_needs_reply`.

The store appends the turn's end event at the end of the rollout, so a probe
that reads only the first 400 rows reports a late failure as ``clean``. The
"Needs input" signal had no Codex probe at all, so the column reported unknown
for every Codex session while the roles sat in the file. These cases are
hand-written JSONL and exercise the tail reads, their widening, and the
fallbacks across a resumed session's files.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_handoff.parsers.codex import CodexParser

SID = "019fac0f-0000-7000-8000-0000000000cc"


def _row(rtype: str, payload: dict, at: str | None = None) -> dict:
    row: dict = {"type": rtype, "payload": payload}
    if at is not None:
        row["timestamp"] = at
    return row


def _header(at: str = "2026-08-31T10:00:00.000Z") -> dict:
    return {
        "type": "session_meta",
        "payload": {"id": SID, "timestamp": at, "cwd": "D:/demo"},
    }


def _store(tmp_path: Path, files: list[tuple[str, list[dict]]]) -> CodexParser:
    root = tmp_path / "sessions" / "2026" / "08" / "31"
    root.mkdir(parents=True, exist_ok=True)
    for name, records in files:
        path = root / name
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return CodexParser(tmp_path / "sessions")


def _one(records: list[dict]) -> list[tuple[str, list[dict]]]:
    return [(f"rollout-2026-08-31T10-00-00-{SID}.jsonl", records)]


def test_error_tail_wins(tmp_path):
    records = [
        _header(),
        _row("event_msg", {"type": "task_complete", "error": "quota gone"}),
    ]
    assert _store(tmp_path, _one(records)).peek_status(SID) == "error"


def test_aborted_tail_wins(tmp_path):
    records = [
        _header(),
        _row("event_msg", {"type": "turn_aborted", "reason": "user stop"}),
    ]
    assert _store(tmp_path, _one(records)).peek_status(SID) == "cancelled"


def test_clean_tail_wins(tmp_path):
    records = [
        _header(),
        _row("event_msg", {"type": "task_complete"}),
    ]
    assert _store(tmp_path, _one(records)).peek_status(SID) == "clean"


def test_late_end_event_after_four_hundred_rows(tmp_path):
    filler = [_row("event_msg", {"type": "token_count", "info": {"n": i}}) for i in range(401)]
    records = [
        _header(),
        *filler,
        _row("event_msg", {"type": "task_complete", "error": "late failure"}),
    ]
    assert _store(tmp_path, _one(records)).peek_status(SID) == "error"


def test_latest_end_event_in_tail_wins(tmp_path):
    records = [
        _header(),
        _row("event_msg", {"type": "task_complete", "error": "late failure"}),
        _row("event_msg", {"type": "turn_aborted", "reason": "user stop"}),
    ]
    assert _store(tmp_path, _one(records)).peek_status(SID) == "cancelled"


def test_end_event_above_a_full_tail_window(tmp_path):
    """A shape this store really has: the tail holds no end event at all.

    Sessions `019fb930-cd8f…` and `019fb930-9540…` wrote ~540 KB more after
    their last `turn_aborted`, so one 64 KB tail read finds no end event and
    the head scan answers an older completion instead: the list said ``clean``
    while the detail said ``cancelled``. The window has to widen.
    """
    after = [
        _row("event_msg", {"type": "token_count", "info": {"pad": "x" * 500}})
        for _ in range(200)
    ]
    records = [
        _header(),
        _row("event_msg", {"type": "task_complete"}),
        _row("event_msg", {"type": "turn_aborted", "reason": "user stop"}),
        *after,
    ]
    assert _store(tmp_path, _one(records)).peek_status(SID) == "cancelled"


def test_clean_fallback_from_older_file(tmp_path):
    files = [
        (
            f"rollout-2026-08-31T10-00-00-{SID}.jsonl",
            [_header(), _row("event_msg", {"type": "task_complete"})],
        ),
        (
            f"rollout-2026-08-31T11-00-00-{SID}_2.jsonl",
            [
                _header("2026-08-31T11:00:00.000Z"),
                _row("response_item", {"type": "message", "role": "user", "content": "follow-up"}),
            ],
        ),
    ]
    assert _store(tmp_path, files).peek_status(SID) == "clean"


def test_none_without_any_end_or_completion(tmp_path):
    records = [
        _header(),
        _row("event_msg", {"type": "token_count", "info": {}}),
    ]
    assert _store(tmp_path, _one(records)).peek_status(SID) is None


def _msg(role: str, text: str) -> dict:
    kind = "input_text" if role == "user" else "output_text"
    block = {"type": kind, "text": text}
    return _row("response_item", {"type": "message", "role": role, "content": [block]})


def test_needs_reply_true_when_a_user_message_is_last(tmp_path):
    records = [
        _header(),
        _msg("assistant", "here is the answer"),
        _msg("user", "now do the other thing"),
    ]
    assert _store(tmp_path, _one(records)).peek_needs_reply(SID) is True


def test_needs_reply_false_once_the_assistant_answered(tmp_path):
    records = [
        _header(),
        _msg("user", "do the thing"),
        _msg("assistant", "done"),
    ]
    assert _store(tmp_path, _one(records)).peek_needs_reply(SID) is False


def test_needs_reply_counts_a_sub_agent_dispatch_as_the_parent_having_spoken(tmp_path):
    """Twelve sessions on this store end on a dispatch row, not a chat row.

    The parent's `agent_message` to its sub-agent is an assistant row that
    `_build` pushes like any other, so the session has spoken last and does not
    need input - a probe that only knew `response_item/message` reported
    unknown for all twelve.
    """
    records = [
        _header(),
        _msg("user", "go"),
        _row(
            "event_msg",
            {
                "type": "agent_message",
                "author": "/root",
                "recipient": "/root/muse_echo_3",
                "content": [{"type": "input_text", "text": "handle this"}],
            },
        ),
    ]
    assert _store(tmp_path, _one(records)).peek_needs_reply(SID) is False


def test_needs_reply_widens_past_a_full_tail_window(tmp_path):
    after = [
        _row("event_msg", {"type": "token_count", "info": {"pad": "x" * 500}})
        for _ in range(200)
    ]
    records = [_header(), _msg("assistant", "answered"), _msg("user", "and now?"), *after]
    assert _store(tmp_path, _one(records)).peek_needs_reply(SID) is True


def test_needs_reply_looks_back_through_a_resumed_session_files(tmp_path):
    files = [
        (
            f"rollout-2026-08-31T10-00-00-{SID}.jsonl",
            [_header(), _msg("user", "still waiting on this")],
        ),
        (
            f"rollout-2026-08-31T11-00-00-{SID}_2.jsonl",
            [
                _header("2026-08-31T11:00:00.000Z"),
                _row("event_msg", {"type": "token_count", "info": {}}),
            ],
        ),
    ]
    assert _store(tmp_path, files).peek_needs_reply(SID) is True


def test_needs_reply_ignores_harness_rows(tmp_path):
    records = [
        _header(),
        _row("response_item", {"type": "message", "role": "developer", "content": "injected"}),
        _row("response_item", {"type": "message", "role": "system", "content": "injected"}),
    ]
    assert _store(tmp_path, _one(records)).peek_needs_reply(SID) is None
