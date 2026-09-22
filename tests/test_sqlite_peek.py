"""Round 58: the "Needs input" probes for the two SQLite stores.

Both stores write a `message` row for every model call, including the calls that
produce nothing a reader can see — a bare tool call, a reasoning-only turn. So
the newest row is an assistant row for **every** session on the machine this was
measured on (458 of 458 zcode, 222 of 222 opencode), and a probe that asks the
table "`SELECT … ORDER BY … LIMIT 1`" answers "not waiting" for all of them. The
question the column asks is about the newest row that *reaches the page*, and
these cases pin that predicate: each shape is asserted against `load()` as well
as by hand, because the two must not drift.
"""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

from agent_handoff.parsers import base as pb
from agent_handoff.parsers.opencode import OpenCodeParser
from agent_handoff.parsers.zcode import ZcodeParser

T0 = 1_756_500_000_000


@pytest.fixture(autouse=True)
def _no_shared_answers():
    """Answers are memoised per store path; never across a test boundary."""
    pb._SQL_NEEDS_REPLY_CACHE.clear()
    yield
    pb._SQL_NEEDS_REPLY_CACHE.clear()


Z_SCHEMA = """
CREATE TABLE session (id TEXT, project_id TEXT, title TEXT, directory TEXT,
    time_created INTEGER, time_updated INTEGER, parent_id TEXT,
    task_type TEXT, title_source TEXT, permission TEXT);
CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER,
    data TEXT, sequence INTEGER);
CREATE TABLE part (id TEXT, message_id TEXT, session_id TEXT,
    data TEXT, sequence INTEGER);
CREATE TABLE todo (session_id TEXT, content TEXT, status TEXT, priority TEXT,
    position INTEGER);
"""

OC_SCHEMA = """
CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, directory TEXT,
    parent_id TEXT, agent TEXT, model TEXT, tokens_input INTEGER,
    tokens_output INTEGER, tokens_reasoning INTEGER, tokens_cache_read INTEGER,
    tokens_cache_write INTEGER, cost REAL, permission TEXT,
    time_compacting INTEGER, version TEXT);
CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER,
    data TEXT);
CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
    time_created INTEGER, data TEXT);
CREATE TABLE todo (session_id TEXT, content TEXT, status TEXT, priority TEXT,
    position INTEGER);
"""


def _text(t: str) -> dict:
    return {"type": "text", "text": t}


def _tool(name: str, **extra) -> dict:
    return {"type": "tool", "tool": name, "state": extra.get("state") or {}}


def _zcode(tmp_path, rows_by_session: dict[str, list[tuple]]) -> ZcodeParser:
    """Build a zcode store. A row is (role, at_ms, parts, sequence|None)."""
    db = tmp_path / "db.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(Z_SCHEMA)
    for sid, rows in rows_by_session.items():
        times = [r[1] for r in rows]
        con.execute(
            "INSERT INTO session (id, title, directory, time_created, time_updated)"
            " VALUES (?,?,?,?,?)",
            (sid, sid, "D:/demo", min(times), max(times)),
        )
        for order, row in enumerate(rows):
            role, at, parts = row[0], row[1], row[2]
            seq = row[3] if len(row) > 3 and row[3] is not None else order
            mid = f"{sid}_m{order}"
            con.execute(
                "INSERT INTO message VALUES (?,?,?,?,?)",
                (mid, sid, at, json.dumps({"role": role}), seq),
            )
            for pi, part in enumerate(parts):
                con.execute(
                    "INSERT INTO part VALUES (?,?,?,?,?)",
                    (f"{mid}_p{pi}", mid, sid, json.dumps(part), pi),
                )
    con.commit()
    con.close()
    return ZcodeParser(db)


