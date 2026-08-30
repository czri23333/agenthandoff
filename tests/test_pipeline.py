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


# -- interruption awareness ---------------------------------------------------

from agent_handoff.model import Interruption  # noqa: E402


def test_user_pending_detected_and_promoted():
    raw = make_raw(messages=[
        Message(role="user", text="first ask", at="2026-08-30T10:00:00+00:00"),
        Message(role="assistant", text="done that part.", at="2026-08-30T10:05:00+00:00"),
        Message(role="user", text="然后跑回归测试", at="2026-08-30T10:06:00+00:00"),
    ])
    b = summarize(raw)
    assert b.interruption.kind == "user_pending"
    assert b.interruption.pending_user_text == "然后跑回归测试"
    assert b.next_steps[0].startswith("[pending from interrupted session]")
    assert "然后跑回归测试" in b.next_steps[0]


def test_clean_when_assistant_replied_last():
    raw = make_raw(messages=[
        Message(role="user", text="ask", at="2026-08-30T10:00:00+00:00"),
        Message(role="assistant", text="all done, tests green.", at="2026-08-30T10:05:00+00:00"),
    ])
    b = summarize(raw)
    assert b.interruption.kind == "clean"


def test_parser_cancelled_survives_and_truncated_note_dropped():
    raw = make_raw(messages=[
        Message(role="user", text="ask", at="2026-08-30T10:00:00+00:00"),
        Message(
            role="assistant",
            text="generating a very long report that got cut",
            at="2026-08-30T10:05:00+00:00",
        ),
    ])
    raw.interruption = Interruption(
        kind="length_truncated", detail="finish_reason=length"
    )
    b = summarize(raw)
    assert b.interruption.kind == "length_truncated"
    # the truncated fragment must not appear as a conclusion
    assert not any("got cut" in n for n in b.context_notes)


def test_interruption_roundtrips_through_markdown():
    b = HandoffBundle(
        meta=SessionMeta(cli="zcode", session_id="s", title="t", cwd="D:/demo"),
        interruption=Interruption(kind="user_pending", pending_user_text="跑完测试了吗"),
        next_steps=["[pending from interrupted session] 跑完测试了吗"],
    )
    b2 = parse_bundle_markdown(render_markdown(b))
    assert b2.interruption.kind == "user_pending"
    assert b2.interruption.pending_user_text == "跑完测试了吗"


def test_brief_warns_and_keeps_warning_under_budget():
    b = HandoffBundle(
        meta=SessionMeta(cli="zcode", session_id="s", title="t", cwd="D:/demo"),
        directives=["R" * 9000],
        interruption=Interruption(
            kind="user_pending", detail="d", pending_user_text="finish the run"
        ),
    )
    brief = render_brief(b, max_chars=3000)
    assert "ended abruptly" in brief
    assert "finish the run" in brief  # pending instruction survives trimming
    assert "R" * 9000 not in brief
