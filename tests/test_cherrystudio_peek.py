"""Round 61: the "Needs input" probe for CherryStudio dialogues.

`scripts/probe_audit.py` measured 8 rows on this machine where the detail page can
name the last line of the conversation while the list column says nothing. The
store is one SQLite file of real user↔assistant dialogues, so the answer is in it —
what was missing was asking.

The predicate is `load()`'s, row for row and block for block, because the two
things that make this store awkward are both about *rows* rather than sessions:

* one row is one LLM call and can render several messages — a row whose last block
  is a tool call ends on an assistant line whatever its own role says, so "the last
  row's role" and "the last line on the page" are different questions;
* a row can render nothing at all (an empty tool result, a thinking block that
  cleans to nothing, a role the page does not show, content that will not decode),
  so the walk has to go back.

Every test asserts probe and page agree, because that agreement is the claim: a
probe that disagrees with the page is a lie, and one that quietly answers a simpler
question is the same lie with greener tests. Where a shape does not occur on this
machine's store the test says so, so a reader can tell coverage from evidence.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from agent_handoff.parsers import base as pb
from agent_handoff.parsers.cherrystudio import CherryStudioParser

T0 = "2026-07-05T08:19:30.000Z"

SCHEMA = """
CREATE TABLE agents (
    id TEXT PRIMARY KEY NOT NULL, name TEXT, created_at TEXT);
CREATE TABLE sessions (
    id TEXT PRIMARY KEY NOT NULL, agent_id TEXT, name TEXT,
    created_at TEXT, updated_at TEXT);
CREATE TABLE session_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, session_id TEXT NOT NULL,
    role TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    agent_session_id TEXT DEFAULT '');
