"""Summarize/render/resume pipeline tests: round-trip, determinism, budget policy."""

from __future__ import annotations

from agent_handoff.model import HandoffBundle, Message, RawSession, SessionMeta, TodoItem
from agent_handoff.render import parse_bundle_markdown, render_json, render_markdown
from agent_handoff.resume import render_brief
from agent_handoff.summarize import summarize


def make_raw(**kw) -> RawSession:
    meta = SessionMeta(
        cli="zcode",
        session_id="s1",
        title="t",
        cwd="D:/demo",
        started_at="2026-08-30T10:00:00+00:00",
        updated_at="2026-08-30T11:00:00+00:00",
    )
    return RawSession(meta=meta, **kw)


def test_todo_state_split():
    raw = make_raw(
        todos=[
            TodoItem(content="a", status="completed"),
            TodoItem(content="b", status="in_progress"),
            TodoItem(content="c", status="pending"),
        ],
        messages=[Message(role="user", text="do a b c")],
    )
    b = summarize(raw)
    assert b.done == ["a"] and b.in_progress == ["b"] and b.blocked == ["c"]


def test_directives_extracted_and_verbatim():
    raw = make_raw(messages=[
        Message(role="user", text="第一句普通话。不要引入新的依赖，用现有中间件修复。第二句。"),
        Message(role="assistant", text="ok"),
    ])
    b = summarize(raw)
    assert "不要引入新的依赖，用现有中间件修复。" in b.directives


def test_deterministic_render():
    raw = make_raw(messages=[Message(role="user", text="x"), Message(role="assistant", text="y")])
    b = summarize(raw)
    assert render_markdown(b) == render_markdown(b)
    assert render_json(b) == render_json(b)


def test_bundle_roundtrip():
    raw = make_raw(
        todos=[TodoItem(content="done thing", status="completed")],
        messages=[
            Message(role="user", text="please fix it"),
            Message(role="assistant", text="Final state: all green, tests pass."),
        ],
    )
    b = summarize(raw)
    md = render_markdown(b)
    b2 = parse_bundle_markdown(md)
    assert b2.meta.cli == b.meta.cli
    assert b2.meta.session_id == b.meta.session_id
    assert b2.done == b.done
    assert b2.next_steps == b.next_steps
    assert "Final state" in " ".join(b2.context_notes)


def test_budget_drops_digest_first_keeps_rules():
    b = HandoffBundle(
        meta=SessionMeta(cli="zcode", session_id="s", title="t", cwd="D:/demo"),
        objective="obj",
        done=["fact " * 5] * 20,
        directives=["RULE_MUST_STAY"],
        next_steps=["step 1", "step 2"],
        context_notes=["digest " * 50] * 5,
    )
    full = render_brief(b, max_chars=10**9)
    assert "RULE_MUST_STAY" in full and "<digest>" in full
    tight = render_brief(b, max_chars=len(full) // 2)
    assert "RULE_MUST_STAY" in tight          # rules survive
    assert "step 1" in tight and "step 2" in tight
    assert "<digest>" not in tight            # digest dropped whole, not truncated


def test_budget_keeps_header_when_all_else_dropped():
    b = HandoffBundle(
        meta=SessionMeta(cli="zcode", session_id="s", title="t", cwd="D:/demo"),
        directives=["R" * 9000],
    )
    tiny = render_brief(b, max_chars=2000)
    assert "<project>" in tiny and "RULE" not in tiny
    assert "agenthandoff v0.1" in tiny


def test_zh_scaffolding():
    b = HandoffBundle(meta=SessionMeta(cli="zcode", session_id="s", title="t", cwd="D:/demo"),
                      next_steps=["第一步"])
    brief = render_brief(b, lang="zh")
    assert "不要重做" in brief and "<下一步>" in brief
