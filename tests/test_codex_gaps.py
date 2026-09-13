"""What the Codex reader used to drop on the floor, one record type at a time.

event_msg rows are the product's own UI notifications and response_item rows are
the API items it renders, so a record type with no branch in _build is a record
the cockpit drops in silence. Every case below is the shape measured on a real
2026-09 store (the census in
docs/compose/spec/divergent-slice-m3components-1.md, round 27); every case is a
synthetic rollout in tmp_path, never the live store.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_handoff.parsers.codex import CodexParser

SID = "019fac0f-0000-7000-8000-0000000000bb"
CHILD = "019fb90d-d5b3-7f31-9380-8400b7cb1f23"


def _header() -> dict:
    return {
        "type": "session_meta",
        "payload": {
            "id": SID,
            "timestamp": "2026-09-12T10:00:00.000Z",
            "cwd": "D:/demo",
            "originator": "codex_cli_rs",
            "source": "cli",
        },
    }


def _store(tmp_path: Path, records: list[dict]) -> Path:
    root = tmp_path / "sessions" / "2026" / "09" / "12"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"rollout-2026-09-12T10-00-00-{SID}.jsonl"
    body = [_header(), *records]
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in body) + "\n",
        encoding="utf-8",
    )
    return tmp_path / "sessions"


def _load(tmp_path: Path, records: list[dict]):
    parser = CodexParser(_store(tmp_path, records))
    raw = parser.load(SID)
    assert raw is not None, "the synthetic rollout must load"
    return parser, raw


def _row(record_type: str, payload: dict, at: str = "2026-09-12T10:00:01.000Z") -> dict:
    return {"type": record_type, "timestamp": at, "payload": payload}


def _token_count(per_call: int, total: int, reasoning: int = 0) -> dict:
    return _row(
        "event_msg",
        {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": per_call,
                    "output_tokens": 7,
                    "reasoning_output_tokens": reasoning,
                    "total_tokens": per_call + 7,
                },
                "total_token_usage": {
                    "input_tokens": total,
                    "output_tokens": 7,
                    "total_tokens": total + 7,
                },
            },
        },
    )


def _texts(raw) -> list[str]:
    return [m.text for m in raw.messages]


# -- messages: the model's own thinking ---------------------------------------
def test_reasoning_becomes_a_folded_thinking_row(tmp_path):
    _parser, raw = _load(
        tmp_path,
        [
            _row(
                "response_item",
                {
                    "type": "reasoning",
                    "id": "rs_1",
                    "summary": [],
                    "content": [{"type": "reasoning_text", "text": "weighing the two options"}],
                },
            ),
            _row(
                "response_item",
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "picked the second"}],
                },
            ),
        ],
    )
    assert _texts(raw) == ["[思考] weighing the two options", "picked the second"]
    thinking = raw.messages[0]
    # Nothing was trimmed, so the row IS the store's text: no 原文 toggle.
    assert thinking.raw_text is None


def test_a_thinking_block_keeps_its_verbatim_form_beside_the_cleaned_one(tmp_path):
    """The house convention: cleaning that removed something leaves the source."""
    _parser, raw = _load(
        tmp_path,
        [
            _row(
                "response_item",
                {
                    "type": "reasoning",
                    "content": [
                        {
                            "type": "reasoning_text",
                            "text": "weighting it<system-reminder>ignore me</system-reminder>",
                        }
                    ],
                },
            )
        ],
    )
    thinking = raw.messages[0]
    assert thinking.text == "[思考] weighting it"
    assert thinking.raw_text == "[思考] weighting it<system-reminder>ignore me</system-reminder>"


def test_encrypted_only_reasoning_stays_out_of_the_transcript(tmp_path):
    """4512 rows exist; 4456 carry text. The rest are ciphertext, not speech."""
    _parser, raw = _load(
        tmp_path,
        [
            _row(
                "response_item",
                {
                    "type": "reasoning",
                    "id": "rs_2",
                    "summary": [],
                    "content": [{"type": "reasoning_text", "text": "   "}],
                    "encrypted_content": "gAAAAABq",
                },
            ),
            _row(
                "response_item",
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "answer"}],
                },
            ),
        ],
    )
    assert _texts(raw) == ["answer"]


# -- tools ---------------------------------------------------------------------
def test_custom_tool_call_output_carries_the_exit_code(tmp_path):
    """1918 rows the reader never looked at: every custom tool call's result."""
    _parser, raw = _load(
        tmp_path,
        [
            _row(
                "response_item",
                {
                    "type": "custom_tool_call",
                    "name": "apply_patch",
                    "call_id": "c1",
                    "input": "*** Begin Patch\n*** Update File: D:/demo/x.py\n*** End Patch",
                },
            ),
            _row(
                "response_item",
                {
                    "type": "custom_tool_call_output",
                    "call_id": "c1",
                    "output": (
                        "Exit code: 1\n"
                        "Wall time: 91.0 seconds\n"
                        "Output:\n"
                        "boom\n"
                    ),
                },
            ),
        ],
    )
    assert raw.tool_counts["apply_patch"] == 1
    assert raw.tool_counts["exit:1"] == 1
    assert raw.tool_counts["slow_call>=60s"] == 1


