"""Search index behaviour: coverage, ranking, caching, and two shipped bugs.

Everything runs against synthetic in-memory sessions — no real transcripts are
read in tests (Contributing rule 5).

Note the deliberate split these tests encode: ``search_cached`` reads the index
only (what the cockpit does on every keystroke, so it must never block), while
``build_index`` / ``search_with_stats`` are the ones that pay for stores.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pytest

from agent_handoff import search as S
from agent_handoff.indexstore import IndexStore
from agent_handoff.model import Message, RawSession, SessionMeta
from agent_handoff.parsers.base import Parser


@dataclass
class _FakeParser(Parser):
    """Minimal in-memory Parser double; ``loads`` records how often it was paid."""

    cli: str = "fake"
    sessions: list[SessionMeta] = field(default_factory=list)
    bodies: dict[str, str] = field(default_factory=dict)
    loads: dict[str, int] = field(default_factory=dict)
    unparseable: set[str] = field(default_factory=set)

    def list_sessions(self) -> list[SessionMeta]:
        return list(self.sessions)

    def load(self, session_id: str) -> RawSession | None:
        self.loads[session_id] = self.loads.get(session_id, 0) + 1
        if session_id in self.unparseable:
            return None
        meta = next(m for m in self.sessions if m.session_id == session_id)
        text = self.bodies.get(session_id, "")
        return RawSession(
            meta=meta,
            messages=[Message(role="user", text=text)] if text else [],
            files_touched=["src/zzz_quantum_loader.py"],
        )


def _meta(
    sid: str,
    title: str,
    *,
    cli: str = "fake",
    cwd: str = "D:/demo",
    updated: str = "2026-08-30T10:00:00+00:00",
    source: str = "",
) -> SessionMeta:
    return SessionMeta(
        cli=cli,
        session_id=sid,
        title=title,
        cwd=cwd,
        started_at="2026-08-30T09:00:00+00:00",
        updated_at=updated,
        source_path=source or f"/store/{sid}.jsonl",
    )


@pytest.fixture
def parsers(tmp_path):
    """Two CLIs; `fake` also holds an archived roll copy sharing one session id."""
    a = _FakeParser(
        cli="fake",
        sessions=[
            _meta("s1", "Fix the login loop"),
            _meta("s2", "Retune colour space", updated="2026-08-30T11:00:00+00:00"),
            _meta(
                "s2",
                "Retune colour space",
                updated="2026-08-30T11:00:00+00:00",
                source="/archive/roll1/s2.jsonl",
            ),
            _meta("s3", "Broken session", updated="2026-08-30T12:00:00+00:00"),
        ],
        bodies={
            "s1": "The middleware ordering caused the redirect loop.",
            "s2": "nothing relevant here but a mention of zebra-print rendering",
            "s3": "unreachable",
        },
        unparseable={"s3"},
    )
    b = _FakeParser(
        cli="other",
        sessions=[
            _meta(
                "o1",
                "Zebra migrations",
                cli="other",
                cwd="D:/other",
                updated="2026-08-29T10:00:00+00:00",
            )
        ],
        bodies={"o1": "plain body"},
    )
    S.reset_index(disk=False)
    S._STORE = IndexStore(tmp_path / "index.sqlite3")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(S, "available_parsers", lambda: [a, b])
        yield a, b
    S.reset_index(disk=False)


# -- fast mode ------------------------------------------------------------------


def test_fast_mode_matches_metadata_only(parsers):
    a, _b = parsers
    hits, stats = S.search_cached("login", mode="fast")
    assert [h.session_id for h in hits] == ["s1"]
    assert hits[0].matched == "title"
    assert a.loads == {}, "fast mode must not load a session"
    assert stats.mode == "fast"


def test_fast_mode_misses_body_text(parsers):
    hits, _ = S.search_cached("zebra-print", mode="fast")
    assert hits == []


def test_fast_mode_matches_cwd_and_model(parsers):
    _a, _b = parsers
    hits, _ = S.search_cached("D:/other", mode="fast")
    assert [h.session_id for h in hits] == ["o1"]


# -- full mode ------------------------------------------------------------------


def test_cold_full_search_reports_idle_instead_of_blocking(parsers):
    """The cockpit's first full-text query must return fast and say it is partial."""
    a, _b = parsers
    hits, stats = S.search_cached("zebra-print", mode="full")
    assert hits == []
    assert stats.index_state == "idle"
    assert stats.indexed == 0
    assert a.loads == {}, "search_cached never touches the stores"


def test_full_mode_finds_body_text_after_a_build(parsers):
    S.build_index()
    hits, stats = S.search_cached("zebra-print", mode="full")
    assert hits and hits[0].matched == "body"
    assert "zebra-print" in hits[0].excerpt
    assert stats.index_state == "ready"
    assert stats.indexed >= 1


