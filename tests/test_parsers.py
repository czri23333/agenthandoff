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


def test_codebuddy_job_state(tmp_path):
    """jobs/<short>/state.json state surfaces via peek_status (working/idle)."""
    import json

    from agent_handoff.parsers.jsonl_family import CodebuddyParser

    root = tmp_path / ".codebuddy" / "projects" / "d--demo"
    root.mkdir(parents=True)
    (root / "aaa111.jsonl").write_text(
        json.dumps(
            {
                "type": "message",
                "role": "user",
                "sessionId": "aaa111",
                "cwd": "D:/demo",
                "timestamp": 1756548000000,
                "content": [{"type": "input_text", "text": "hi"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    jobs = tmp_path / ".codebuddy" / "jobs" / "a1b2c3"
    jobs.mkdir(parents=True)
    (jobs / "state.json").write_text(
        json.dumps({"sessionId": "aaa111", "name": "Agent", "state": "working"}),
        encoding="utf-8",
    )
    p = CodebuddyParser(tmp_path / ".codebuddy")
    # The job state is read...
    assert p._store_status_word("aaa111") == "working"
    # ...but "working" describes a live job, not an ending, so the end-state
    # field refuses to borrow it: a badge the detail page would not claim is a
    # contradiction waiting to be rendered (spec Round 39, scripts/probe_audit.py).
    assert p.peek_status("aaa111") is None
    assert p._proven_interruption("aaa111") is None
    assert p.peek_status("nope") is None
    (jobs / "state.json").write_text(
        json.dumps({"sessionId": "aaa111", "name": "Agent", "state": "failed"}),
        encoding="utf-8",
    )
    p = CodebuddyParser(tmp_path / ".codebuddy")
    assert p.peek_status("aaa111") == "error"
    assert p._proven_interruption("aaa111").kind == "error"


def test_an_unseen_row_shape_is_reported_not_swallowed(tmp_path):
    """The store writing something new must not look like nothing happened.

    Rows carrying no role fall out of the parse loop. For the bookkeeping types
    the store actually writes (active-leaf, runtime-config, ...) that is by
    design and stays quiet; for a shape nobody has seen it has to leave a
    visible fact, and the bytes still have to be retrievable.
    """
    import json

    root = tmp_path / ".codebuddy" / "projects" / "p"
    root.mkdir(parents=True)
    (root / "aaa111.jsonl").write_text(
        "".join(
            json.dumps(r) + "\n"
            for r in [
                {"type": "session_meta", "sessionId": "aaa111", "cwd": "D:/demo"},
                {"type": "active-leaf", "sessionId": "aaa111", "leaf": 3},
                {
                    "type": "quantum_flux_report",
                    "sessionId": "aaa111",
                    "payload": {"volume": 42},
                },
                {
                    "type": "message",
                    "sessionId": "aaa111",
                    "cwd": "D:/demo",
                    "timestamp": 1756548000000,
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hello there friend"}],
                },
            ]
        ),
        encoding="utf-8",
    )
    p = CodebuddyParser(tmp_path / ".codebuddy")
    raw = p.load("aaa111")
    assert raw is not None
    assert "unhandled_row:quantum_flux_report=1" in raw.meta.notes
    assert not [n for n in raw.meta.notes if n.startswith("unhandled_row:active-leaf")]
    assert [m.text for m in raw.messages] == ["hello there friend"]
    # Retained and exportable: raw_archive hands out the file byte-faithfully,
    # so an unread row is a row not yet interpreted, never a row that is gone.
    archive = p.raw_archive("aaa111")
    assert archive and "quantum_flux_report" in archive[0]["text"]


def test_attachment_is_reported_by_its_own_kind_not_as_one_blob(tmp_path):
    """`attachment` is 12 different things, so one label for it hides the point.

    Nine of the kinds this machine writes are injected context (skills, hooks,
    reminders) and name nothing; three name a file the session touched. Listing
    them all as "unread attachment" would drown the three that matter and let a
    brand-new kind slip past as noise.
    """
    import json

    root = tmp_path / ".codebuddy" / "projects" / "p"
    root.mkdir(parents=True)
    (root / "aaa111.jsonl").write_text(
        "".join(
            json.dumps(r) + "\n"
            for r in [
                {"type": "session_meta", "sessionId": "aaa111", "cwd": "D:/demo"},
                {"type": "attachment", "sessionId": "aaa111", "attachment": {
                    "type": "skill_listing", "content": "- a skill"}},
                {"type": "attachment", "sessionId": "aaa111", "attachment": {
                    "type": "file", "filename": "D:/demo/notes.md", "content": "x"}},
                {"type": "attachment", "sessionId": "aaa111", "attachment": {
                    "type": "post_compact_restored_files",
                    "files": json.dumps([{"filePath": "D:/demo/restored.rs"}])}},
                {"type": "attachment", "sessionId": "aaa111", "attachment": {
                    "type": "plan_mode", "planFilePath": "D:/demo/plan.md"}},
                {"type": "attachment", "sessionId": "aaa111", "attachment": {
                    "type": "holographic_diff", "whatever": 1}},
                {
                    "type": "message",
                    "sessionId": "aaa111",
                    "cwd": "D:/demo",
                    "timestamp": 1756548000000,
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hello there friend"}],
                },
            ]
        ),
        encoding="utf-8",
    )
    raw = CodebuddyParser(tmp_path / ".codebuddy").load("aaa111")
    assert raw is not None
    notes = raw.meta.notes
    # injected context: known, silent
    assert not [n for n in notes if n.startswith("unhandled_row:attachment/skill_listing")]
    # file-bearing kinds: read, so their paths are in the record. The plan_*
    # kinds were only found because attachments are reported per sub-type.
    files = dict(raw.files_touched)
    assert files["D:/demo/notes.md"] == 1
    assert files["D:/demo/restored.rs"] == 1
    assert files["D:/demo/plan.md"] == 1
    # a kind nobody has seen: reported, by its own name
    assert "unhandled_row:attachment/holographic_diff=1" in notes


def test_the_shapes_a_full_store_sweep_inherited_are_each_classified(tmp_path):
    """Round 48: the 131-session sample had never met four sub-types.

    Three of them say nothing the product models (an empty mode marker, a hook
    printing at the user, a skill file the harness loaded), so they join the
    excused list. The fourth carries `planFilePath` and was simply missed while
    its three siblings were read, so its plan must land in the touched files.
    The unseen kind at the end is the point of the test: widening an excuse list
    must not be able to quiet a shape nobody has actually seen.
    """
    import json

    root = tmp_path / ".codebuddy" / "projects" / "p"
    root.mkdir(parents=True)
    (root / "bbb222.jsonl").write_text(
        "".join(
            json.dumps(r) + "\n"
            for r in [
                {"type": "session_meta", "sessionId": "bbb222", "cwd": "D:/demo"},
                {"type": "attachment", "sessionId": "bbb222", "attachment": {
                    "type": "plan_mode_reentry", "planFilePath": "D:/demo/reentry.md"}},
                {"type": "attachment", "sessionId": "bbb222", "attachment": {
                    "type": "auto_mode_exit"}},
                {"type": "attachment", "sessionId": "bbb222", "attachment": {
                    "type": "hook_system_message", "content": "a scanner said hi",
                    "hookName": "PostToolUse:Write"}},
                {"type": "attachment", "sessionId": "bbb222", "attachment": {
                    "type": "invoked_skills", "skills": [
                        {"name": "quality-gate",
                         "path": "D:/demo/.qoder/skills/quality-gate/SKILL.md",
                         "content": "# quality-gate"}]}},
                {"type": "attachment", "sessionId": "bbb222", "attachment": {
                    "type": "temporal_orbit_note", "whatever": 1}},
                {
                    "type": "message",
                    "sessionId": "bbb222",
                    "cwd": "D:/demo",
                    "timestamp": 1756548000000,
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hello there friend"}],
                },
            ]
        ),
        encoding="utf-8",
    )
    raw = CodebuddyParser(tmp_path / ".codebuddy").load("bbb222")
    assert raw is not None
    notes = raw.meta.notes
    # the missed sibling: read, like the plan_* kinds beside it
    assert dict(raw.files_touched)["D:/demo/reentry.md"] == 1
    # excused, each for what it is
    for quiet in ("auto_mode_exit", "hook_system_message", "invoked_skills"):
        assert not [n for n in notes if n.startswith(f"unhandled_row:attachment/{quiet}")]
    # and the list still reports what it has never seen
    assert "unhandled_row:attachment/temporal_orbit_note=1" in notes
    # a skill file the harness loaded is not a file the session worked on
    assert "D:/demo/.qoder/skills/quality-gate/SKILL.md" not in dict(raw.files_touched)


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


def test_ide_task_execution_files_exact(tmp_path, monkeypatch):
    """task sessions merge only their own execution record's touched paths."""
    import json as _json

    from agent_handoff.parsers.jsonl_family import QodercnIdeParser

    state = tmp_path / ".qodersec" / "state" / "proj"
    state.mkdir(parents=True)
    (state / "task-1.session.execution.json").write_text(
        _json.dumps({"touched_paths": ["src/own.ts"]}), encoding="utf-8"
    )
    (state / "task-9.session.execution.json").write_text(
        _json.dumps({"touched_paths": ["src/other.ts"]}), encoding="utf-8"
    )
    monkeypatch.setenv("AGENTHANDOFF_HOME", str(tmp_path))
    root = tmp_path / ".qoder-cn" / "projects" / "C--x"
    root.mkdir(parents=True)
    (root / "task-1.session.execution.jsonl").write_text(
        _json.dumps(
            {
                "type": "user",
                "sessionId": "task-1.session.execution",
                "cwd": "D:/demo",
                "timestamp": "2026-08-30T10:00:00Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    p = QodercnIdeParser(tmp_path / ".qoder-cn")
    assert p._task_execution_files("task-1.session.execution") == ["src/own.ts"]
    assert p._task_execution_files("task-9.session.execution") == ["src/other.ts"]
    assert p._task_execution_files("plain-uuid") == []


def test_request_interrupted_rows_are_dropped_as_noise():
    """Official projection drops `[Request interrupted by user…]` user rows;
    the parsers must never surface them as turns."""
    from agent_handoff.parsers.base import Parser

    assert Parser.is_noise("[Request interrupted by user before completing]")
    assert not Parser.is_noise("Request a production review of this diff")


def test_snapshot_missing_task_session_is_flagged_archived(tmp_path, monkeypatch):
    """The product tags task-panel entries whose session is gone as
    archived-or-deleted. A task transcript absent from both snapshot lists is
    flagged — but only when the snapshot DB itself was readable."""
    import json as _json
    import sqlite3

    from agent_handoff.parsers.jsonl_family import QodercnIdeParser

    appdata = tmp_path / "appdata"
    gs = appdata / "QoderCN" / "User" / "globalStorage"
    gs.mkdir(parents=True)
    con = sqlite3.connect(gs / "state.vscdb")
    con.execute('CREATE TABLE ItemTable("key" TEXT, "value" TEXT)')
    active = {"folders": {"p": {"tasks": [{"executionSessionId": "task-9", "title": "Active"}]}}}
    con.execute(
        'INSERT INTO ItemTable("key", "value") VALUES (?, ?)',
        ("aicoding.questTaskListSnapshot", _json.dumps(active)),
    )
    con.execute(
        'INSERT INTO ItemTable("key", "value") VALUES (?, ?)',
        (
            "aicoding.questArchivedTaskList",
            _json.dumps([{"executionSessionId": "task-8", "title": "Old"}]),
        ),
    )
    con.commit()
    con.close()
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("AGENTHANDOFF_HOME", str(tmp_path))
    root = tmp_path / ".qoder-cn" / "projects" / "C--x"
    root.mkdir(parents=True)
    for sid in ("task-1.session.execution", "task-9.session.execution", "task-8.session.execution"):
        (root / f"{sid}.jsonl").write_text(
            _json.dumps(
                {
                    "type": "user",
                    "sessionId": sid,
                    "cwd": "D:/demo",
                    "timestamp": "2026-08-30T10:00:00Z",
                    "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                }
            )
            + "\n",
            encoding="utf-8",
        )
    p = QodercnIdeParser(tmp_path / ".qoder-cn")
    metas = {m.session_id: m for m in p.list_sessions()}
    assert "snapshot_archived" in metas["task-1.session.execution"].notes
    assert "snapshot_archived" not in metas["task-9.session.execution"].notes
    assert "snapshot_archived" not in metas["task-8.session.execution"].notes


def test_unreadable_snapshot_never_flags_archived(tmp_path, monkeypatch):
    """No snapshot DB means unknown, never a badge — absence of evidence."""
    import json as _json

    from agent_handoff.parsers.jsonl_family import QodercnIdeParser

    monkeypatch.setenv("APPDATA", str(tmp_path / "no-appdata-here"))
    monkeypatch.setenv("AGENTHANDOFF_HOME", str(tmp_path))
    root = tmp_path / ".qoder-cn" / "projects" / "C--x"
    root.mkdir(parents=True)
    (root / "task-1.session.execution.jsonl").write_text(
        _json.dumps(
            {
                "type": "user",
                "sessionId": "task-1.session.execution",
                "cwd": "D:/demo",
                "timestamp": "2026-08-30T10:00:00Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    p = QodercnIdeParser(tmp_path / ".qoder-cn")
    metas = p.list_sessions()
    assert metas and all("snapshot_archived" not in m.notes for m in metas)
def test_ide_telemetry_anchors_exact(tmp_path):
    """ai-stats attributes only rows whose lineDetails carry this sessionId."""
    import json as _json

    stats = tmp_path / ".qoder-cli" / "ai-stats" / "projects" / "p"
    stats.mkdir(parents=True)
    (stats / "a.jsonl").write_text(
        "\n".join(
            [
                _json.dumps(
                    {
                        "filePath": "src/own.ts",
                        "lineDetails": [{"sessionId": "sid-1"}, {"sessionId": "sid-9"}],
                    }
                ),
                _json.dumps({"filePath": "src/other.ts", "lineDetails": [{"sessionId": "sid-9"}]}),
                _json.dumps({"lineDetails": [{"sessionId": "sid-1"}]}),
                "{broken",
            ]
        ),
        encoding="utf-8",
    )
    p = QodercnIdeParser(tmp_path / ".qoder-cn")
    projects = stats.parent
    assert p.telemetry_anchors("sid-1", stats_dir=projects) == {"src/own.ts": 1}
    assert p.telemetry_anchors("sid-9", stats_dir=projects) == {
        "src/own.ts": 1,
        "src/other.ts": 1,
    }
    assert p.telemetry_anchors("sid-missing", stats_dir=projects) == {}


def test_one_open_does_not_reread_the_store_for_the_model_hint(tmp_path):
    """The workspace-model hint must cost the session, not the workspace.

    qoder writes no model on task-class sessions, so the hint searches for a
    same-cwd, time-overlapping sibling. That search once began by re-listing the
    whole store: measured on this machine at **6,501 of the 6,667 file reads in a
    single `load()`** -- so opening a two-message session cost as much as the
    largest workspace on disk (1,334 sessions live in one directory here).

    Bounding it is only honest if the answer survives, so the test asserts both
    halves: the hint is still given, a second open reads a bounded number of
    files, and touching a sibling makes the cache let go.
    """
    import json
    import os
    import time

    import agent_handoff.parsers.jsonl_family as jf

    jf._ANCHOR_FACTS.clear()
    proj = tmp_path / ".qoder-cn" / "projects" / "C--w"
    proj.mkdir(parents=True)

    def write(sid: str, cwd: str, model: str | None, minute: int) -> Path:
        cfg = {"type": "runtime-config", "sessionId": sid, "cwd": cwd, "timestamp": 1}
        if model:
            cfg["model"] = model
        rows = [
            cfg,
            {
                "type": "user",
                "sessionId": sid,
                "cwd": cwd,
                "timestamp": f"2026-08-30T10:{minute:02d}:00Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "ask"}]},
            },
            {
                "type": "assistant",
                "sessionId": sid,
                "cwd": cwd,
                "timestamp": f"2026-08-30T10:{minute:02d}:30Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
            },
        ]
        path = proj / f"{sid}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return path

    # The sibling that carries the answer, written first so the search need not
    # go far; then 12 decoys in other workspaces that must be ruled out.
    write("sib-anchor", "C:/w", "gemini-x", 0)
    decoys = [write(f"sib-{i:02d}", f"C:/other-{i}", "gpt-z", 1 + i) for i in range(12)]
    write("ask-me", "C:/w", None, 2)

    real = jf.read_jsonl
    reads = {"n": 0}

    def counted(path, *a, **kw):
        reads["n"] += 1
        return real(path, *a, **kw)

    jf.read_jsonl = counted
    try:
        p = QodercnIdeParser(tmp_path / ".qoder-cn")
        p.list_sessions()

        reads["n"] = 0
        first = p.load("ask-me")
        first_reads = reads["n"]
        hints = [n for n in first.meta.notes if n.startswith("workspace_model:")]
        assert hints and "gemini-x" in hints[0], first.meta.notes

        reads["n"] = 0
        again = p.load("ask-me")
        second_reads = reads["n"]
        assert [n for n in again.meta.notes if n.startswith("workspace_model:")] == hints

        # The store has 14 sessions; a bounded repeat must not scale with it.
        assert second_reads <= 4, f"second open still read {second_reads} files"
        assert second_reads < first_reads, "the hint cache never engaged"

        os.utime(decoys[3], (time.time() + 2, time.time() + 2))
        reads["n"] = 0
        after = p.load("ask-me")
        touched_reads = reads["n"]
        assert [n for n in after.meta.notes if n.startswith("workspace_model:")] == hints
        assert touched_reads > second_reads, "a changed sibling did not recompute"
    finally:
        jf.read_jsonl = real
        jf._ANCHOR_FACTS.clear()


def test_the_qoder_turn_echo_is_absorbed_by_the_session_that_carries_it(tmp_path):
    """A fragment is hidden only while its proof is on disk, and the proof costs
    one stat per remembered text - never a re-read of the store.

    qoder writes every user turn twice: once as an `add_user_message` fragment
    file, once inside the task/uuid conversation. Listing both shows one
    chat twice, so `_absorbed_fragment_ids` hides the fragment - and that scan
    ran on every 20s rebuild, because its cache key was the newest mtime of
    the whole store (which moves every second a session is live). The scan
    reached 4.1s of an 11.3s poll and, on this machine's stores, ~170,000 JSON
    rows parsed per poll (spec Round 50).

    Caching the answers is only honest if the answer is the same one, so this
    pins all four directions: the absorbed fragment goes, the unabsorbed one
    stays, a repeat pass reads no transcript at all, and deleting the session
    that proved the match brings the fragment back.
    """
    import json
    import time

    import agent_handoff.parsers.jsonl_family as jf

    proj = tmp_path / ".qoder-cn" / "projects" / "C--w"
    proj.mkdir(parents=True)
    for name in (
        "_PEEK_CACHE",
        "_ID_CACHE",
        "_FRAG_HEAD_CACHE",
        "_QODER_ABSORB_CACHE",
        "_PROVEN_ABSORBED_TEXTS",
    ):
        getattr(jf, name).clear()

    def meta(sid: str, cwd: str, minute: int) -> dict:
        return {
            "type": "session_meta",
            "sessionId": sid,
            "timestamp": f"2026-09-20T10:{minute:02d}:00Z",
            "cwd": cwd,
            "data": {"meta_type": "session_info", "content": {"session_type": "add_user_message"}},
        }

    def user(sid: str, cwd: str, minute: int, text: str) -> dict:
        return {
            "type": "user",
            "sessionId": sid,
            "timestamp": f"2026-09-20T10:{minute:02d}:00Z",
            "cwd": cwd,
            "message": {"role": "user", "content": text},
        }

    def write(name: str, rows: list[dict]) -> Path:
        path = proj / f"{name}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return path

    # 20 unrelated sessions: the scan the old code repeated used to read these.
    for i in range(20):
        write(
            f"task-{i:02d}",
            [
                user(f"task-{i:02d}", f"C:/w{i}", 30 + i, f"unrelated question {i}"),
                {
                    "type": "assistant",
                    "sessionId": f"task-{i:02d}",
                    "timestamp": f"2026-09-20T10:{40 + (i % 10):02d}:00Z",
                    "cwd": f"C:/w{i}",
                    "message": {"role": "assistant", "content": "ok"},
                },
            ],
        )
    # frag-echo: the IDE also kept its text inside task-00, so it must go.
    write("frag-echo", [meta("frag-echo", "C:/a", 5), user("frag-echo", "C:/a", 5, "hello")])
    # frag-alone: no session carries this turn, so it must stay listed.
    write("frag-alone", [meta("frag-alone", "C:/b", 6), user("frag-alone", "C:/b", 6, "only here")])
    # The proving file goes last: its mtime is the store's newest, so deleting
    # it below is something the cache key can actually notice.
    time.sleep(0.05)
    proof = write("task-00-proof", [user("task-00-proof", "C:/a", 7, "hello")])

    real_read = jf.read_jsonl
    reads = {"n": 0}

    def counted(path, *a, **kw):
        reads["n"] += 1
        return real_read(path, *a, **kw)

    jf.read_jsonl = counted
    try:
        p = QodercnIdeParser(tmp_path / ".qoder-cn")
        first = {m.session_id for m in p.list_sessions()}
        cold_reads = reads["n"]
        assert "frag-echo" not in first, "the duplicated turn echo was not absorbed"
        assert "frag-alone" in first, "absorption swallowed a fragment nothing carries"

        reads["n"] = 0
        again = QodercnIdeParser(tmp_path / ".qoder-cn")
        second = {m.session_id for m in again.list_sessions()}
        warm_reads = reads["n"]
        assert second == first, f"a second pass changed the answer: {second ^ first}"
        assert warm_reads == 0, f"a pass over an unchanged store read {warm_reads} files"
        assert warm_reads < cold_reads

        # The proof is no longer what it was: the session still exists, but the
        # turn it carried is gone. A remembered match must be re-derived, not
        # trusted - otherwise the fragment stays hidden although nothing lists
        # the conversation, i.e. a chat silently leaves the cockpit.
        time.sleep(0.02)
        write("task-00-proof", [user("task-00-proof", "C:/a", 7, "a different turn entirely")])
        fourth = {m.session_id for m in QodercnIdeParser(tmp_path / ".qoder-cn").list_sessions()}
        assert "frag-echo" in fourth, (
            "a fragment stayed absorbed after the session that proved it changed"
        )

        # And gone altogether: same demand from the other direction.
        proof.unlink()
        reads["n"] = 0
        third = {
            m.session_id for m in QodercnIdeParser(tmp_path / ".qoder-cn").list_sessions()
        }
        assert "frag-echo" in third, (
            "the absorbed fragment stayed hidden after its proof was deleted"
        )
    finally:
        jf.read_jsonl = real_read
        for name in (
            "_PEEK_CACHE",
            "_ID_CACHE",
            "_FRAG_HEAD_CACHE",
            "_QODER_ABSORB_CACHE",
            "_PROVEN_ABSORBED_TEXTS",
        ):
            getattr(jf, name).clear()