def test_the_other_execution_spelling_is_read_too(tmp_path):
    """exec_command writes "Process exited with code 1", not "Exit code: 1"."""
    _parser, raw = _load(
        tmp_path,
        [
            _row(
                "response_item",
                {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "c7",
                    "arguments": json.dumps({"cmd": "rg shape"}),
                },
            ),
            _row(
                "response_item",
                {
                    "type": "function_call_output",
                    "call_id": "c7",
                    "output": (
                        "Chunk ID: f9820c\n"
                        "Wall time: 0.0562 seconds\n"
                        "Process exited with code 1\n"
                        "Original token count: 53\n"
                        "Output:\n"
                        "rg: |^\\s+shapePressed: |shape:: bad\n"
                    ),
                },
            ),
        ],
    )
    assert raw.tool_counts["exit:1"] == 1


def test_a_slow_command_is_noted_in_both_spellings(tmp_path):
    _parser, raw = _load(
        tmp_path,
        [
            _row(
                "response_item",
                {
                    "type": "function_call_output",
                    "call_id": "c8",
                    "output": "Chunk ID: aa\nWall time: 91.0 seconds\nProcess exited with code 0\n",
                },
            )
        ],
    )
    assert raw.tool_counts["slow_call>=60s"] == 1
    assert not [k for k in raw.tool_counts if k.startswith("exit:")]


def test_a_tool_call_is_a_row_and_its_arguments_are_the_body(tmp_path):
    _parser, raw = _load(
        tmp_path,
        [
            _row(
                "response_item",
                {
                    "type": "function_call",
                    "name": "shell_command",
                    "call_id": "c2",
                    "arguments": json.dumps({"command": "Get-ChildItem D:/demo"}),
                },
            )
        ],
    )
    row = next(m for m in raw.messages if m.text.startswith("[工具"))
    head, _nl, body = row.text.partition("\n")
    assert head.startswith("[工具 shell_command")
    assert "Get-ChildItem D:/demo" in head
    assert "Get-ChildItem D:/demo" in body
    assert row.raw_text and "shell_command" in row.raw_text


