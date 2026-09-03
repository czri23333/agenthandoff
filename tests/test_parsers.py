"""Parser tests against synthetic stores (see CONTRIBUTING: happy path + corrupt input)."""

from __future__ import annotations

from pathlib import Path

from agent_handoff.parsers.codex import CodexParser
from agent_handoff.parsers.dsh import DshParser
from agent_handoff.parsers.jsonl_family import (
    ClaudeCodeParser,
    CodebuddyParser,
    QodercnIdeParser,
    QoderworkCnParser,
    QoderworkParser,
    QwenworkParser,
)
from agent_handoff.parsers.zcode import ZcodeParser


def test_zcode_happy(zcode_store):
    p = ZcodeParser(zcode_store / "zcode" / "cli" / "db" / "db.sqlite")
    metas = p.list_sessions()
    assert [m.session_id for m in metas] == ["sess_a"]
    assert metas[0].title == "Fix login loop"
    assert metas[0].task_type == "interactive"
    assert metas[0].title_source == "first_input"
    assert metas[0].permission == "yolo"
    raw = p.load("sess_a")
    assert raw is not None
    roles = [(m.role, m.text) for m in raw.messages]
    assert ("user", "Fix the login redirect loop. 不要引入新的依赖") in roles
    assert raw.files_touched["src/auth.ts"] == 1
    assert raw.tool_counts["Edit"] == 1
    assert [t.content for t in raw.todos if t.status == "in_progress"] == ["patch middleware"]
    assert raw.meta.tokens_in == 30 and raw.meta.tokens_out == 15  # summed across turns
    assert raw.meta.task_type == "interactive"
    assert raw.meta.attachments == []


def test_zcode_attachments_and_goal_verdict(zcode_store):
    """file parts land in attachments; goal_verification folds its verdict in."""
    import json
    import sqlite3

    db = zcode_store / "zcode" / "cli" / "db" / "db.sqlite"
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO part VALUES ('m1file','m1','sess_a',?,4)",
        (
            json.dumps(
                {
                    "type": "file",
                    "filename": "spec.html",
                    "url": "C:/dl/spec.html",
                    "source": {"path": "C:/dl/spec.html"},
                }
            ),
        ),
    )
    con.execute(
        "INSERT INTO part VALUES ('m2goal','m2','sess_a',?,5)",
        (
            json.dumps(
                {
                    "type": "timeline",
                    "timelineType": "goal_verification",
                    "verification": {"passed": True, "nextAction": "Ship it"},
                }
            ),
        ),
    )
    con.commit()
    con.close()
    p = ZcodeParser(db)
    raw = p.load("sess_a")
    assert raw is not None
    assert raw.meta.attachments == ["C:/dl/spec.html"]
    assert any("[目标核验 ✓] Ship it" in m.text for m in raw.messages)


def test_zcode_missing_session(zcode_store):
    p = ZcodeParser(zcode_store / "zcode" / "cli" / "db" / "db.sqlite")
    assert p.load("nope") is None


def test_claude_happy_and_corrupt(claude_store):
    p = ClaudeCodeParser(claude_store / "claude")
    metas = p.list_sessions()
    assert len(metas) == 1
    assert metas[0].session_id == "abc123"
    assert metas[0].title == "Demo session"  # summary line wins
    raw = p.load("abc123")
    assert raw is not None
    assert raw.messages[0].role == "user"
    assert raw.messages[0].text == "hello, do the thing"
    assert raw.files_touched["src/main.py"] == 1
    assert [t.status for t in raw.todos] == ["completed", "in_progress"]


def test_codebuddy_dialect(codebuddy_store):
    p = CodebuddyParser(codebuddy_store / "codebuddy")
    raw = p.load("def456")
    assert raw is not None
    assert raw.messages[0].text == "codebuddy turn"
    assert raw.messages[1].role == "assistant"


