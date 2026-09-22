"""Round 59: the "Needs input" probe for the QoderWake daemon's team chats.

Half of this entry's rows are transcripts in the shared qoder store, and Round 56
gave them a probe by delegating. The other half — the team-group conversations the
user addresses in the wake console — live in this parser's own SQLite tables, and
until now nothing asked them: measured on this machine, both conversations the
store held ended on an unanswered user turn, so the column was silent about
exactly the rows its own detail page could answer.

The predicate is `load()`'s, row for row: a message counts when its sender maps
to a role and its body carries text that survives cleaning and `is_noise`. The
store writes messages that do none of those (a member turn with an empty body, a
harness reminder), so "the last row" and "the last message" are different things
here too.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from agent_handoff.parsers import base as pb
from agent_handoff.parsers.qoderwake import QoderwakeCnParser, QoderwakeParser

T0 = "2026-07-26T14:44:41.635+08:00"


@pytest.fixture(autouse=True)
def _no_shared_answers():
    """Answers are memoised per store path; never across a test boundary."""
    pb._SQL_NEEDS_REPLY_CACHE.clear()
    yield
    pb._SQL_NEEDS_REPLY_CACHE.clear()

SCHEMA = """
CREATE TABLE team_group_conversations_v3 (
    id TEXT PRIMARY KEY, group_id TEXT, task_name TEXT, workspace_root TEXT,
    model_id TEXT, created_at TEXT, last_message_at TEXT);
CREATE TABLE team_group_messages_v3 (
    id TEXT PRIMARY KEY, uid TEXT, group_id TEXT, session_id TEXT,
    sender_type TEXT NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL);