def _opencode(tmp_path, rows_by_session: dict[str, list[tuple]]) -> OpenCodeParser:
    """Build an opencode store. A row is (role, at_ms, parts)."""
    root = tmp_path / "opencode"
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / "opencode.db")
    con.executescript(OC_SCHEMA)
    for sid, rows in rows_by_session.items():
        con.execute(
            "INSERT INTO session (id, title, directory) VALUES (?,?,?)",
            (sid, sid, "D:/demo"),
        )
        for order, (role, at, parts) in enumerate(rows):
            mid = f"{sid}_m{order}"
            con.execute(
                "INSERT INTO message VALUES (?,?,?,?)",
                (mid, sid, at, json.dumps({"role": role})),
            )
            for pi, part in enumerate(parts):
                con.execute(
                    "INSERT INTO part VALUES (?,?,?,?,?)",
                    (f"{mid}_p{pi}", mid, sid, at + pi, json.dumps(part)),
                )
    con.commit()
    con.close()
    return OpenCodeParser(root)


def _page_ends_on(parser, sid: str) -> bool | None:
    """What the detail page says: the role of its last visible message."""
    raw = parser.load(sid)
    shown = [
        m for m in raw.messages if m.role in ("user", "assistant") and (m.text or "").strip()
    ]
    return None if not shown else shown[-1].role == "user"


# -- the trap both stores share -----------------------------------------------


def test_a_zcode_row_that_reaches_nobody_is_not_an_ending(tmp_path):
    """An assistant row with only a tool part sits after the user's question.

    The store has a row for it and the page does not, so the user is still
    waiting; reading the table instead of the transcript answers the opposite.
    """
    p = _zcode(
        tmp_path,
        {
            "s1": [
                ("user", T0, [_text("为什么编译不过")]),
                (
                    "assistant",
                    T0 + 1000,
                    [_tool("Bash", state={"input": {"command": "cargo build"}})],
                ),
            ]
        },
    )
    assert p.peek_needs_reply("s1") is True
    assert _page_ends_on(p, "s1") is True


def test_an_opencode_row_that_reaches_nobody_is_not_an_ending(tmp_path):
    p = _opencode(
        tmp_path,
        {
            "s1": [
                ("user", T0, [_text("跑一下测试")]),
                ("assistant", T0 + 1000, [_tool("bash")]),
                ("assistant", T0 + 2000, [{"type": "reasoning", "text": "thinking"}]),
            ]
        },
    )
    assert p.peek_needs_reply("s1") is True
    assert _page_ends_on(p, "s1") is True


def test_a_replied_session_says_so(tmp_path):
    p = _zcode(
        tmp_path,
        {
            "s1": [
                ("user", T0, [_text("为什么编译不过")]),
                ("assistant", T0 + 1000, [_text("缺一个 feature flag.")]),
            ]
        },
    )
    assert p.peek_needs_reply("s1") is False
    assert _page_ends_on(p, "s1") is False


# -- the predicate, piece by piece --------------------------------------------


def test_text_that_is_only_injected_context_is_not_a_turn(tmp_path):
    """Two ways a user row can hold no human words, and both must be seen.

    `clean_text` removes a bare `<system-reminder>…</system-reminder>` wrapper,
    which leaves nothing to count; one written with an attribute survives
    cleaning, and there it is `is_noise` that decides. A probe that leans on
    either one alone passes half the store and calls the other half a question.
    """
    for i, marker in enumerate(
        (
            "<system-reminder>goal: 持续优化软件</system-reminder>",
            '<system-reminder kind="goal">目标：持续优化软件</system-reminder>',
            "[Request interrupted by user]",
        )
    ):
        p = _zcode(
            tmp_path / f"case{i}",
            {"s1": [("assistant", T0, [_text("已完成。")]), ("user", T0 + 1000, [_text(marker)])]},
        )
        assert p.peek_needs_reply("s1") is False, marker
        assert _page_ends_on(p, "s1") is False, marker