def test_search_calls_become_tool_rows_with_their_queries(tmp_path):
    _parser, raw = _load(
        tmp_path,
        [
            _row(
                "response_item",
                {
                    "type": "tool_search_call",
                    "call_id": "c3",
                    "execution": "client",
                    "status": "completed",
                    "arguments": {"query": "spawn subagent parallel task"},
                },
            ),
            _row("response_item", {"type": "tool_search_output", "call_id": "c3", "tools": []}),
            _row(
                "response_item",
                {
                    "type": "web_search_call",
                    "id": "ws1",
                    "status": "completed",
                    "action": {"type": "search", "queries": ["live2d moc parser", "cubism 2.1"]},
                },
            ),
        ],
    )
    assert raw.tool_counts["tool_search"] == 1
    assert raw.tool_counts["web_search"] == 1
    assert any(
        "[工具 tool_search" in t and "spawn subagent parallel task" in t for t in _texts(raw)
    )
    assert any("[工具 web_search" in t and "live2d moc parser" in t for t in _texts(raw))
    # the output row carries no exit code and no wall clock: nothing to show
    assert not any("tool_search_output" in t for t in _texts(raw))


def test_sub_agent_activity_names_the_child(tmp_path):
    _parser, raw = _load(
        tmp_path,
        [
            _row(
                "event_msg",
                {
                    "type": "item_completed",
                    "item": {
                        "type": "SubAgentActivity",
                        "kind": "started",
                        "agent_path": "/root/media_formats",
                        "agent_thread_id": CHILD,
                    },
                },
            )
        ],
    )
    row = next(t for t in _texts(raw) if t.startswith("[子代理"))
    assert "/root/media_formats" in row
    assert CHILD in row


# -- files ---------------------------------------------------------------------
def test_file_changes_and_viewed_images_are_files_touched(tmp_path):
    _parser, raw = _load(
        tmp_path,
        [
            _row(
                "event_msg",
                {
                    "type": "item_completed",
                    "item": {
                        "type": "FileChange",
                        "id": "call_1",
                        "status": "completed",
                        "changes": {
                            "D:/demo/a.py": {"type": "update", "unified_diff": "@@ -1 +1 @@"},
                            "D:/demo/b.py": {"type": "add", "unified_diff": "@@ -0 +1 @@"},
                        },
                    },
                },
            ),
            _row(
                "event_msg",
                {
                    "type": "item_completed",
                    "item": {
                        "type": "ImageView",
                        "id": "call_2",
                        "path": "file:///C:/shots/dark.png",
                    },
                },
            ),
        ],
    )
    assert raw.files_touched["D:/demo/a.py"] == 1
    assert raw.files_touched["D:/demo/b.py"] == 1
    assert any("shots/dark.png" in p for p in raw.files_touched)


# -- end state -----------------------------------------------------------------
def test_an_aborted_turn_is_the_end_state(tmp_path):
    _parser, raw = _load(
        tmp_path,
        [
            _row(
                "response_item",
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "go"}],
                },
            ),
            _row("event_msg", {"type": "task_started", "model_context_window": 996147}),
            _row(
                "event_msg",
                {"type": "turn_aborted", "reason": "interrupted", "duration_ms": 1761049},
            ),
        ],
    )
    assert raw.interruption.kind == "cancelled", raw.interruption.detail
    assert "interrupt" in raw.interruption.detail


def test_an_abort_that_a_later_turn_survives_is_not_the_end_state(tmp_path):
    _parser, raw = _load(
        tmp_path,
        [
            _row("event_msg", {"type": "turn_aborted", "reason": "interrupted"}),
            _row("event_msg", {"type": "task_started"}),
            _row(
                "response_item",
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "done"}],
                },
            ),
            _row("event_msg", {"type": "task_complete"}),
        ],
    )
    assert raw.interruption.kind == "clean"


# -- compaction ----------------------------------------------------------------
def test_a_compaction_is_recorded_with_its_measured_window(tmp_path):
    _parser, raw = _load(
        tmp_path,
        [
            _row(
                "response_item",
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "go"}]},
            ),
            _row(
                "response_item",
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "on it"}],
                },
            ),
            _token_count(138122, 354947),
            _row(
                "compacted",
                {
                    "message": "summary of everything before",
                    "window_number": 3,
                    "previous_window_id": "w2",
                    "latest_token_usage_record": None,
                },
            ),
            _token_count(16688, 371635),
        ],
    )
    assert len(raw.compactions) == 1
    event = raw.compactions[0]
    assert "3" in event.reason
    assert (event.pre_tokens, event.post_tokens) == (138122, 16688)
    # The divider belongs where it happened: two turns had been written.
    assert event.after_messages == 2, raw.messages


