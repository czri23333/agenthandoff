"""Summarize's phase-aware conclusion selection.

The parser now stamps Codex assistant rows with ``phase``; summarize must use
that signal to stop treating tool cards, thinking blocks and sub-agent rows as
the session's conclusion. These tests use hand-built RawSessions, not fixtures.
"""

from __future__ import annotations

from agent_handoff.model import HandoffBundle, Interruption, Message, RawSession, SessionMeta
from agent_handoff.summarize import _unfinished, summarize


def make_raw(messages: list[Message], interruption: Interruption | None = None) -> RawSession:
    meta = SessionMeta(
        cli="codex",
        session_id="s1",
        title="t",
        cwd="D:/demo",
        started_at="2026-08-30T10:00:00+00:00",
        updated_at="2026-08-30T11:00:00+00:00",
    )
    return RawSession(meta=meta, messages=messages, interruption=interruption or Interruption())


def test_notes_prefer_final_answer_over_commentary():
    raw = make_raw(
        [
            Message(role="user", text="开始这个任务。"),
            Message(
                role="assistant",
                text="还在思考，这里是一段足够长的过程文本，先放着。",
                phase="commentary",
            ),
            Message(
                role="assistant",
                text="最终结论已经确定，全部测试通过并且可以交付使用了。",
                phase="final_answer",
            ),
        ]
    )
    bundle = summarize(raw)
    assert any("最终结论" in n for n in bundle.context_notes)
    assert not any("还在思考" in n for n in bundle.context_notes)


def test_notes_fall_back_to_commentary_when_no_final_answer():
    raw = make_raw(
        [
            Message(role="user", text="开始这个任务。"),
            Message(
                role="assistant",
                text="这里只有过程文本，但也是当前唯一的结论候选。",
                phase="commentary",
            ),
        ]
    )
    bundle = summarize(raw)
    assert any("过程文本" in n for n in bundle.context_notes)


def test_tool_card_is_not_a_conclusion():
    raw = make_raw(
        [
            Message(role="user", text="跑一下测试。"),
            Message(role="assistant", text="[工具 run_tests · command]", phase="commentary"),
            Message(
                role="assistant",
                text="测试已经跑完并且全部通过，这是本次的最终结论。",
                phase="final_answer",
            ),
        ]
    )
    bundle = summarize(raw)
    assert not any("[工具" in n for n in bundle.context_notes)
    assert any("全部通过" in n for n in bundle.context_notes)


def test_unfinished_reports_truncated_commentary():
    raw = make_raw(
        [
            Message(role="user", text="开始写报告。", at="2026-08-30T10:00:00+00:00"),
            Message(
                role="assistant",
                text="报告写到这里还没有结束",
                phase="commentary",
                at="2026-08-30T10:05:00+00:00",
            ),
        ]
    )
    raw.interruption = Interruption(kind="length_truncated", detail="finish_reason=length")
    bundle = HandoffBundle(meta=raw.meta, interruption=Interruption(kind="length_truncated"))
    assert _unfinished(raw, bundle).endswith("还没有结束")


def test_unfinished_prefers_last_commentary_over_older_final_answer():
    raw = make_raw(
        [
            Message(
                role="assistant",
                text="上一轮的最终回答已经完成。",
                phase="final_answer",
                at="2026-08-30T10:00:00+00:00",
            ),
            Message(role="user", text="再来一个。", at="2026-08-30T10:05:00+00:00"),
            Message(
                role="assistant",
                text="这一轮还在写就被截断了",
                phase="commentary",
                at="2026-08-30T10:06:00+00:00",
            ),
        ]
    )
    raw.interruption = Interruption(kind="length_truncated", detail="finish_reason=length")
    bundle = HandoffBundle(meta=raw.meta, interruption=Interruption(kind="length_truncated"))
    tail = _unfinished(raw, bundle)
    assert "这一轮还在写" in tail
    assert "上一轮" not in tail


def test_no_assistant_text_does_not_crash():
    raw = make_raw([Message(role="user", text="只有用户消息。")])
    bundle = summarize(raw)
    assert bundle.context_notes == []
    assert bundle.unfinished == ""