def test_a_user_context_reminder_is_a_turn_that_still_needs_an_answer(tmp_path):
    """The other half of `is_noise`: user-context reminders stay on the page."""
    p = _zcode(
        tmp_path,
        {
            "s1": [
                ("assistant", T0, [_text("已完成。")]),
                (
                    "user",
                    T0 + 1000,
                    [_text('<system-reminder data-role="user-context">当前目录</system-reminder>')],
                ),
            ]
        },
    )
    assert p.peek_needs_reply("s1") is True
    assert _page_ends_on(p, "s1") is True


def test_a_timeline_line_counts_as_visible_text(tmp_path):
    """Goal-verification separators are rendered as transcript lines.

    The page shows them, so a session ending on one has been answered — a probe
    that only knows `text` parts calls it a pending question.
    """
    p = _zcode(
        tmp_path,
        {
            "s1": [
                ("user", T0, [_text("继续")]),
                (
                    "assistant",
                    T0 + 1000,
                    [
                        {
                            "type": "timeline",
                            "timelineType": "goal_verification",
                            "verification": {
                                "passed": False,
                                "nextAction": "目标未达成，继续修",
                            },
                        }
                    ],
                ),
            ]
        },
    )
    assert p.peek_needs_reply("s1") is False
    assert _page_ends_on(p, "s1") is False


def test_a_model_change_that_changed_nothing_shows_no_line(tmp_path):
    p = _zcode(
        tmp_path,
        {
            "s1": [
                ("user", T0, [_text("继续")]),
                (
                    "assistant",
                    T0 + 1000,
                    [
                        {
                            "type": "timeline",
                            "timelineType": "model_change",
                            "fromModel": {"modelID": "glm-4.7"},
                            "toModel": {"modelID": "glm-4.7"},
                        }
                    ],
                ),
            ]
        },
    )
    assert p.peek_needs_reply("s1") is True
    assert _page_ends_on(p, "s1") is True


def test_a_sub_agent_spawn_leaves_the_session_answered(tmp_path):
    """An `Agent` call becomes its own assistant message on the page.

    The row that carries it may hold no text at all, so a probe keyed on text
    parts walks past it and reports the previous user turn as still open — the
    opposite of what the product shows.
    """
    p = _zcode(
        tmp_path,
        {
            "s1": [
                ("user", T0, [_text("分派一个子代理去查")]),
                (
                    "assistant",
                    T0 + 1000,
                    [
                        _tool(
                            "Agent",
                            state={
                                "status": "running",
                                "input": {"description": "查构建日志", "prompt": "读日志"},
                            },
                        )
                    ],
                ),
            ]
        },
    )
    assert p.peek_needs_reply("s1") is False
    assert _page_ends_on(p, "s1") is False


def test_a_spawn_beats_the_text_on_its_own_row(tmp_path):
    """Same timestamp, two messages: the page's own order decides.

    `load()` sorts the main rows first and appends spawns after them, so with
    one timestamp it is the spawn — always assistant — that reads as last.
    """
    p = _zcode(
        tmp_path,
        {
            "s1": [
                ("user", T0, [_text("问题在哪")]),
                (
                    "assistant",
                    T0 + 1000,
                    [
                        _text("我先看一眼。"),
                        _tool(
                            "Agent",
                            state={"status": "running", "input": {"description": "查日志"}},
                        ),
                    ],
                ),
            ]
        },
    )
    assert p.peek_needs_reply("s1") is False
    assert _page_ends_on(p, "s1") is False


def test_a_spawn_on_an_earlier_row_still_beats_a_later_user_row(tmp_path):
    """The tie-break is the message's position in the page, not the read order.

    Two rows stamped the same instant, the user one written later: reading
    newest-first meets the user row first, and taking "the first of the tied"
    would report a question the transcript has already answered with a spawn.
    """
    p = _zcode(
        tmp_path,
        {
            "s1": [
                (
                    "assistant",
                    T0,
                    [
                        _tool(
                            "Agent",
                            state={"status": "running", "input": {"description": "查日志"}},
                        )
                    ],
                    0,
                ),
                ("user", T0, [_text("那我再看一眼")], 1),
            ]
        },
    )
    assert p.peek_needs_reply("s1") is False
    assert _page_ends_on(p, "s1") is False


