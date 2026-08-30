r"""Bundle text must survive markdown: the directive splitter used to cut links.

Reproduced from a real shipped handover, where a user line

    8 - [竖屏面板根因](vertical-panel-fix.md) — 用户跑的是 D:/wgtgt 构建，修复后必须同步部署

landed in the continuation brief as two fragments —

    md) — 用户跑的是 D:\wgtgt 构建，修复后必须同步部署
    8 - [竖屏面板根因](vertical-panel-fix.

because the sentence splitter split on "." and "\n" without knowing anything
about markup, and each half independently matched a directive cue. The brief is
this tool's flagship output, so "it reads like garbage" is a product defect.
"""

from __future__ import annotations

from agent_handoff.model import Message, RawSession, SessionMeta
from agent_handoff.summarize import _balanced, _collapse_markdown, _pick_directives, summarize


def _raw(messages: list[Message]) -> RawSession:
    meta = SessionMeta(
        cli="zcode",
        session_id="s1",
        title="demo",
        cwd="D:/demo",
        started_at="2026-08-30T10:00:00+00:00",
        updated_at="2026-08-30T11:00:00+00:00",
    )
    return RawSession(meta=meta, messages=messages)


def test_markdown_link_target_is_dropped_not_split():
    text = (
        "8 - [竖屏面板根因](vertical-panel-fix.md) — "
        "用户跑的是 D:/wgtgt 构建，修复后必须同步部署"
    )
    got = _pick_directives([Message(role="user", text=text)])
    assert got, "the directive must survive"
    assert all("md)" not in g for g in got), got
    assert all("(" not in g for g in got), f"link syntax leaked into the bundle: {got}"
    assert any("必须同步部署" in g for g in got)


def test_no_fragment_is_unbalanced():
    """Every emitted directive closes what it opens."""
    text = (
        "先看 (a/b 这条，必须复现。\n"
        "参考 [文档](docs/x.md) 这个说法不对，改用方案 B。\n"
        "`inline code` 不要引入新依赖，用现有中间件修复。"
    )
    for got in _pick_directives([Message(role="user", text=text)]):
        assert _balanced(got), got


def test_english_directives_still_split_on_periods():
    text = "This is fine. Do not touch the schema, it is frozen. Another topic here."
    got = _pick_directives([Message(role="user", text=text)])
    assert any(g.startswith("Do not touch") for g in got), got


def test_image_syntax_collapses_to_alt_text():
    assert _collapse_markdown("![cast](img/cast.png) 必须对齐官方") == "cast 必须对齐官方"


def test_clip_also_flattens_markup():
    bundle = summarize(_raw([Message(role="user", text="见 [设计](plan.md) 这一份，必须照做")]))
    assert all("](" not in line for line in bundle.directives)


def test_compaction_echoes_are_still_ignored():
    """The old guard stays: quoted-back bullets are a summary's paraphrase."""
    text = "- 已完成：修好登录\n- 不要引入新依赖，用现有中间件修复"
    assert _pick_directives([Message(role="user", text=text)]) == []


def test_plain_sentences_are_untouched():
    text = "第一句普通话。不要引入新的依赖，用现有中间件修复。第二句。"
    got = _pick_directives([Message(role="user", text=text)])
    assert got == ["不要引入新的依赖，用现有中间件修复。"]
