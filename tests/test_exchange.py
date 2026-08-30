"""Multi-agent exchange lifecycle and lineage extraction tests."""

from __future__ import annotations

import json
from pathlib import Path

from agent_handoff.exchange import claim, inbox, publish
from agent_handoff.model import HandoffBundle, SessionMeta
from agent_handoff.render import render_markdown


def _write_bundle(path: Path, session_id: str = "sess_pub01", title: str = "t") -> Path:
    b = HandoffBundle(
        meta=SessionMeta(cli="zcode", session_id=session_id, title=title, cwd="D:/demo")
    )
    path.write_text(render_markdown(b), encoding="utf-8")
    return path


def test_publish_inbox_claim_lifecycle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = _write_bundle(tmp_path / "bundle.md")
    dest = publish(src, note="for the overnight agent")
    assert dest.parent == tmp_path / ".handoff"
    assert "handoff-" in dest.name and "sess_pub01" in dest.name
    assert "for the overnight agent" in dest.read_text(encoding="utf-8")

    items = inbox()
    assert len(items) == 1 and items[0].claimed is False
    assert items[0].cli == "zcode" and items[0].session_id == "sess_pub01"

    sidecar = claim(items[0].path, claimed_by="agent-B")
    assert sidecar.exists()
    assert json.loads(sidecar.read_text(encoding="utf-8"))["claimed_by"] == "agent-B"

    items = inbox()
    assert items[0].claimed is True and items[0].claimed_by == "agent-B"


def test_publish_global_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("agent_handoff.exchange.Path.home", lambda: tmp_path)
    src = _write_bundle(tmp_path / "b.md", session_id="sess_glob")
    dest = publish(src, global_scope=True)
    assert dest.parent == tmp_path / ".agenthandoff"
    assert len(inbox(global_scope=True)) == 1


def test_publish_missing_bundle(tmp_path):
    try:
        publish(tmp_path / "nope.md")
        raised = False
    except FileNotFoundError:
        raised = True
    assert raised


def test_lineage_fields_roundtrip(tmp_path):
    b = HandoffBundle(
        meta=SessionMeta(
            cli="zcode",
            session_id="sess_child",
            title="subtask",
            cwd="D:/demo",
            provider="builtin:bigmodel-start-plan",
            parent_session_id="sess_parent",
            notes=["account:work"],
        )
    )
    from agent_handoff.render import parse_bundle_markdown

    b2 = parse_bundle_markdown(render_markdown(b))
    assert b2.meta.provider == "builtin:bigmodel-start-plan"
    assert b2.meta.parent_session_id == "sess_parent"
    assert b2.meta.notes == ["account:work"]

    from agent_handoff.resume import render_brief

    brief = render_brief(b)
    assert "parent session: sess_parent" in brief
    assert "provider: builtin:bigmodel-start-plan" in brief
    assert "account:work" in brief
