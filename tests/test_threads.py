"""Task-thread clustering and mixed-session topic detection tests."""

from __future__ import annotations

from agent_handoff.model import Message, RawSession, SessionMeta
from agent_handoff.render import parse_bundle_markdown, render_markdown
from agent_handoff.summarize import summarize
from agent_handoff.threads import SessionNode, build_threads, title_tokens


def _node(sid: str, cli: str, files: list[str], title: str = "", parent=None,
          updated="2026-08-30T10:00:00+00:00", origin=None) -> SessionNode:
    meta = SessionMeta(cli=cli, session_id=sid, title=title, cwd="D:/demo",
                       updated_at=updated, parent_session_id=parent, origin=origin)
    return SessionNode(meta=meta, files={f.replace("\\", "/").lower() for f in files},
                       tokens=title_tokens(title))


def test_lineage_links_parent_and_child():
    threads = build_threads([
        _node("parent1", "zcode", ["src/a.py"]),
        _node("child1", "zcode", ["src/b.py"], parent="parent1"),
    ])
    assert len(threads) == 1 and len(threads[0].sessions) == 2


def test_file_overlap_links_across_clis():
    files = ["src/auth.ts", "src/middleware/auth.ts", "tests/login.py"]
    threads = build_threads([
        _node("s1", "zcode", files),
        _node("s2", "codebuddy", files + ["src/extra.py"]),
        _node("s3", "claude", ["unrelated/thing.rs"]),
    ])
    big = [t for t in threads if len(t.sessions) == 2]
    assert big and {s.meta.session_id for s in big[0].sessions} == {"s1", "s2"}


def test_title_tokens_chinese_bigrams():
    toks = title_tokens("WebGAL全量对标续跑提示词")
    assert "webgal" in toks and "全量" in toks and "对标" in toks


def test_standalone_session_is_own_thread():
    threads = build_threads([_node("lonely", "zcode", ["x.py"], title="独特任务")])
    assert len(threads) == 1 and len(threads[0].sessions) == 1


def test_topic_segments_mixed_session():
    raw = RawSession(meta=SessionMeta(cli="zcode", session_id="s", title="t", cwd="D:/x"),
                     messages=[
        Message(role="user", text="做视频", at="2026-08-30T08:00:00+00:00"),
        Message(role="assistant", text="好的，开始。", at="2026-08-30T08:05:00+00:00"),
        Message(role="user", text="换个事：写交接工具", at="2026-08-30T14:30:00+00:00"),
        Message(role="assistant", text="明白。", at="2026-08-30T14:31:00+00:00"),
    ])
    b = summarize(raw)
    assert b.objective.endswith("(multi-topic session: 2 segments)")
    assert len(b.topics) == 2
    assert b.topics[0][0] == "做视频" and b.topics[1][0] == "换个事：写交接工具"


def test_topic_segments_single_topic_untouched():
    raw = RawSession(meta=SessionMeta(cli="zcode", session_id="s", title="t", cwd="D:/x"),
                     messages=[
        Message(role="user", text="a", at="2026-08-30T08:00:00+00:00"),
        Message(role="user", text="b", at="2026-08-30T08:10:00+00:00"),
    ])
    b = summarize(raw)
    assert b.topics == [] and "multi-topic" not in b.objective


def test_topics_roundtrip_through_markdown():
    raw = RawSession(meta=SessionMeta(cli="zcode", session_id="s", title="t", cwd="D:/x"),
                     messages=[
        Message(role="user", text="话题一", at="2026-08-30T08:00:00+00:00"),
        Message(role="assistant", text="ok.", at="2026-08-30T08:05:00+00:00"),
        Message(role="user", text="话题二", at="2026-08-30T18:00:00+00:00"),
    ])
    b = summarize(raw)
    b2 = parse_bundle_markdown(render_markdown(b))
    assert len(b2.topics) == 2
    assert b2.topics[1][0] == "话题二"