def test_a_row_of_another_role_is_not_in_the_transcript(tmp_path):
    p = _zcode(
        tmp_path,
        {
            "s1": [
                ("user", T0, [_text("看一下")]),
                ("system", T0 + 1000, [_text("已切换到 plan 模式")]),
            ]
        },
    )
    assert p.peek_needs_reply("s1") is True
    assert _page_ends_on(p, "s1") is True


# -- the window ---------------------------------------------------------------


def test_a_session_with_no_visible_turn_is_unknown_not_answered(tmp_path):
    """Past the window there is nothing to say, and the column must say so."""
    rows = [
        ("assistant", T0 + i * 1000, [_tool("Bash")])
        for i in range(ZcodeParser._PROBE_ROWS + 10)
    ]
    p = _zcode(tmp_path, {"s1": rows})
    assert p.peek_needs_reply("s1") is None
    assert _page_ends_on(p, "s1") is None


def test_the_window_is_walked_in_the_order_the_page_sorts_by(tmp_path):
    """Sequence order and time order are not the same thing.

    A store that re-appends a resumed turn keeps the older row's sequence while
    stamping it newest: reading the newest `sequence` misses the turn that is
    last on the page, and answers for a conversation that has moved on.
    """
    filler = [
        ("assistant", T0 - (i + 1) * 1000, [_text(f"较早的回答 {i}")])
        for i in range(ZcodeParser._PROBE_ROWS + 5)
    ]
    # The user's newest turn carries the LOWEST sequence, as a re-inserted row
    # would; only its timestamp says it is last.
    p = _zcode(tmp_path, {"s1": [*filler, ("user", T0 + 9_999_999, [_text("最新的问题")], 0)]})
    assert p.peek_needs_reply("s1") is True
    assert _page_ends_on(p, "s1") is True


def test_the_window_depth_is_not_a_function_of_session_length(tmp_path):
    """A 300-row session costs the same bounded read as a 3-row one."""
    long = [("assistant", T0 + i * 1000, [_text(f"回答 {i}")]) for i in range(300)]
    p = _zcode(tmp_path, {"short": [("user", T0, [_text("问题")])], "long": long})
    with _statements(ZcodeParser) as counter:
        counter.reset()
        p.peek_needs_reply("short")
        short = counter.total
        counter.reset()
        p.peek_needs_reply("long")
        length = counter.total
    assert (short, length) == (2, 2), "the probe's cost grew with the transcript"


class _statements:
    """Count the SQL statements a probe sends, for the cost assertions below."""

    def __init__(self, cls):
        self.cls = cls
        self.total = 0
        self._real = cls._connect

    def __enter__(self):
        outer = self

        class Prox:
            def __init__(self, con):
                self._con = con

            def execute(self, sql, *a, **kw):
                outer.total += 1
                return self._con.execute(sql, *a, **kw)

            def __enter__(self):
                self._con.__enter__()
                return self

            def __exit__(self, *exc):
                return self._con.__exit__(*exc)

            def __getattr__(self, name):
                return getattr(self._con, name)

        def connect(self):
            return Prox(outer._real(self))

        self.cls._connect = connect
        return self

    def __exit__(self, *exc):
        self.cls._connect = self._real
        return False

    def reset(self):
        self.total = 0


# -- the memo ---------------------------------------------------------------


def test_a_warm_pass_asks_the_store_nothing(tmp_path):
    """30-second rebuilds against a store that has not moved re-derive nothing.

    A SQLite store is one file for every conversation, so re-running the probe
    per row means re-querying rows nobody changed.
    """
    p = _zcode(
        tmp_path,
        {"s1": [("user", T0, [_text("还在等吗")]), ("assistant", T0 + 1000, [_text("在。")])]},
    )
    assert p.peek_needs_reply("s1") is False
    with _statements(ZcodeParser) as counter:
        assert ZcodeParser(p.db_path).peek_needs_reply("s1") is False
    assert counter.total == 0, f"a warm pass issued {counter.total} statements"


