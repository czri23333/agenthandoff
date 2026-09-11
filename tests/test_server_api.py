"""Cockpit REST contract tests (TestClient, no network, synthetic stores).

These cover the API surface the frontend is written against — including two
shape decisions that exist for honesty/REST reasons:

* ``/api/search`` answers ``{hits, stats}`` so the UI can show coverage instead
  of presenting a partial scan as a complete answer;
* ``/api/backup`` is POST-only because it writes to disk.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

# Guard before import: without the [server] extra this module must skip, not fail
# at collection time. (Importing the app first is exactly what broke CI.)
pytest.importorskip("fastapi", reason="agenthandoff[server] extra not installed")
pytest.importorskip("httpx", reason="fastapi TestClient needs httpx")

from agent_handoff.server.app import app  # noqa: E402

Client = pytest.importorskip("fastapi.testclient", reason="agenthandoff[server]").TestClient


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


def test_built_js_serves_as_javascript_not_text_plain(client):
    """Windows registries may map .js to text/plain; browsers then refuse the
    module scripts and the cockpit boots blank. The server pins web types."""
    from agent_handoff.server.app import _static_dir

    d = _static_dir()
    assert d is not None
    names = sorted(p.name for p in (d / "assets").glob("*.js"))
    assert names, "built frontend missing from the package"
    r = client.get(f"/assets/{names[0]}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/javascript"), r.headers["content-type"]


def test_unknown_session_detail_is_404_not_500(client):
    assert client.get("/api/sessions/zcode/nope-nope/detail").status_code == 404


def test_inbox_is_empty_by_default(client, monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    import agent_handoff.exchange as ex

    monkeypatch.setattr(ex.Path, "home", classmethod(lambda cls: tmp_path))
    assert client.get("/api/inbox", params={"global_scope": True}).json() == []
def test_detail_carries_the_budget_block(client, monkeypatch):
    """The cockpit gauge is only as honest as this payload's contract.

    A previous edit dropped the field silently - a file restored from an older
    revision - and nothing failed: the UI simply stopped showing a budget. So the
    shape is asserted here, with a stub parser instead of this machine's stores.
    """
    from agent_handoff import server
    from agent_handoff.model import Message, RawSession, SessionMeta

    raw = RawSession(
        meta=SessionMeta(
            cli="zcode",
            session_id="sess_budget",
            title="budgeted",
            cwd="D:/demo",
            notes=["context_window:1000"],
        ),
        messages=[Message(role="user", text="go", at="2026-08-31T00:00:00+00:00")],
    )

    class StubParser:
        cli = "zcode"

        def last_request_tokens(self, session_id):
            return {"input_tokens": 640}

        def usage(self, session_id):
            return {"models": [], "totals": {"calls": 2, "tokens_in": 900, "tokens_out": 40}}

    monkeypatch.setattr(server.app, "_raw_or_404", lambda cli, sid: raw)
    monkeypatch.setattr(server.app, "_parser_or_404", lambda cli: StubParser())
    detail = client.get("/api/sessions/zcode/sess_budget/detail").json()

    assert "budget" in detail, "the detail payload lost its budget block"
    budget = detail["budget"]
    assert set(budget) >= {"fill", "basis", "turns", "fired", "pending"}
    assert budget["turns"] == 1
    assert budget["fill"] == pytest.approx(0.64)
    assert "1000" in budget["basis"]
    assert budget["fired"] == [] and "45%" in budget["pending"]


def test_raw_zip_endpoint_carries_verbatim_files(client, monkeypatch):
    """The zip is the unfiltered truth: the vendor's own lines, hash-tagged."""
    import io
    import zipfile

    from agent_handoff import server

    payload = "{\"type\":\"user\",\"text\":\"original bytes\"}\n"
    import hashlib

    class StubRawParser:
        cli = "qodercn-ide"

        def raw_archive(self, session_id):
            if session_id == "sess_raw":
                return [{
                    "path": "D----x/transcript/sess_raw.jsonl",
                    "encoding": "utf-8",
                    "sha256": hashlib.sha256(payload.encode()).hexdigest(),
                    "text": payload,
                }]
            return None

    monkeypatch.setattr(server.app, "_parser_or_404", lambda cli: StubRawParser())
    r = client.get("/api/sessions/qodercn-ide/sess_raw/raw")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.read("D----x/transcript/sess_raw.jsonl") == payload.encode()

    # unsupported (archive None) is a 404, not a silent empty zip
    assert client.get("/api/sessions/qodercn-ide/nope/raw").status_code == 404



