"""Cockpit REST contract tests (TestClient, no network, synthetic stores).

These cover the API surface the frontend is written against — including two
shape decisions that exist for honesty/REST reasons:

* ``/api/search`` answers ``{hits, stats}`` so the UI can show coverage instead
  of presenting a partial scan as a complete answer;
* ``/api/backup`` is POST-only because it writes to disk.
"""

from __future__ import annotations

import pytest

from agent_handoff.server.app import app

fastapi_testclient = pytest.importorskip("fastapi.testclient", reason="agenthandoff[server]")
Client = fastapi_testclient.TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A cockpit that cannot see this machine's real session stores.

    Without this, a single ``/api/search`` call would walk (and index) every CLI
    store on the test host — slow, and a test must never read real transcripts.
    """
    from agent_handoff import search as S
    from agent_handoff.indexstore import IndexStore

    S.reset_index(disk=False)
    monkeypatch.setattr(S, "_STORE", IndexStore(tmp_path / "idx.sqlite3"))
    monkeypatch.setattr(S, "available_parsers", lambda: [])
    monkeypatch.setattr(S, "_LISTING", (0.0, []))
    monkeypatch.setattr("agent_handoff.server.app.discover", lambda: [])
    monkeypatch.setattr("agent_handoff.server.app.all_parsers", lambda: [])
    with Client(app) as c:
        yield c


def test_search_rejects_one_character_queries(client):
    r = client.get("/api/search", params={"q": "a"})
    assert r.status_code == 400
    assert "2" in r.json()["detail"]


def test_search_rejects_unknown_mode(client):
    assert client.get("/api/search", params={"q": "abc", "mode": "fuzzy"}).status_code == 400


def test_search_returns_hits_and_coverage_stats(client, monkeypatch):
    from agent_handoff import search as S
    from agent_handoff.search import SearchHit, SearchStats

    hit = SearchHit(
        cli="zcode",
        session_id="s1",
        title="Fix login",
        cwd="D:/demo",
        updated_at="2026-08-30T10:00:00+00:00",
        score=30,
        excerpt="…",
        matched="title",
    )
    stats = SearchStats(
        mode="full", scanned=42, total=42, indexed=42, took_ms=7, index_state="ready"
    )
    monkeypatch.setattr(S, "search_cached", lambda *a, **kw: ([hit], stats))
    body = client.get("/api/search", params={"q": "login"}).json()
    assert body["stats"]["index_state"] == "ready"
    assert body["hits"][0]["session_id"] == "s1"
    assert body["hits"][0]["matched"] == "title"


def test_search_status_exposes_index_progress_shape(client):
    body = client.get("/api/search/status").json()
    assert set(body) >= {"state", "done", "total", "indexed", "error", "persisted"}


def test_warm_endpoint_returns_immediately(client, monkeypatch):
    from agent_handoff import search as S

    monkeypatch.setattr(
        S, "warm_async", lambda cli=None: {"state": "building", "done": 1, "total": 2}
    )
    body = client.post("/api/search/warm", json={}).json()
    assert body["state"] == "building"


def test_backup_is_post_only(client):
    """A GET that writes to disk is a cache/prefetch hazard; reviewers flag it."""
    assert client.get("/api/backup").status_code == 405
    assert client.head("/api/backup").status_code == 405


def test_backup_writes_only_under_our_state_dir(client, monkeypatch, tmp_path):
    from pathlib import Path

    import agent_handoff.backup as B

    monkeypatch.setattr(B.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(B, "discover", lambda: [])
    body = client.post("/api/backup", json={}).json()
    out = Path(body["path"])
    assert out.is_dir() and tmp_path in out.parents
    assert (out / "manifest.json").is_file()


def test_heartbeat_counts_sessions(client):
    assert client.get("/api/heartbeat").json() == {"sessions": 0}


def test_launcher_registry_answers_verified_and_unknown(client):
    ok = client.get("/api/launcher/dsh/abc123").json()
    assert ok["kind"] == "verified"
    assert ok["command"] == "dsh --resume abc123"
    assert client.get("/api/launcher/nosuchcli/abc").status_code == 404


def test_stores_endpoint_is_a_list_of_readables(client):
    assert client.get("/api/stores").json() == []


def test_cockpit_html_ships_with_the_package(client):
    """A clean clone must serve the UI without running node."""
    r = client.get("/")
    assert r.status_code == 200
    assert "agenthandoff cockpit" in r.text
    assert 'src="/assets/' in r.text


def test_unknown_session_detail_is_404_not_500(client):
    assert client.get("/api/sessions/zcode/nope-nope/detail").status_code == 404


def test_inbox_is_empty_by_default(client, monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    import agent_handoff.exchange as ex

    monkeypatch.setattr(ex.Path, "home", classmethod(lambda cls: tmp_path))
    assert client.get("/api/inbox", params={"global_scope": True}).json() == []
