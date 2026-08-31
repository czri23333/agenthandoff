"""The watch ladder: fire on the right signal, once per rung, and not later.

Written against the scenario this exists for - a session that dies on quota - so
the assertions are about the failure modes that would actually hurt: a rung that
never fires (no snapshot when the death comes), a rung that fires repeatedly (a
directory full of near-identical briefs), and a fill estimate built from the wrong
number (cumulative tokens, which would claim every long session is at 100%).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_handoff import watch
from agent_handoff.model import Message, RawSession, SessionMeta

SID = "sess_watch_0123456789abcdef"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep state, snapshots and the vault inside the test's own tree."""
    monkeypatch.setenv("AGENTHANDOFF_HOME", str(tmp_path))
    return tmp_path


def make_raw(turns: int = 10, *, notes=(), tokens_in: int | None = None) -> RawSession:
    meta = SessionMeta(
        cli="fake",
        session_id=SID,
        title="watched session",
        cwd="/srv/project",
        started_at="2026-08-31T00:00:00+00:00",
        updated_at="2026-08-31T00:10:00+00:00",
        tokens_in=tokens_in,
        notes=list(notes),
    )
    messages = [
        Message(
            role="user" if index % 2 == 0 else "assistant",
            text=f"turn {index} " + ("payload " * 8),
            at=f"2026-08-31T00:{index % 60:02d}:00+00:00",
        )
        for index in range(turns)
    ]
    return RawSession(meta=meta, messages=messages)


class FakeParser:
    cli = "fake"

    def __init__(self, raw: RawSession | None, per_request: dict | None = None) -> None:
        self.raw = raw
        self.per_request = per_request or {}

    def load(self, session_id: str) -> RawSession | None:
        if self.raw is None or session_id != self.raw.meta.session_id:
            return None
        return self.raw

    def last_request_tokens(self, session_id: str) -> dict:
        return dict(self.per_request)


def test_unknown_window_falls_back_to_turn_rungs():
    parser = FakeParser(make_raw(turns=30))
    state = watch.WatchState(cli="fake", session_id=SID)
    assert watch.triggers(parser.raw, state, None) == ["t25"]


def test_rung_fires_once_and_remembers():
    raw = make_raw(turns=40, notes=["context_window:100000"])
    parser = FakeParser(raw, {"input_tokens": 50000})
    first = watch.watch_once(parser, SID)
    assert [item["rung"] for item in first["fired"]] == ["20%", "45%"]
    assert first["basis"] == "50000 of 100000 tokens"
    second = watch.watch_once(parser, SID)
    assert second["fired"] == [], "a rung refired on the same session"
    assert "70%" in second["pending"]


def test_cumulative_tokens_are_not_mistaken_for_context_fill():
    """Without a per-request figure the estimate is unknown, not inflated."""
    raw = make_raw(turns=40, notes=["context_window:1000"], tokens_in=999999)
    parser = FakeParser(raw)  # no per-request figure at all
    result = watch.watch_once(parser, SID)
    assert result["fill"] is None
    assert result["basis"] == "unknown"
    assert [item["rung"] for item in result["fired"]] == ["t25"]


def test_snapshot_is_a_readable_brief_and_a_lossless_archive():
    raw = make_raw(turns=80, notes=["context_window:100000"])
    parser = FakeParser(raw, {"input_tokens": 75000})
    result = watch.watch_once(parser, SID)
    paths = [item["path"] for item in result["fired"]]
    assert paths, "crossing 70% wrote nothing"
    brief = Path(paths[-1]).read_text(encoding="utf-8")
    assert "turn 79" in brief, "the newest turn is missing from the brief"
    assert result["fired"][-1]["vault"], "the lossless archive did not happen"


def test_watch_stops_when_the_session_disappears():
    parser = FakeParser(make_raw(turns=30))
    slept: list[float] = []
    result = watch.run(parser, SID, interval=1, iterations=3, sleep=slept.append)
    assert result["looks"] == 3
    parser.raw = None  # the store dropped it: compaction, cleanup, or a death
    gone = watch.run(parser, SID, interval=1, iterations=5, sleep=lambda _s: None)
    assert gone["looks"] == 1
    assert gone["last"]["status"] == "gone"


def test_ladder_state_survives_a_second_process(tmp_path):
    raw = make_raw(turns=10, notes=["context_window:100000"])
    parser = FakeParser(raw, {"input_tokens": 21000})
    watch.watch_once(parser, SID)
    reloaded = watch.load_state("fake", SID)
    assert "20%" in reloaded.fired
    assert reloaded.snapshots[-1].endswith(".md")
