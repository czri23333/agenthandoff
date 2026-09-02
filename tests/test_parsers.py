'''Parser tests against synthetic stores (see CONTRIBUTING: happy path + corrupt input).'''

from __future__ import annotations

from agent_handoff.parsers.codex import CodexParser
from agent_handoff.parsers.dsh import DshParser
from agent_handoff.parsers.jsonl_family import (
    ClaudeCodeParser,
    CodebuddyParser,
    QodercnIdeParser,
    QoderworkParser,
    QwenworkParser,
)
from agent_handoff.parsers.zcode import ZcodeParser


def test_zcode_happy(zcode_store):
    p = ZcodeParser(zcode_store / "zcode" / "cli" / "db" / "db.sqlite")
    metas = p.list_sessions()
    assert [m.session_id for m in metas] == ["sess_a"]
    assert metas[0].title == "Fix login loop"
    raw = p.load("sess_a")
    assert raw is not None
    roles = [(m.role, m.text) for m in raw.messages]
    assert ("user", "Fix the login redirect loop. 不要引入新的依赖") in roles
    assert raw.files_touched["src/auth.ts"] == 1
    assert raw.tool_counts["Edit"] == 1
    assert [t.content for t in raw.todos if t.status == "in_progress"] == ["patch middleware"]
    assert raw.meta.tokens_in == 30 and raw.meta.tokens_out == 15  # summed across turns


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
            {"type": "user", "timestamp": "2026-08-30T10:00:00Z",
             "message": {"role": "user", "content": [{"type": "text", "text": text}]}},
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
        {"type": "user", "timestamp": "2026-08-30T10:00:00Z",
         "message": {"role": "user", "content": [{"type": "text", "text": "fix the login loop"}]}},
        {"type": "assistant", "timestamp": "2026-08-30T10:00:01Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "found it"}]}},
    ]
    with open(root / "aaa111.jsonl", "w", encoding="utf-8") as fh:
        for r in turn:
            fh.write(json.dumps(r) + "\n")

    # Zero real text: every user row is a tool_result echo, every assistant row
    # a tool_use - the exact shape qoder writes for a browser/automation run.
    loop = [
        {"type": "runtime-config", "sessionId": "bbb222", "timestamp": 1},
        {"type": "user", "timestamp": "2026-08-30T10:01:00Z",
         "message": {"role": "user", "content": [
             {"content": "browser said no", "is_error": False,
              "tool_use_id": "t1", "type": "tool_result"}]}},
        {"type": "assistant", "timestamp": "2026-08-30T10:01:01Z",
         "message": {"role": "assistant", "content": [
             {"id": "c1", "input": {"url": "https://example.test"},
              "name": "browser_open", "type": "tool_use"}]}},
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