def test_a_changed_store_re_derives_instead_of_repeating_itself(tmp_path):
    """The memo is keyed on the store version, not on the session id alone."""
    p = _zcode(
        tmp_path,
        {"s1": [("user", T0, [_text("问题")]), ("assistant", T0 + 1000, [_text("答")])]},
    )
    assert p.peek_needs_reply("s1") is False
    con = sqlite3.connect(p.db_path)
    con.execute(
        "INSERT INTO message VALUES ('s1_m9','s1',?,?,9)",
        (T0 + 9000, json.dumps({"role": "user"})),
    )
    con.execute(
        "INSERT INTO part VALUES ('s1_m9_p0','s1_m9','s1',?,0)",
        (json.dumps(_text("新的问题")),),
    )
    con.commit()
    con.close()
    assert ZcodeParser(p.db_path).peek_needs_reply("s1") is True


def test_the_wal_sidecar_is_part_of_the_version(tmp_path):
    """A commit that only reaches the WAL still counts as new content.

    Both stores run in WAL mode, so the db file is the least lively of the two:
    a conversation can move several turns while it sits untouched. A version
    key that reads only the db would keep serving the answer from before them.
    """
    p = _zcode(
        tmp_path,
        {"s1": [("user", T0, [_text("问题")]), ("assistant", T0 + 1000, [_text("答")])]},
    )
    assert p.peek_needs_reply("s1") is False
    with _statements(ZcodeParser) as counter:
        assert ZcodeParser(p.db_path).peek_needs_reply("s1") is False
    assert counter.total == 0
    (tmp_path / "db.sqlite-wal").write_bytes(b"\x00" * 64)
    with _statements(ZcodeParser) as after:
        assert ZcodeParser(p.db_path).peek_needs_reply("s1") is False
    assert after.total > 0, "a WAL the version key cannot see is a store that never changes"
    assert pb.db_version(p.db_path) != pb.db_version(tmp_path / "missing.sqlite")


def test_a_commit_that_grows_nothing_still_moves_the_version(tmp_path):
    """SQLite's own change counter is in the key, because stat alone was not enough.

    Measured while writing this: a store whose rows were rewritten in place kept
    the same file length and, inside one clock tick, the same mtime — and the
    probe memo answered from before the rewrite. The two copies here are made to
    differ in exactly the 4 bytes of the header counter, with the same size and
    the same recorded mtime, so `stat` cannot separate them by construction: an
    assertion about the counter and nothing else.
    """
    head = bytearray(b"\x53\x4c\x49\x54\x45" + b"\x00" * 64)
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    a.write_bytes(bytes(head))
    bumped = bytearray(head)
    bumped[24:28] = (1).to_bytes(4, "big")
    b.write_bytes(bytes(bumped))
    stamp = 1_700_000_000_000_000_000
    for path in (a, b):
        os.utime(path, ns=(stamp, stamp))
    assert a.stat().st_size == b.stat().st_size
    assert a.stat().st_mtime_ns == b.stat().st_mtime_ns
    assert a.read_bytes()[:24] == b.read_bytes()[:24] and a.read_bytes()[28:] == b.read_bytes()[28:]
    assert pb.db_version(a) != pb.db_version(b)


def test_a_wal_that_restarted_moves_the_version_without_growing(tmp_path):
    """The WAL header's checkpoint sequence and salt are read, not just its size."""
    db = tmp_path / "db.sqlite"
    db.write_bytes(b"x")
    wal = tmp_path / "db.sqlite-wal"
    first = bytearray(b"\x00" * 64)
    wal.write_bytes(bytes(first))
    second = bytearray(first)
    second[12:20] = (7).to_bytes(4, "big") + (3).to_bytes(4, "big")
    stamp = 1_700_000_000_000_000_000
    os.utime(wal, ns=(stamp, stamp))
    before = pb.db_version(db)
    os.utime(db, ns=(stamp, stamp))
    wal.write_bytes(bytes(second))
    os.utime(wal, ns=(stamp, stamp))
    assert wal.stat().st_size == 64 and db.stat().st_size == 1
    assert before != pb.db_version(db)