def test_qoder_and_qwen_share_dialect(tmp_path):
    for cls, dirname, text in [
        (QoderworkParser, ".qoderwork", "qoder ask"),
        (QwenworkParser, ".qwenworkcn", "qwen ask"),
    ]:
        root = tmp_path / dirname / "projects" / "C--x"
        (root.parent.parent / dirname).mkdir(parents=True, exist_ok=True)
        import json

        root.mkdir(parents=True)
        rows = [
            {"type": "runtime-config", "sessionId": "s1", "timestamp": 1},
            {
                "type": "user",
                "timestamp": "2026-08-30T10:00:00Z",
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
            },
        ]
        with open(root / "s1.jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        p = cls(tmp_path / dirname)
        raw = p.load("s1")
        assert raw is not None and raw.messages[0].text == text


def test_qoder_tool_loop_hidden_but_loadable(tmp_path):
    """A transcript holding zero real text is an internal tool loop (a spawned
    browser/automation sub-agent run), not a conversation: the product never
    lists it, so neither do we. It must still load by id for debugging.

    Regression: the filter shipped without coverage, and the cockpit listed
    ~90 tool-loop sessions as if they were chats (the user saw 5 in the IDE).
    """
    import json

    root = tmp_path / ".qoder-cn" / "projects" / "C--x"
    root.mkdir(parents=True)
    turn = [
        {"type": "runtime-config", "sessionId": "aaa111", "timestamp": 1},
        {
            "type": "user",
            "timestamp": "2026-08-30T10:00:00Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "fix the login loop"}],
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-08-30T10:00:01Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "found it"}]},
        },
    ]
    with open(root / "aaa111.jsonl", "w", encoding="utf-8") as fh:
        for r in turn:
            fh.write(json.dumps(r) + "\n")

    # Zero real text: every user row is a tool_result echo, every assistant row
    # a tool_use - the exact shape qoder writes for a browser/automation run.
    loop = [
        {"type": "runtime-config", "sessionId": "bbb222", "timestamp": 1},
        {
            "type": "user",
            "timestamp": "2026-08-30T10:01:00Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "content": "browser said no",
                        "is_error": False,
                        "tool_use_id": "t1",
                        "type": "tool_result",
                    }
                ],
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-08-30T10:01:01Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "id": "c1",
                        "input": {"url": "https://example.test"},
                        "name": "browser_open",
                        "type": "tool_use",
                    }
                ],
            },
        },
    ]
    with open(root / "bbb222.jsonl", "w", encoding="utf-8") as fh:
        for r in loop:
            fh.write(json.dumps(r) + "\n")

    p = QodercnIdeParser(tmp_path / ".qoder-cn")
    ids = [m.session_id for m in p.list_sessions()]
    assert ids == ["aaa111"], ids
    raw = p.load("bbb222")
    assert raw is not None  # hidden from the list, still loadable by id
    assert raw.messages == []  # and it is honestly empty: nothing to pretend


def test_qoder_shared_store_splits_families(tmp_path):
    """The qoder-cn store is shared by IDE chats, qoderwake workers and qoderwork
    workspaces. Each family must list only its own; wake/work transcripts
    belong to their CLI entries, and the IDE list stays one family.

    Regression: the cockpit listed 125 qodercn-ide sessions although the IDE
    UI shows 5; 90+ were tool loops (now hidden) and ~11 were wake/work.
    """
    import json

    def write_session(rootdir: Path, name: str, sid: str, text: str) -> None:
        rootdir.mkdir(parents=True, exist_ok=True)
        rows = [
            {"type": "runtime-config", "sessionId": sid, "timestamp": 1},
            {
                "type": "user",
                "timestamp": "2026-08-30T10:00:00Z",
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
            },
            {
                "type": "assistant",
                "timestamp": "2026-08-30T10:00:01Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
            },
        ]
        with open(rootdir / f"{name}.jsonl", "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")

    store = tmp_path / ".qoder-cn" / "projects"
    write_session(store / "D----x" / "transcript", "aaa111", "aaa111", "ide chat")
    write_session(
        store / "C--u--qoderwake-cn-data-team-groups-team-group-g1-workspace",
        "bbb222",
        "bbb222",
        "wake group ask",
    )
    write_session(store / "C--u--qoderworkcn-workspace-m1", "ccc333", "ccc333", "work ask")

    from agent_handoff.parsers.qoderwake import _WakeShared

    p_ide = QodercnIdeParser(tmp_path / ".qoder-cn")
    assert [m.session_id for m in p_ide.list_sessions()] == ["aaa111"]

    p_wake = _WakeShared(tmp_path / ".qoder-cn", "qoderwake-cn", "QoderCN", ".qoderwake-cn")
    assert [m.session_id for m in p_wake.list_sessions()] == ["bbb222"]

    p_work = QoderworkCnParser(tmp_path / ".qoderworkcn")
    assert [m.session_id for m in p_work.list_sessions()] == ["ccc333"]
    assert p_work.load("ccc333") is not None


def test_dsh_roll(dsh_store):
    p = DshParser(dsh_store / "dsh" / "sessions")
    assert p.codec_ok()
    metas = p.list_sessions()
    assert metas and metas[0].title == "dsh demo task"
    raw = p.load("11112222")
    assert raw is not None
    assert raw.messages[0].text == "dsh user ask"
    assert raw.messages[1].role == "assistant"
    # usage chunk must not become a text message
    assert len(raw.messages) == 2


def test_dsh_usage_sums_once_per_turn(dsh_store):
    """usage() sums turn-level usage rows, not fanned-out messages."""
    from agent_handoff.parsers.dsh import DshParser

    p = DshParser(dsh_store / "dsh" / "sessions")
    u = p.usage("11112222")
    assert u is not None
    assert u["totals"] == {"calls": 1, "tokens_in": 5, "tokens_out": 0}
    assert u["models"][0]["calls"] == 1
    assert p.usage("nope") is None