"""


@pytest.fixture(autouse=True)
def _fresh_memo():
    """Answers are memoised per store path; never across a test boundary."""
    pb._SQL_NEEDS_REPLY_CACHE.clear()
    yield
    pb._SQL_NEEDS_REPLY_CACHE.clear()


def _text(content):
    return {"type": "main_text", "content": content}


def _thinking(content):
    return {"type": "thinking", "content": content}


def _tool(content=None):
    return {"type": "tool", "content": content, "metadata": {}}


def _payload(role, blocks, **message):
    """The `{"message": …, "blocks": […]}` envelope as the store writes it."""
    return {"message": {"role": role, **message}, "blocks": list(blocks)}


def _later(ms: int, base: str = T0) -> str:
    """A timestamp `ms` after the base, in the format the store stamps rows with."""
    when = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    when = when + timedelta(milliseconds=ms)
    return when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"


def _store(tmp_path, rows: list[tuple]) -> CherryStudioParser:
    """Build an agents.db. A row is (session_id, role_column, created_at, payload).

    `payload` is a dict when it should be JSON and a raw string when the test is
    about content the store cannot even decode.
    """
    db = tmp_path / "agents.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    for sid in sorted({r[0] for r in rows}):
        con.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", (sid, "a1", f"会话 {sid}", T0, T0))
    for sid, role, when, payload in rows:
        content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        con.execute(
            "INSERT INTO session_messages"
            " (session_id, role, content, created_at, updated_at) VALUES (?,?,?,?,?)",
            (sid, role, content, when, when),
        )
    con.commit()
    con.close()
    return CherryStudioParser(db)


def _page_ends_on(parser: CherryStudioParser, sid: str) -> bool | None:
    """What the detail page shows last, read out of the full parse."""
    raw = parser.load(sid)
    shown = [
        m
        for m in (raw.messages if raw else [])
        if m.role in ("user", "assistant") and (m.text or "").strip()
    ]
    return None if not shown else shown[-1].role == "user"


def _asked(p: CherryStudioParser, sid: str, expect: bool | None):
    """Probe and page, both, every time — the pair is the claim."""
    assert p.peek_needs_reply(sid) is expect, "the probe answered wrongly"
    assert _page_ends_on(p, sid) is expect, "the probe and the page disagree"


def test_a_dialogue_ending_on_a_user_line_is_waiting(tmp_path):
    p = _store(
        tmp_path,
        [
            ("s1", "user", T0, _payload("user", [_text("帮我把这段配音跑完")])),
            ("s1", "assistant", _later(12000), _payload("assistant", [_text("稍等")])),
            ("s1", "user", _later(30000), _payload("user", [_text("然后呢？")])),
        ],
    )
    _asked(p, "s1", True)


def test_an_answered_dialogue_says_so(tmp_path):
    p = _store(
        tmp_path,
        [
            ("s1", "user", T0, _payload("user", [_text("帮我把这段配音跑完")])),
            ("s1", "assistant", _later(12000), _payload("assistant", [_text("跑完了。")])),
        ],
    )
    _asked(p, "s1", False)


def test_a_row_that_ends_on_a_tool_call_is_not_a_user_line(tmp_path):
    """The shape one row can take: the tool call is the last thing on the page.

    A probe reading "the last row's role" answers True here while the page shows an
    assistant line. Measured on this machine's store, no user row carries a tool
    block (all 112 of them are a lone `main_text`), so this is coverage of `load()`'s
    rule rather than an answer anyone is being given today.
    """
    p = _store(
        tmp_path,
        [
            ("s1", "user", T0, _payload("user", [_text("查一下模型缓存")])),
            ("s1", "user", _later(9000), _payload("user", [_text("我看一下。"), _tool("ls")])),
        ],
    )
    _asked(p, "s1", False)


def test_an_empty_tool_result_renders_nothing_so_the_row_answer_changes(tmp_path):
    """Same shape, opposite answer: the final block has no text to show."""
    p = _store(
        tmp_path,
        [
            ("s1", "user", T0, _payload("user", [_text("查一下模型缓存")])),
            ("s1", "user", _later(9000), _payload("user", [_text("我看一下。"), _tool(None)])),
        ],
    )
    _asked(p, "s1", True)


def test_a_row_of_only_a_thinking_block_is_still_an_assistant_line(tmp_path):
    p = _store(
        tmp_path,
        [
            ("s1", "user", T0, _payload("user", [_text("问题")])),
            ("s1", "assistant", _later(4000), _payload("assistant", [_thinking("想了一会儿")])),
        ],
    )
    _asked(p, "s1", False)


def test_a_row_whose_text_cleans_to_nothing_carries_no_turn(tmp_path):
    """An environment wrapper is not something a human typed, and `clean_text` says so.

    The page drops it, so the row behind it is still the last line a reader saw — and
    that row is an assistant's, so a probe that skips cleaning reports a question
    where the page reports an answer.
    """
    p = _store(
        tmp_path,
        [
            ("s1", "user", T0, _payload("user", [_text("问题")])),
            (
                "s1",
                "assistant",
                _later(6000),
                _payload(
                    "assistant",
                    [_text("<environment_context><cwd>D:/demo</cwd></environment_context>")],
                ),
            ),
        ],
    )
    _asked(p, "s1", True)


def test_injected_text_is_not_a_turn(tmp_path):
    """The other half of the same rule: here it is `is_noise`, not cleaning."""
    p = _store(
        tmp_path,
        [
            ("s1", "user", T0, _payload("user", [_text("问题")])),
            (
                "s1",
                "assistant",
                _later(6000),
                _payload(
                    "assistant",
                    [_text('<system-reminder kind="goal">继续</system-reminder>')],
                ),
            ),
        ],
    )
    _asked(p, "s1", True)


def test_a_role_the_page_does_not_show_is_not_a_turn(tmp_path):
    p = _store(
        tmp_path,
        [
            ("s1", "user", T0, _payload("user", [_text("还要改什么")])),
            ("s1", "system", _later(5000), _payload("system", [_text("成员已加入")])),
        ],
    )
    _asked(p, "s1", True)


def test_the_envelope_role_wins_and_the_column_is_the_fallback(tmp_path):
    """Two places name a row's role; the probe must read the one the page reads.

    Measured on this machine's store: 0 of 224 rows have an envelope role that
    differs from their column, so the precedence is not being exercised by real
    data — which is why it is pinned here rather than left to the live audit.
    """
    for role_column, expect in (("assistant", True), ("user", False)):
        pb._SQL_NEEDS_REPLY_CACHE.clear()
        p = _store(
            tmp_path / role_column,
            [
                (
                    "s1",
                    role_column,
                    T0,
                    {"message": {"role": "user" if expect else "assistant"},
                     "blocks": [_text("同一句")]},
                )
            ],
        )
        _asked(p, "s1", expect)


def test_a_row_with_no_role_in_the_envelope_is_the_columns_role(tmp_path):
    """The fallback direction of the same pair.

    An envelope can carry model/usage and no role at all; `load()` then reads the
    column, and a probe that only looked at the JSON would drop the row and answer
    about the one behind it. Measured on this machine's store, no row is written
    that way today — all 224 carry an envelope role — so this pins the fallback
    rather than describing the data.
    """
    for role_column, expect in (("user", True), ("assistant", False)):
        pb._SQL_NEEDS_REPLY_CACHE.clear()
        p = _store(
            tmp_path / f"col-{role_column}",
            [
                ("s1", "assistant" if expect else "user", T0,
                 _payload("assistant" if expect else "user", [_text("前一句")])),
                ("s1", role_column, _later(7000), {"message": {"model": {"name": "glm-5.2"}},
                 "blocks": [_text("这一句")]}),
            ],
        )
        _asked(p, "s1", expect)


def test_a_row_the_store_cannot_decode_renders_nothing(tmp_path):
    p = _store(
        tmp_path,
        [
            ("s1", "user", T0, _payload("user", [_text("问题")])),
            ("s1", "assistant", _later(3000), "{not json at all"),
        ],
    )
    _asked(p, "s1", True)


def test_two_rows_in_one_instant_keep_the_pages_order(tmp_path):
    """`load()` reads (created_at, rowid); the probe reads the same pair reversed.

    A burst of writes can share one millisecond. Measured on this machine's store:
    0 tied (session, instant) pairs in 224 rows, so no answer today depends on it —
    and that is exactly why it needs a test instead of an audit run.
    """
    for last, expect in (("user", True), ("assistant", False)):
        pb._SQL_NEEDS_REPLY_CACHE.clear()
        first = "assistant" if last == "user" else "user"
        p = _store(
            tmp_path / last,
            [
                ("s1", first, T0, _payload(first, [_text("先写的")])),
                ("s1", last, T0, _payload(last, [_text("后写的")])),
            ],
        )
        _asked(p, "s1", expect)


def test_an_unknown_session_stays_unknown(tmp_path):
    p = _store(tmp_path, [("s1", "user", T0, _payload("user", [_text("问题")]))])
    _asked(p, "s2", None)


def test_a_session_of_rows_that_render_nothing_declines(tmp_path):
    """No window to run out of, and the honest answer is still `None`.

    Every row is an empty tool result, so the page shows no line at all; the probe
    must not invent an ending the list cannot show either.
    """
    rows = [
        ("s1", "assistant", _later(i * 1000), _payload("assistant", [_tool(None)]))
        for i in range(300)
    ]
    p = _store(tmp_path, rows)
    _asked(p, "s1", None)


def test_the_walk_stops_at_the_row_that_answers(tmp_path, monkeypatch):
    """300 older rows cost nothing when the newest row already answers.

    Counted by the blocks the probe looks at, because the store has no index
    leading with `session_id` so the scan happens either way — the parse is what an
    early exit buys, and an exit is what a row cap would have had to fake.
    """
    from agent_handoff.parsers import cherrystudio as cs

    rows = [
        ("s1", "user", _later(i * 1000), _payload("user", [_text(f"旧话 {i}")]))
        for i in range(300)
    ]
    rows.append(("s1", "assistant", _later(999_000), _payload("assistant", [_text("在。")])))
    p = _store(tmp_path, rows)
    seen: list[str] = []
    real = cs._block_turn

    def spy(parser, role, block):
        seen.append(str(block.get("type")))
        return real(parser, role, block)

    monkeypatch.setattr(cs, "_block_turn", spy)
    assert p.peek_needs_reply("s1") is False
    assert len(seen) == 1, f"the probe parsed {len(seen)} blocks to answer one row"


def test_the_probe_reads_the_message_table_once(tmp_path, statement_counter):
    """One statement whatever the session holds, and it does not open `sessions`."""
    rows = [("s1", "user", T0, _payload("user", [_text("问题")]))]
    rows += [
        ("s1", "assistant", _later(i * 1000), _payload("assistant", [_text(f"答 {i}")]))
        for i in range(300)
    ]
    p = _store(tmp_path, rows)
    with statement_counter(CherryStudioParser) as counter:
        assert p.peek_needs_reply("s1") is False
    assert counter.statements == 1, f"the probe issued {counter.statements} statements"


def test_a_warm_pass_asks_the_store_nothing(tmp_path, statement_counter):
    """The memo is keyed on the store version, so a 30-second rebuild re-derives 0."""
    p = _store(tmp_path, [("s1", "user", T0, _payload("user", [_text("问题")]))])
    assert p.peek_needs_reply("s1") is True
    with statement_counter(CherryStudioParser) as counter:
        assert CherryStudioParser(p.db_path).peek_needs_reply("s1") is True
    assert counter.statements == 0, f"a warm pass issued {counter.statements} statements"


def test_a_changed_store_re_derives_instead_of_repeating_itself(tmp_path):
    """A row written after the last answer changes the next one."""
    p = _store(tmp_path, [("s1", "user", T0, _payload("user", [_text("问题")]))])
    assert p.peek_needs_reply("s1") is True
    when = _later(2000)
    con = sqlite3.connect(p.db_path)
    con.execute(
        "INSERT INTO session_messages"
        " (session_id, role, content, created_at, updated_at) VALUES (?,?,?,?,?)",
        (
            "s1",
            "assistant",
            json.dumps(_payload("assistant", [_text("答")]), ensure_ascii=False),
            when,
            when,
        ),
    )
    con.commit()
    con.close()
    assert CherryStudioParser(p.db_path).peek_needs_reply("s1") is False
