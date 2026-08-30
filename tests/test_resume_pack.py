"""The resume pack: what survives a quota death.

These tests pin the policy that the previous design got backwards — under a
tight budget the *oldest* context is sacrificed, the newest is not.
"""

from __future__ import annotations

from agent_handoff.model import HandoffBundle, Interruption, Message, RawSession, SessionMeta
from agent_handoff.resume import render_brief
from agent_handoff.summarize import _pick_recent, _unfinished, summarize


def _raw(
    messages: list[tuple[str, str]], *, updated: str = "2026-08-30T11:00:00+00:00"
) -> RawSession:
    meta = SessionMeta(
        cli="zcode",
        session_id="s1",
        title="Port the renderer",
        cwd="D:/demo",
        started_at="2026-08-30T09:00:00+00:00",
        updated_at=updated,
    )
    # Strictly increasing stamps: the end-state heuristics compare the newest user
    # turn against the newest assistant turn, so a shared timestamp would make
    # every fixture look interrupted.
    from datetime import datetime, timedelta

    base = datetime.fromisoformat(updated)
    stamped = [
        Message(role=role, text=text, at=(base + timedelta(minutes=i)).isoformat())
        for i, (role, text) in enumerate(messages)
    ]
    return RawSession(meta=meta, messages=stamped)


def _dialogue(turns: int, size: int = 200) -> list[tuple[str, str]]:
    """Synthetic turns that end like finished sentences - the summariser treats a
    reply without ending punctuation as a cut-off fragment, on purpose."""
    out: list[tuple[str, str]] = []
    for i in range(turns):
        role = "user" if i % 2 == 0 else "assistant"
        out.append((role, f"turn {i:03d} " + ("x" * size) + "。"))
    return out


# -- extraction ---------------------------------------------------------------


def test_recent_keeps_the_newest_turns_verbatim():
    raw = _raw(_dialogue(40))
    recent = _pick_recent(raw, 2000)
    assert recent, "a session with 40 turns must yield a tail"
    assert recent[-1][0] == "assistant"
    assert "turn 039" in recent[-1][1]
    indices = [int(text.split()[1]) for _role, text in recent]
    assert indices == sorted(indices), "the pack is ordered oldest first"


def test_recent_always_keeps_a_floor_of_turns_even_if_over_budget():
    """The floor beats the budget: the last turns are not negotiable."""
    raw = _raw(_dialogue(12, size=5000))
    recent = _pick_recent(raw, 1000)
    assert len(recent) >= 6


def test_giant_final_turn_keeps_its_end():
    """Where the sentence broke off is the useful half."""
    tail_text = ("y" * 9000) + "_TAIL_MARKER"
    raw = _raw([("user", "go"), ("assistant", tail_text)])
    recent = _pick_recent(raw, 1000)
    kept = recent[-1][1]
    assert kept.endswith("_TAIL_MARKER"), "the end of the turn is what survives"
    assert kept.startswith("…"), "the clipped head is marked, not silently removed"


def test_dead_session_gets_a_deeper_tail_than_a_clean_one():
    turns = _dialogue(60, size=400)
    clean = summarize(_raw(turns))
    # An unanswered final user turn is exactly how a quota death looks.
    dead = summarize(_raw(turns + [("user", "继续，别停。")]))
    assert clean.interruption.kind == "clean", clean.interruption.describe()
    assert dead.interruption.kind == "user_pending"
    dead_chars = len("".join(t for _r, t in dead.recent))
    clean_chars = len("".join(t for _r, t in clean.recent))
    assert dead_chars > clean_chars


def test_unfinished_output_is_carried_when_the_reply_was_cut():
    reply = "结论是前面都对了，最后一步需要把 colorspace 改成"
    raw = _raw([("user", "写下去"), ("assistant", reply)])
    bundle = summarize(raw)
    bundle.interruption = Interruption(kind="length_truncated", detail="max tokens")
    cut = _unfinished(raw, bundle)
    assert cut.endswith("改成"), "the cut-off tail is what to continue from"


def test_no_unfinished_for_a_cleanly_finished_session():
    raw = _raw([("user", "done?"), ("assistant", "Yes, all tests pass.")])
    bundle = summarize(raw)
    assert bundle.unfinished == ""


# -- brief policy -------------------------------------------------------------


def _bundle(**kw) -> HandoffBundle:
    meta = SessionMeta(cli="zcode", session_id="s", title="t", cwd="D:/demo")
    base = dict(
        meta=meta,
        objective=" Port the renderer",
        directives=["RULE_MUST_STAY: do not touch the schema"],
        context_notes=["D" * 4000],
        next_steps=["step 1", "step 2"],
        recent=[
            ("user", "EARLY_CONTEXT_" + ("a" * 300)),
            ("assistant", "LATEST_CONTEXT_" + ("b" * 300)),
        ],
    )
    base.update(kw)
    return HandoffBundle(**base)


def test_brief_includes_the_pack_by_default():
    brief = render_brief(_bundle(), lang="en", max_chars=10**9)
    assert "recent context (verbatim, oldest first)" in brief
    assert "LATEST_CONTEXT_" in brief and "EARLY_CONTEXT_" in brief


def test_brief_can_omit_the_pack_on_request():
    brief = render_brief(_bundle(), lang="zh", max_chars=10**9, with_pack=False)
    assert "接续上下文" not in brief


def test_tight_budget_keeps_the_newest_turn_and_drops_the_oldest():
    bundle = _bundle(
        recent=[
            ("user", "OLDEST_" + ("a" * 4000)),
            ("assistant", "MIDDLE_" + ("b" * 4000)),
            ("user", "NEWEST_" + ("c" * 100)),
        ]
    )
    full = len(render_brief(bundle, max_chars=10**9))
    tight = render_brief(bundle, max_chars=full // 2)
    assert "NEWEST_" in tight, "the freshest turn is the last thing to go"
    assert "OLDEST_" not in tight, "stale context is what the budget pays with"
    assert "RULE_MUST_STAY" in tight, "user corrections outrank old context"


def test_unfinished_survives_even_the_worst_budget():
    fragment = "…half a sentence abo"
    bundle = _bundle(recent=[("assistant", fragment)], unfinished=fragment)
    tight = render_brief(bundle, max_chars=900)
    assert "cut off" in tight or "接着写" in tight or "half a sentence" in tight


def test_brief_is_deterministic():
    bundle = _bundle()
    assert render_brief(bundle) == render_brief(bundle)
    assert render_brief(bundle, lang="zh") == render_brief(bundle, lang="zh")