"""


def _body(text):
    return json.dumps({"recordType": "member_conversation_message", "body": text})


def _store(tmp_path, conversations: dict[str, list[tuple]]):
    """Build a wake store. A message is (sender_type, created_at, body, kind)."""
    root = tmp_path / ".qoderwake-cn" / "data" / "store"
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / "qoderwake.sqlite")
    con.executescript(SCHEMA)
    for sid, messages in conversations.items():
        con.execute(
            "INSERT INTO team_group_conversations_v3 VALUES (?,?,?,?,?,?,?)",
            (sid, "g1", f"任务 {sid[-4:]}", "D:/demo", "glm-4.7", T0, messages[-1][1]),
        )
        for i, (sender, when, body, kind) in enumerate(messages):
            con.execute(
                "INSERT INTO team_group_messages_v3 VALUES (?,?,?,?,?,?,?,?)",
                (f"{sid}_msg_{i:04d}", "u1", "g1", sid, sender, kind, _body(body), when),
            )
    con.commit()
    con.close()
    return QoderwakeCnParser(root)


def _later(minutes: int, base: str = T0) -> str:
    """A timestamp `minutes` after the base, as the store writes it."""
    return base[:14] + f"{int(base[14:16]) + minutes:02d}" + base[16:]


def _page_ends_on(parser, sid: str) -> bool | None:
    raw = parser.load(sid)
    shown = [
        m
        for m in (raw.messages if raw else [])
        if m.role in ("user", "assistant") and (m.text or "").strip()
    ]
    return None if not shown else shown[-1].role == "user"


def test_a_team_chat_ending_on_a_user_turn_is_waiting(tmp_path):
    p = _store(
        tmp_path,
        {
            "team_group_session_a1": [
                ("user", T0, "我让你找ai绘画相关的工作", "initial_request"),
                ("member", _later(1), "整个 Plan 已经完成了。", "leader_message"),
                ("user", _later(2), "再找找别的", "followup"),
            ]
        },
    )
    assert p.peek_needs_reply("team_group_session_a1") is True
    assert _page_ends_on(p, "team_group_session_a1") is True


def test_a_answered_team_chat_says_so(tmp_path):
    p = _store(
        tmp_path,
        {
            "team_group_session_a1": [
                ("user", T0, "我让你找ai绘画相关的工作", "initial_request"),
                ("member", _later(1), "4 已完成任务：探索项目并汇总", "task_message"),
            ]
        },
    )
    assert p.peek_needs_reply("team_group_session_a1") is False
    assert _page_ends_on(p, "team_group_session_a1") is False


def test_a_message_that_reaches_nobody_is_not_an_ending(tmp_path):
    """A member turn with an empty body is a row without a message.

    The store writes one per tool phase; the page drops it, so the user's
    question is still the last thing a reader saw.
    """
    p = _store(
        tmp_path,
        {
            "team_group_session_a1": [
                ("user", T0, "还要改什么", "initial_request"),
                ("member", _later(1), "", "task_message"),
            ]
        },
    )
    assert p.peek_needs_reply("team_group_session_a1") is True
    assert _page_ends_on(p, "team_group_session_a1") is True


def test_injected_text_is_not_a_turn(tmp_path):
    """A reminder written with an attribute survives cleaning, so only the
    noise rule can drop it — and the page drops it, so the member's answer is
    still the last word."""
    p = _store(
        tmp_path,
        {
            "team_group_session_a1": [
                ("member", T0, "已经完成", "leader_message"),
                (
                    "user",
                    _later(1),
                    '<system-reminder kind="goal">继续</system-reminder>',
                    "followup",
                ),
            ]
        },
    )
    assert p.peek_needs_reply("team_group_session_a1") is False
    assert _page_ends_on(p, "team_group_session_a1") is False


def test_a_body_that_is_only_an_environment_wrapper_carries_no_turn(tmp_path):
    """The other half of the same rule: here it is cleaning that empties the row.

    `is_noise` does not reject an `<environment_context>` block — no human typed
    it, and `clean_text` is what says so. The turn behind it is a member's, so a
    probe that skips cleaning reports the conversation as answered; two rows of
    the same role would prove nothing here, which is why this one is shaped to
    change the answer.
    """
    p = _store(
        tmp_path,
        {
            "team_group_session_a1": [
                ("user", T0, "问题", "initial_request"),
                (
                    "member",
                    _later(1),
                    "<environment_context><cwd>D:/demo</cwd></environment_context>",
                    "task_message",
                ),
            ]
        },
    )
    assert p.peek_needs_reply("team_group_session_a1") is True
    assert _page_ends_on(p, "team_group_session_a1") is True


def test_a_sender_the_role_map_does_not_know_is_not_a_message(tmp_path):
    p = _store(
        tmp_path,
        {
            "team_group_session_a1": [
                ("user", T0, "问题", "initial_request"),
                ("system", _later(1), "成员已加入", "member_joined"),
            ]
        },
    )
    assert p.peek_needs_reply("team_group_session_a1") is True
    assert _page_ends_on(p, "team_group_session_a1") is True


def test_a_window_of_messages_that_carry_nothing_declines(tmp_path):
    """Past the window there is nothing to say, and the column must say so."""
    rows = [
        ("member", _later(i), "", "task_message") for i in range(QoderwakeParser._PROBE_ROWS + 10)
    ]
    p = _store(tmp_path, {"team_group_session_a1": rows})
    assert p.peek_needs_reply("team_group_session_a1") is None
    assert _page_ends_on(p, "team_group_session_a1") is None


def test_two_messages_in_one_instant_keep_the_pages_order(tmp_path):
    """`load()` reads them in (created_at, rowid) order, so the probe does too.

    The store stamps a burst of writes with one millisecond; the row written
    later is the one the transcript shows last, and that is the row that decides
    whether someone is still owed an answer.
    """
    for name, expect in (("user", True), ("member", False)):
        p = _store(
            tmp_path / name,
            {
                "team_group_session_a1": [
                    ("member" if name == "user" else "user", T0, "先说的", "task_message"),
                    (name, T0, "后写的", "followup"),
                ]
            },
        )
        sid = "team_group_session_a1"
        assert p.peek_needs_reply(sid) is expect
        assert _page_ends_on(p, sid) is expect


def test_a_body_carried_as_an_object_is_read_the_way_load_reads_it(tmp_path):
    """payload_json.body is a string in this store and an object in older writes."""
    p = _store(
        tmp_path,
        {"team_group_session_a1": [("user", T0, "问题", "initial_request")]},
    )
    con = sqlite3.connect(p._db())
    con.execute(
        "UPDATE team_group_messages_v3 SET payload_json=? WHERE session_id=?",
        (json.dumps({"body": {"text": "对象形式的提问"}}), "team_group_session_a1"),
    )
    con.commit()
    con.close()
    assert QoderwakeCnParser(p.root).peek_needs_reply("team_group_session_a1") is True
    assert _page_ends_on(QoderwakeCnParser(p.root), "team_group_session_a1") is True


def test_a_session_that_is_not_a_team_chat_is_asked_of_the_shared_store(
    tmp_path, statement_counter
):
    """The delegation Round 56 added must stay, and must not be paid for twice."""

    class Shared:
        def __init__(self):
            self.asked = []

        def peek_needs_reply(self, sid):
            self.asked.append(sid)
            return False

    p = _store(
        tmp_path,
        {"team_group_session_a1": [("user", T0, "问题", "initial_request")]},
    )
    p._shared = Shared()
    assert p.peek_needs_reply("team_group_session_a1") is True  # primes the id set
    with statement_counter(QoderwakeCnParser) as counter:
        assert p.peek_needs_reply("qs_1234") is False
    assert p._shared.asked == ["qs_1234"]
    assert counter.statements == 0, "a transcript row was asked of the team-chat table"


def test_the_team_chat_set_comes_from_the_conversation_table(tmp_path):
    """Not from how the id looks, and not from where the messages are.

    A conversation with no messages is still this daemon's (the probe answers
    from the message table and finds nothing to say); a stray message row whose
    conversation is absent belongs to neither store's listing, and the entry
    asks its shared store rather than inventing an answer for it.
    """
    p = _store(
        tmp_path,
        {"oddly_named_chat": [("user", T0, "问题", "initial_request")]},
    )
    con = sqlite3.connect(p._db())
    con.execute("DELETE FROM team_group_messages_v3")  # a conversation with no messages
    con.execute(
        "INSERT INTO team_group_messages_v3 VALUES (?,?,?,?,?,?,?,?)",
        ("stray_msg", "u1", "g1", "qs_orphan", "user", "followup", _body("没人认领"), T0),
    )
    con.commit()
    con.close()

    class Shared:
        def __init__(self):
            self.asked = []

        def peek_needs_reply(self, sid):
            self.asked.append(sid)
            return None

    fresh = QoderwakeCnParser(p.root)
    fresh._shared = Shared()
    pb._SQL_NEEDS_REPLY_CACHE.clear()
    assert fresh.peek_needs_reply("oddly_named_chat") is None
    assert fresh.peek_needs_reply("qs_orphan") is None
    assert fresh._shared.asked == ["qs_orphan"], "an orphan row was read as a team chat"
    assert _page_ends_on(fresh, "oddly_named_chat") is None


def test_a_warm_pass_asks_the_store_nothing(tmp_path, statement_counter):
    """One bounded read per rebuild for the conversation ids, none per row.

    The answers themselves are memoised against the store version (Round 58), so
    a poll over ten team chats that have not moved issues no message query at
    all; the single statement left is the conversation list, which is one query
    for the whole pass rather than one per row.
    """
    two = {
        "team_group_session_a1": [("user", T0, "问题", "initial_request")],
        "team_group_session_a2": [("member", T0, "回答", "task_message")],
    }
    p = _store(tmp_path, two)
    assert p.peek_needs_reply("team_group_session_a1") is True
    assert p.peek_needs_reply("team_group_session_a2") is False
    with statement_counter(QoderwakeCnParser) as counter:
        again = QoderwakeCnParser(p.root)
        assert again.peek_needs_reply("team_group_session_a1") is True
        assert again.peek_needs_reply("team_group_session_a2") is False
        rows_after_two_answers = counter.rows
        assert again.peek_needs_reply("team_group_session_a1") is True
    assert counter.statements == 1, f"a warm pass issued {counter.statements} statements"
    assert counter.rows == rows_after_two_answers, "the second answer re-read the messages"


def test_a_new_reply_changes_the_answer_without_a_restart(tmp_path):
    p = _store(
        tmp_path,
        {"team_group_session_a1": [("user", T0, "问题", "initial_request")]},
    )
    assert p.peek_needs_reply("team_group_session_a1") is True
    con = sqlite3.connect(p._db())
    con.execute(
        "INSERT INTO team_group_messages_v3 VALUES (?,?,?,?,?,?,?,?)",
        ("msg_zzz", "u1", "g1", "team_group_session_a1", "member", "leader_message",
         _body("已经处理完"), _later(30)),
    )
    con.commit()
    con.close()
    assert QoderwakeCnParser(p.root).peek_needs_reply("team_group_session_a1") is False


def test_an_unreadable_store_is_unknown_not_answered(tmp_path, monkeypatch):
    """A locked db declines; it does not report a conversation as finished."""
    p = _store(
        tmp_path,
        {"team_group_session_a1": [("user", T0, "问题", "initial_request")]},
    )
    assert p.peek_needs_reply("team_group_session_a1") is True  # primes the id set

    def boom(_self):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(QoderwakeCnParser, "_connect", boom)
    pb._SQL_NEEDS_REPLY_CACHE.clear()  # force the message query to be attempted
    assert p.peek_needs_reply("team_group_session_a1") is None
    # The same failure for a transcript row: no ids can be read, so the entry
    # asks its shared store and, having none, says nothing.
    assert p.peek_needs_reply("qs_1234") is None


def test_the_probe_agrees_with_the_page_over_every_shape(tmp_path):
    """One store, seven conversations: the column and the transcript match."""
    ask = ("user", T0, "问题", "initial_request")
    shapes = {
        "asked": [ask],
        "answered": [ask, ("member", _later(1), "答", "task_message")],
        "empty_tail": [ask, ("member", _later(1), "", "task_message")],
        "noise_tail": [
            ("member", T0, "已完成", "leader_message"),
            ("user", _later(1), "<system-reminder>x</system-reminder>", "followup"),
        ],
        "system_tail": [ask, ("system", _later(1), "广播", "member_joined")],
        "nothing": [("member", T0, "", "task_message")],
        "two_users": [ask, ("user", _later(1), "第二问", "followup")],
    }
    p = _store(tmp_path, {f"team_group_session_{k}": v for k, v in shapes.items()})
    for k in shapes:
        sid = f"team_group_session_{k}"
        page = _page_ends_on(p, sid)
        probe = p.peek_needs_reply(sid)
        assert probe == page, f"{k}: probe={probe} page={page}"


def test_the_other_wake_edition_shares_the_probe(tmp_path):
    """QoderwakeParser (international) is the same code path under .qoder."""
    root = tmp_path / ".qoderwake" / "data" / "store"
    root.mkdir(parents=True)
    con = sqlite3.connect(root / "qoderwake.sqlite")
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO team_group_conversations_v3 VALUES (?,?,?,?,?,?,?)",
        ("team_group_session_b1", "g", "t", "D:/demo", "m", T0, T0),
    )
    con.execute(
        "INSERT INTO team_group_messages_v3 VALUES (?,?,?,?,?,?,?,?)",
        ("msg_1", "u", "g", "team_group_session_b1", "user", "initial_request", _body("问题"), T0),
    )
    con.commit()
    con.close()
    p = QoderwakeParser(root)
    assert p.peek_needs_reply("team_group_session_b1") is True