def test_title_hit_outranks_body_hit(parsers):
    S.build_index()
    hits, _ = S.search_cached("zebra", mode="full")
    assert [h.session_id for h in hits] == ["o1", "s2", "s2"]  # title beats bodies
    assert hits[0].score > hits[1].score


def test_file_anchors_are_searchable(parsers):
    S.build_index()
    hits, _ = S.search_cached("quantum_loader", mode="full")
    assert hits and all("file" in h.matched for h in hits)


def test_same_session_id_in_two_store_files_is_not_lost(parsers):
    """Regression: the index was keyed (cli, sid), so an archived roll copy of s2
    overwrote the live one — a session silently vanished from search and the
    loser got re-parsed on every query (measured 4 s steady state at 453 sessions).
    """
    a, _b = parsers
    S.build_index()
    hits, _ = S.search_cached("colour space", mode="full")
    assert len(hits) == 2, "both the live and the archived copy stay findable"
    assert S._INDEX.size() == 5, "five listing rows must yield five index entries"
    loads_after_build = dict(a.loads)
    S.build_index()
    assert a.loads == loads_after_build, "nothing may be re-parsed on a warm rebuild"


def test_unparseable_session_is_still_title_searchable_and_not_reparsed(parsers):
    a, _b = parsers
    S.build_index()
    first = dict(a.loads)
    hits, _ = S.search_cached("broken", mode="full")
    assert hits and hits[0].session_id == "s3"
    S.build_index()
    assert a.loads == first, "a known-empty session must not be re-parsed"


def test_changed_fingerprint_reindexes(parsers):
    a, _b = parsers
    S.build_index()
    before = a.loads.get("s2", 0)
    a.sessions[1].updated_at = "2026-08-30T13:00:00+00:00"  # the session grew
    a.bodies["s2"] = "now mentions platypus rendering"
    S.build_index()
    hits, _ = S.search_cached("platypus", mode="full")
    assert hits and a.loads.get("s2", 0) > before


def test_query_shorter_than_two_chars_does_no_work(parsers):
    a, _b = parsers
    hits, stats = S.search_cached("z", mode="full")
    assert hits == [] and a.loads == {} and stats.scanned == 0


def test_cli_filter_is_respected(parsers):
    S.build_index()
    hits, _ = S.search_cached("zebra", cli="other", mode="full")
    assert {h.cli for h in hits} == {"other"}


def test_store_identity_wins_over_a_parser_that_mislabels_meta_cli(parsers):
    """The parser owns the store, so its cli id is authoritative for filtering.

    A parser that forgets to fill ``meta.cli`` used to become invisible to
    ``--cli`` queries; the index key now comes from the parser.
    """
    a, _b = parsers
    a.sessions[0].cli = ""  # a parser bug we must not amplify
    S.build_index()
    hits, _ = S.search_cached("login", cli="fake", mode="full")
    assert "s1" in {h.session_id for h in hits}


def test_ranking_is_deterministic(parsers):
    S.build_index()
    first, _ = S.search_cached("the", mode="full")
    second, _ = S.search_cached("the", mode="full")
    assert [(h.cli, h.session_id, h.score) for h in first] == [
        (h.cli, h.session_id, h.score) for h in second
    ]


# -- build / warm / persist -------------------------------------------------------


def test_warm_async_returns_before_the_build_finishes(parsers):
    status = S.warm_async()
    assert status["state"] in ("building", "ready")
    assert status["done"] <= status["total"]
    for _ in range(200):
        if S.index_status()["state"] != "building":
            break
        time.sleep(0.02)
    final = S.index_status()
    assert final["state"] == "ready"
    assert final["indexed"] == 5


def test_blocking_cli_search_refreshes(parsers):
    hits, stats = S.search_with_stats("platypus-ish", mode="full")
    assert stats.refreshed is True and stats.index_state == "ready"
    assert hits == []


def test_persistence_avoids_a_second_cold_parse(parsers):
    """The CLI is a new process per run; without the on-disk index every
    ``handoff search --body`` paid the full cold pass again (measured 15 s)."""
    a, _b = parsers
    S.build_index()
    assert S._STORE.stats()["rows"] > 0
    S._INDEX.clear()  # simulate process restart: memory gone, disk stays
    loads_before = dict(a.loads)
    S.build_index()
    assert a.loads == loads_before, "a restart must rehydrate from disk, not re-parse"
    hits, _ = S.search_cached("zebra", mode="full")
    assert hits


def test_reset_index_disk_false_keeps_the_persistent_copy(parsers):
    S.build_index()
    rows = S._STORE.stats()["rows"]
    S.reset_index(disk=False)
    assert S.index_status()["indexed"] == 0
    assert S._STORE.stats()["rows"] == rows