def test_the_memo_key_carries_the_store_as_well_as_the_session(tmp_path):
    """Two stores, one session id: the answer belongs to the store, not the id.

    Session ids collide across the dialects this cockpit reads, and the memo is
    keyed by store path for exactly that reason.
    """
    version = (1, 2)
    assert pb.probe_memo("store-a", "s1", version, lambda: True) is True
    assert pb.probe_memo("store-b", "s1", version, lambda: False) is False
    assert pb.probe_memo("store-a", "s1", version, lambda: True) is True
    # An answer is not derived twice for one version, and is re-derived for the
    # next one — the two halves of what the key is for.
    calls = []
    assert pb.probe_memo("store-a", "s2", version, lambda: calls.append(1) or True) is True
    assert pb.probe_memo("store-a", "s2", version, lambda: calls.append(1) or False) is True
    assert len(calls) == 1
    assert pb.probe_memo("store-a", "s2", (9, 9), lambda: calls.append(1) or False) is False
    assert len(calls) == 2


def test_two_stores_sharing_a_session_id_do_not_share_an_answer(tmp_path):
    a = _zcode(tmp_path / "a", {"s1": [("user", T0, [_text("等回答")])]})
    b = _zcode(tmp_path / "b", {"s1": [("assistant", T0, [_text("已回答")])]})
    assert a.peek_needs_reply("s1") is True
    assert b.peek_needs_reply("s1") is False


def test_a_probe_that_cannot_read_the_store_declines(tmp_path, monkeypatch):
    """A locked or half-written db is unknown, never 'not waiting'."""
    p = _zcode(
        tmp_path,
        {"s1": [("user", T0, [_text("问题")]), ("assistant", T0 + 1000, [_text("回答")])]},
    )
    assert p.peek_needs_reply("s1") is False

    def boom(_self):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ZcodeParser, "_connect", boom)
    # A warm row keeps its last answer — the version it was read at has not
    # changed, so nothing has to be read.
    assert ZcodeParser(p.db_path).peek_needs_reply("s1") is False
    # A cold pass that cannot open the store says nothing. "Unknown" is a state
    # the cockpit renders; "not waiting" would close a conversation that is open.
    pb._SQL_NEEDS_REPLY_CACHE.clear()
    assert ZcodeParser(p.db_path).peek_needs_reply("s1") is None


def test_both_probes_agree_with_the_page_over_every_shape(tmp_path):
    """One store, eight shapes, both stores: the two questions match."""
    shapes = {
        "asked": [("user", T0, [_text("问题")])],
        "answered": [("user", T0, [_text("问题")]), ("assistant", T0 + 1000, [_text("答")])],
        "tool_tail": [
            ("user", T0, [_text("问题")]),
            ("assistant", T0 + 1000, [_tool("Read")]),
        ],
        "empty": [("assistant", T0, [_tool("Read")])],
        "only_reminder": [("user", T0, [_text("<system-reminder>goal</system-reminder>")])],
        "two_users": [
            ("user", T0, [_text("第一个")]),
            ("assistant", T0 + 1000, [_text("回答")]),
            ("user", T0 + 2000, [_text("第二个")]),
        ],
        "same_second": [
            ("user", T0, [_text("同秒问题")]),
            ("assistant", T0, [_text("同秒回答")]),
        ],
        "textless_then_user": [
            ("assistant", T0, [_tool("Write")]),
            ("user", T0 + 500, [_text("还要改")]),
        ],
    }
    for parser in (_zcode(tmp_path / "z", shapes), _opencode(tmp_path / "o", shapes)):
        for sid in shapes:
            page = _page_ends_on(parser, sid)
            probe = parser.peek_needs_reply(sid)
            assert probe == page, f"{parser.cli}/{sid}: probe={probe} page={page}"