# -- notes ---------------------------------------------------------------------
def test_the_thread_goal_is_a_note(tmp_path):
    _parser, raw = _load(
        tmp_path,
        [
            _row(
                "event_msg",
                {
                    "type": "thread_goal_updated",
                    "goal": {
                        "objective": "ship the cockpit",
                        "status": "paused",
                        "tokensUsed": 12,
                    },
                },
            )
        ],
    )
    assert any(n.startswith("goal:paused") and "ship the cockpit" in n for n in raw.meta.notes)


def test_thread_settings_supply_the_model_when_turn_context_is_silent(tmp_path):
    parser, raw = _load(
        tmp_path,
        [
            _row(
                "event_msg",
                {
                    "type": "thread_settings_applied",
                    "thread_settings": {
                        "model": "deepseek-v4-flash",
                        "model_provider_id": "deepseek",
                        "service_tier": "default",
                    },
                },
            )
        ],
    )
    assert raw.meta.model == "deepseek-v4-flash"
    assert any("provider:deepseek" in n for n in raw.meta.notes)
    assert parser.last_request_tokens(SID) == {}


# -- usage, second spelling ----------------------------------------------------
def _usage_record(per_call: int, total: int) -> dict:
    return {
        "type": "token_usage_record",
        "timestamp": "2026-09-12T10:00:05.000Z",
        "payload": {
            "thread_id": SID,
            "session_id": SID,
            "usage": {
                "input_tokens": per_call,
                "output_tokens": 7,
                "total_tokens": per_call + 7,
            },
            "thread_token_usage": {
                "input_tokens": total,
                "output_tokens": 7,
                "total_tokens": total + 7,
            },
        },
    }


# -- the header's own facts -----------------------------------------------------
def _header_with(**extra) -> dict:
    payload = dict(_header()["payload"])
    payload.update(extra)
    return {"type": "session_meta", "payload": payload}


def _load_header(tmp_path, **extra):
    root = tmp_path / "sessions" / "2026" / "09" / "12"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"rollout-2026-09-12T10-00-00-{SID}.jsonl"
    rows = [_header_with(**extra), _row("event_msg", {"type": "task_complete"})]
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    parser = CodexParser(tmp_path / "sessions")
    raw = parser.load(SID)
    assert raw is not None
    return parser, raw


def test_a_nested_policy_is_json_and_not_a_python_repr(tmp_path):
    _parser, raw = _load(
        tmp_path,
        [
            _row(
                "turn_context",
                {"sandbox_policy": {"type": "workspace-write", "writable_roots": ["D:/demo"]}},
            )
        ],
    )
    note = next(n for n in raw.meta.notes if n.startswith("sandbox_policy:"))
    assert note == 'sandbox_policy:{"type":"workspace-write","writable_roots":["D:/demo"]}', note
    assert "'" not in note, "a Python repr leaked into the cockpit"


def test_the_header_records_the_revision_the_session_ran_on(tmp_path):
    _parser, raw = _load_header(tmp_path, git={"branch": "webgal", "commit_hash": "cd1bc06df0ba"})
    assert any(n == "git:webgal@cd1bc06" for n in raw.meta.notes), raw.meta.notes


def test_a_page_that_starts_mid_history_says_so(tmp_path):
    _parser, raw = _load_header(
        tmp_path,
        thread_source="subagent",
        parent_thread_id="019fb863-138f-7f01-8f1f-716c90c789ac",
        subagent_history_start_ordinal=619,
    )
    note = next((n for n in raw.meta.notes if n.startswith("history_start:")), "")
    assert note.startswith("history_start:619"), raw.meta.notes
    assert "019fb863" in note, "the note names the thread the earlier turns live in"