def test_sessions_delta_and_etag(client, monkeypatch):
    """Incremental poll: full list carries ETag; since= returns only changes."""
    from agent_handoff import model as M

    metas = [
        M.SessionMeta(cli="zcode", session_id="s-old", title="old", cwd="D:/d",
                      updated_at="2026-01-01T00:00:00+00:00"),
        M.SessionMeta(cli="zcode", session_id="s-new", title="new", cwd="D:/d",
                      updated_at="2026-09-03T00:00:00+00:00"),
    ]

    class FakeParser:
        cli = "zcode"

        def list_sessions(self):
            return metas

        def peek_status(self, sid):
            return None

        def peek_needs_reply(self, sid):
            return None

    monkeypatch.setattr("agent_handoff.server.app.all_parsers", lambda: [FakeParser()])
    monkeypatch.setattr("agent_handoff.server.app._git_info", lambda cwd: {})
    r = client.get("/api/sessions")
    assert r.status_code == 200
    assert r.headers.get("etag")
    assert isinstance(r.json(), list) and len(r.json()) == 2
    r304 = client.get("/api/sessions", headers={"If-None-Match": r.headers["etag"]})
    assert r304.status_code == 304
    d = client.get("/api/sessions", params={"since": "2026-06-01T00:00:00+00:00"}).json()
    assert sorted(d.keys()) == ["changed", "snapshot"]
    assert [s["session_id"] for s in d["changed"]] == ["s-new"]


# ── The list cache: one build at a time, and a stale answer beats a queue ────
#
# Measured on the maintainer's machine before this: a cold build was 5.7s of CPU
# over 802 metas, the frontend polls every 30s per open tab, and nothing stopped
# two requests from building at once. A handful of tabs kept several builds in
# flight, the thread pool saturated, and `/api/stores` — which does nothing —
# took 8.7s to answer while `/api/sessions` timed out at 150s.


@pytest.fixture
def clean_session_cache():
    from agent_handoff.server import app as A

    A._sessions_cache.clear()
    A._sessions_locks.clear()
    yield A
    A._sessions_cache.clear()
    A._sessions_locks.clear()


def test_concurrent_callers_share_one_session_build(clean_session_cache, monkeypatch):
    import threading

    A = clean_session_cache
    calls: list[int] = []

    def slow_build(cli, cwd, q):
        calls.append(1)
        time.sleep(0.3)
        return [{"cli": "zcode", "session_id": "s1"}]

    monkeypatch.setattr(A, "_build_session_roots", slow_build)
    results: list[list] = []

    def worker():
        results.append(A._session_roots(None, None, None))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(calls) == 1, f"expected one build, got {len(calls)}"
    assert results and all(r == results[0] for r in results)
    assert results[0] == [{"cli": "zcode", "session_id": "s1"}]


def test_a_stale_list_answers_while_the_refresh_is_still_running(
    clean_session_cache, monkeypatch
):
    import threading

    A = clean_session_cache
    stale = [{"cli": "zcode", "session_id": "old"}]
    A._sessions_cache["None|None|None"] = (
        time.monotonic() - A._CACHE_TTL - 1.0,
        stale,
    )
    calls: list[int] = []

    def slow_build(cli, cwd, q):
        calls.append(1)
        time.sleep(0.5)
        return [{"cli": "zcode", "session_id": "new"}]

    monkeypatch.setattr(A, "_build_session_roots", slow_build)
    refresh = threading.Thread(target=lambda: A._session_roots(None, None, None))
    refresh.start()
    time.sleep(0.08)  # let the refreshing caller take the lock

    started = time.perf_counter()
    answer = A._session_roots(None, None, None)
    elapsed = time.perf_counter() - started
    refresh.join()

    assert answer == stale, "a second caller should be served the cached list"
    assert elapsed < 0.2, f"it waited {elapsed:.2f}s for someone else's build"
    assert len(calls) == 1, f"expected one refresh, got {len(calls)}"


# ── The thread view: an answer, with a number attached ──────────────────────
#
# Clustering needs each session's touched files, which costs one full `load()`
# per session: measured 189ms each over 802 sessions, ~150s, and the view sat on
# "clustering…" for two minutes because of it. The pass now runs under a budget
# and reports what it covered, so these two tests are about the budget and the
# increment, not about the clustering algorithm.