def test_codex_rollout(codex_store):
    p = CodexParser(codex_store / "codex" / "sessions")
    metas = p.list_sessions()
    assert len(metas) == 1 and metas[0].cwd == "D:/demo"
    raw = p.load("aaa")
    assert raw is not None
    texts = [m.text for m in raw.messages]
    assert "codex ask" in texts and "codex answer" in texts
    # developer role filtered
    assert "<app-context>" not in "".join(texts)


def test_account_config_count(tmp_path):
    from agent_handoff.locations import _count_account_configs

    root = tmp_path / ".qoderworkcn"
    models = root / ".models"
    (models / "019f4786-292e-70b9-b2e7-2427bbbee917").mkdir(parents=True)
    (models / "019f59cd-0c18-77aa-87be-77c90882e185").mkdir(parents=True)
    (models / "default").mkdir()
    assert _count_account_configs(root) == 2  # only uuid dirs count

    single = tmp_path / ".qoderwork"
    (single / ".models" / "019f3554-c9cc-4000-8000-000000000000").mkdir(parents=True)
    assert _count_account_configs(single) == 1


def test_cherrystudio_happy(cherrystudio_store):
    from agent_handoff.parsers.cherrystudio import CherryStudioParser

    p = CherryStudioParser(cherrystudio_store / "agents.db")
    metas = p.list_sessions()
    assert [m.session_id for m in metas] == ["sess_cs"]
    assert metas[0].title == "Demo chat"
    raw = p.load("sess_cs")
    assert raw is not None
    assert [(m.role, m.text) for m in raw.messages] == [
        ("user", "hello cherry"),
        ("assistant", "hi there"),
    ]
    assert p.raw_archive("sess_cs")[0]["path"] == "cherrystudio/sess_cs.records.jsonl"
    assert p.load("nope") is None


def test_cherrystudio_usage(cherrystudio_store):
    """usage() aggregates per-model tokens + TTFT from message rows."""
    import json as _json
    import sqlite3

    from agent_handoff.parsers.cherrystudio import CherryStudioParser

    db = cherrystudio_store / "agents.db"
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO session_messages VALUES ('r3','sess_cs','assistant',?,"
        " '2026-07-05T08:19:50.000Z')",
        (
            _json.dumps(
                {
                    "message": {
                        "role": "assistant",
                        "model": {"name": "glm-5.2"},
                        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                        "metrics": {"time_first_token_millsec": 2000},
                    },
                    "blocks": [{"type": "main_text", "content": "and more"}],
                }
            ),
        ),
    )
    con.commit()
    con.close()
    p = CherryStudioParser(db)
    u = p.usage("sess_cs")
    assert u is not None
    assert u["totals"] == {"calls": 1, "tokens_in": 100, "tokens_out": 50}
    assert u["models"][0]["model"] == "glm-5.2"
    assert u["models"][0]["avg_ttft_ms"] == 2000
    assert p.usage("nope") is None


def test_qoderapp_happy(qoderapp_store):
    from agent_handoff.parsers.qoderapp import (
        QoderworkAppParser,
        QoderworkCnAppParser,
        QwenworkAppParser,
    )

    for cls in (QoderworkAppParser, QoderworkCnAppParser, QwenworkAppParser):
        p = cls(qoderapp_store / "agents.db")
        metas = p.list_sessions()
        assert [m.session_id for m in metas] == ["chat1"]
        raw = p.load("chat1")
        assert raw is not None
        assert raw.messages[0].text == "hello task"
        assert any(m.text.startswith("[思考]") for m in raw.messages)
        assert raw.tool_counts["Read"] == 1
        assert raw.files_touched["src/a.ts"] == 1
        assert p.raw_archive("chat1")[0]["path"] == "qoderapp/chat1.records.jsonl"


def test_qoderwork_execution_anchors(tmp_path):
    import json as _json

    state = tmp_path / ".qodersec" / "state" / "proj"
    state.mkdir(parents=True)
    (state / "task-1.session.execution.json").write_text(
        _json.dumps({"touched_paths": ["src/a.ts", "src/b.ts"]}), encoding="utf-8"
    )
    (state / "task-2.session.execution.json.lock").write_text("locked", encoding="utf-8")
    (state / "task-3.session.execution.json").write_text("{broken", encoding="utf-8")

    root = tmp_path / ".qoderwork" / "projects" / "C--x"
    root.mkdir(parents=True)
    (root / "sess1.jsonl").write_text(
        _json.dumps(
            {
                "type": "user",
                "sessionId": "sess1",
                "cwd": "D:/demo",
                "timestamp": "2026-08-30T10:00:00Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    p = QoderworkParser(tmp_path / ".qoderwork")
    anchors = p.execution_anchors(state_dir=tmp_path / ".qodersec" / "state")
    assert anchors == {"src/a.ts": 1, "src/b.ts": 1}