def test_the_page_start_is_a_field_and_not_only_a_note(tmp_path):
    """The server renders this as a marker, the way a compaction is rendered."""
    _parser, raw = _load_header(
        tmp_path,
        thread_source="subagent",
        parent_thread_id="019fb863-138f-7f01-8f1f-716c90c789ac",
        subagent_history_start_ordinal=619,
    )
    assert raw.history_start is not None
    assert raw.history_start.ordinal == 619
    assert raw.history_start.parent_session_id == "019fb863-138f-7f01-8f1f-716c90c789ac"
    assert raw.history_start.at, "the marker needs the header's timestamp to sort in"


def test_a_whole_conversation_has_no_history_start(tmp_path):
    _parser, raw = _load_header(tmp_path)
    assert raw.history_start is None


def test_a_whole_conversation_says_nothing_about_pages(tmp_path):
    _parser, raw = _load_header(tmp_path, history_mode="paginated")
    assert not [n for n in raw.meta.notes if n.startswith("history_start:")]


def test_the_thread_source_becomes_the_task_kind(tmp_path):
    _p1, sub = _load_header(tmp_path / "a", thread_source="subagent")
    _p2, user = _load_header(tmp_path / "b", thread_source="user")
    _p3, created = _load_header(tmp_path / "c", thread_source="agent_created_thread")
    assert sub.meta.task_type == "subagent"
    assert user.meta.task_type is None, "an ordinary conversation is not a task kind"
    assert created.meta.task_type == "agent_created_thread"


def test_a_forked_thread_falls_back_to_the_thread_it_was_cut_from(tmp_path):
    _parser, raw = _load_header(tmp_path, forked_from_id="01a08bc6-754b-78e1-9a1c-b9ba74f8354f")
    assert raw.meta.parent_session_id == "01a08bc6-754b-78e1-9a1c-b9ba74f8354f"


def test_usage_records_are_usage_when_token_count_is_absent(tmp_path):
    parser, _raw = _load(tmp_path, [_usage_record(6765, 6765)])
    assert parser.last_request_tokens(SID)["input_tokens"] == 6765
    usage = parser.usage(SID)
    assert usage is not None
    assert usage["totals"]["tokens_in"] == 6765
    assert usage["totals"]["calls"] == 1


def test_one_request_spelled_both_ways_counts_once(tmp_path):
    parser, _raw = _load(tmp_path, [_token_count(6765, 6765), _usage_record(6765, 6765)])
    usage = parser.usage(SID)
    assert usage is not None
    assert usage["totals"]["calls"] == 1
    assert parser.last_request_tokens(SID)["input_tokens"] == 6765


# -- billing placement ---------------------------------------------------------
def test_the_answer_takes_the_billing_not_the_tool_or_thinking_row(tmp_path):
    """token_count arrives after the items it measured, and the transcript now
    carries thinking and tool cards, so the settle-back has to skip them."""
    _parser, raw = _load(
        tmp_path,
        [
            _row(
                "response_item",
                {
                    "type": "reasoning",
                    "content": [{"type": "reasoning_text", "text": "thinking first"}],
                },
            ),
            _row(
                "response_item",
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "the answer"}],
                },
            ),
            _row(
                "response_item",
                {
                    "type": "function_call",
                    "name": "shell_command",
                    "call_id": "c9",
                    "arguments": json.dumps({"command": "echo hi"}),
                },
            ),
            _row(
                "response_item",
                {"type": "function_call_output", "call_id": "c9", "output": "Exit code: 0"},
            ),
            _token_count(100, 100, reasoning=3),
        ],
    )
    answer = next(m for m in raw.messages if m.text == "the answer")
    assert (answer.tokens_in, answer.tokens_out) == (100, 7)
    assert answer.tokens_reasoning == 3
    for row in raw.messages:
        if row is answer:
            continue
        assert row.tokens_in is None, row.text[:40]
        assert row.tokens_out is None, row.text[:40]