def test_threads_respect_the_time_budget_and_say_what_they_covered(
    client, monkeypatch, clean_session_cache
):
    from agent_handoff import model as M
    from agent_handoff.server import app as A

    A._threads_cache.clear()
    A._files_cache.clear()
    monkeypatch.setattr(A, "_THREADS_BUDGET", 0.25)

    metas = [
        M.SessionMeta(
            cli="zcode",
            session_id=f"s{i:02d}",
            title=f"task {i}",
            cwd="D:/d",
            updated_at=f"2026-09-{i + 1:02d}T00:00:00+00:00",
        )
        for i in range(20)
    ]
    loads: list[str] = []

    class SlowParser:
        cli = "zcode"

        def list_sessions(self):
            return metas

        def load(self, sid):
            loads.append(sid)
            time.sleep(0.05)
            return None  # no files; the point here is the cost, not the content

        def peek_status(self, sid):
            return None

        def peek_needs_reply(self, sid):
            return None

    monkeypatch.setattr(A, "all_parsers", lambda: [SlowParser()])
    monkeypatch.setattr(A, "build_threads", lambda nodes, **kw: [])

    body = client.get("/api/threads").json()
    coverage = body["coverage"]
    assert coverage["sessions"] == 20
    assert 0 < coverage["with_files"] < 20, coverage
    assert coverage["budget_hit"] is True
    assert coverage["seconds"] <= 2.0, coverage
    first_batch = list(loads)
    assert len(first_batch) == coverage["with_files"]

    # The second call pays only for what it had not read yet: the first batch is
    # cached, so `loads` grows by another batch rather than repeating the first.
    more = client.get("/api/threads/refresh").json()["coverage"]
    assert more["with_files"] > coverage["with_files"], (coverage, more)
    assert loads[: len(first_batch)] == first_batch


def test_threads_reuse_the_file_cache_across_calls(client, monkeypatch, clean_session_cache):
    from agent_handoff import model as M
    from agent_handoff.server import app as A

    A._threads_cache.clear()
    A._files_cache.clear()
    metas = [
        M.SessionMeta(
            cli="zcode", session_id="s1", title="t", cwd="D:/d",
            updated_at="2026-09-01T00:00:00+00:00",
        )
    ]
    loads: list[str] = []

    class TinyParser:
        cli = "zcode"

        def list_sessions(self):
            return metas

        def load(self, sid):
            loads.append(sid)
            return None

        def peek_status(self, sid):
            return None

        def peek_needs_reply(self, sid):
            return None

    monkeypatch.setattr(A, "all_parsers", lambda: [TinyParser()])
    monkeypatch.setattr(A, "build_threads", lambda nodes, **kw: [])
    client.get("/api/threads")
    assert loads == ["s1"]
    client.get("/api/threads/refresh")
    assert loads == ["s1"], "a second pass must not re-read a cached session"


def test_git_info_reads_head_instead_of_spawning_git(tmp_path):
    """The branch is a line in `.git/HEAD`; the old code spawned two processes."""
    from agent_handoff.server import app as A

    repo = tmp_path / "plain"
    (repo / ".git" / "refs" / "heads").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    assert A._git_info_from_files(str(repo)) == {"branch": "main"}

    # A linked worktree: `.git` is a file, and `commondir` points at the host.
    host = tmp_path / "host"
    (host / ".git" / "worktrees" / "wt1").mkdir(parents=True)
    (host / ".git" / "worktrees" / "wt2").mkdir(parents=True)
    wt = tmp_path / "wt"
    wt.mkdir()
    gitfile = wt / ".git"
    gitfile.write_text(
        f"gitdir: {(host / '.git' / 'worktrees' / 'wt1').as_posix()}\n",
        encoding="utf-8",
    )
    (host / ".git" / "worktrees" / "wt1" / "HEAD").write_text(
        "ref: refs/heads/feature/x\n", encoding="utf-8"
    )
    (host / ".git" / "worktrees" / "wt1" / "commondir").write_text(
        "../..\n", encoding="utf-8"
    )
    assert A._git_info_from_files(str(wt)) == {
        "branch": "feature/x",
        "worktree_count": 3,
    }

    # Detached HEAD answers exactly what `git branch --show-current` answers.
    detached = tmp_path / "detached"
    (detached / ".git").mkdir(parents=True)
    (detached / ".git" / "HEAD").write_text(
        "0123456789abcdef0123456789abcdef01234567\n", encoding="utf-8"
    )
    assert A._git_info_from_files(str(detached)) == {}

    # Shapes the fast path declines, so `git` still gets asked.
    assert A._git_info_from_files(str(tmp_path / "missing")) == {}
    assert A._git_info_from_files("relative/path") == {}
    packed = tmp_path / "packed"
    (packed / ".git").mkdir(parents=True)
    (packed / ".git" / "HEAD").write_text("ref: refs/tags/v1\n", encoding="utf-8")
    assert A._git_info_from_files(str(packed)) is None

    # And on this repository: the shape is understood (not declined), and if it
    # names a branch that branch is a non-empty string.
    here = A._git_info_from_files(str(Path(__file__).resolve().parent.parent))
    assert here is not None
    if "branch" in here:
        assert here["branch"]
