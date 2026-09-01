"""Concurrency of the search index, which the gap list called untested.

The cockpit's shape is one background writer and many readers on a single WAL
SQLite file, plus the possibility of two cockpit instances pointed at the same
index. None of that had coverage. These tests run the real threads and a real
second process, and assert the properties that matter: a reader never blocks or
sees a torn answer, every write survives, the file stays intact, and a build is
not paid for twice.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import threading
from dataclasses import dataclass, field

from agent_handoff import search as S
from agent_handoff.indexstore import IndexStore
from agent_handoff.model import Message, RawSession, SessionMeta
from agent_handoff.parsers.base import Parser

SESSIONS = 12


@dataclass
class _Parser(Parser):
    cli: str = "fake"
    sessions: list[SessionMeta] = field(default_factory=list)
    loads: dict[str, int] = field(default_factory=dict)

    def list_sessions(self) -> list[SessionMeta]:
        return list(self.sessions)

    slow: float = 0.0

    def load(self, session_id: str) -> RawSession | None:
        # Not thread-safe on purpose: a duplicate build shows up as a doubled
        # count here. The optional delay widens the "building" window so the
        # single-flight promise of warm_async is observable without sleeping on
        # luck.
        if self.slow:
            import time as _time

            _time.sleep(self.slow)
        self.loads[session_id] = self.loads.get(session_id, 0) + 1
        meta = next(m for m in self.sessions if m.session_id == session_id)
        return RawSession(
            meta=meta,
            messages=[Message(role="user", text=f"quantum loader {session_id}")],
            files_touched=["src/zzz_quantum_loader.py"],
        )


def _fixture_parser() -> _Parser:
    sessions = [
        SessionMeta(
            cli="fake",
            session_id=f"s{index}",
            title=f"session {index}",
            cwd="D:/demo",
            updated_at="2026-08-30T10:00:00+00:00",
            source_path=f"D:/demo/s{index}.jsonl",
        )
        for index in range(SESSIONS)
    ]
    return _Parser(sessions=sessions)


def test_readers_never_block_a_writer(tmp_path, monkeypatch):
    parser = _fixture_parser()
    S.reset_index(disk=False)
    monkeypatch.setattr(S, "_STORE", IndexStore(tmp_path / "idx.sqlite3"))
    monkeypatch.setattr(S, "_LISTING", (0.0, []))
    monkeypatch.setattr(S, "available_parsers", lambda: [parser])

    errors: list[BaseException] = []

    def reader() -> None:
        try:
            for _ in range(40):
                # A keystroke-time search must not block on the build, and must
                # answer with a hit list even while rows are being written.
                hits, stats = S.search_cached("quantum")
                assert isinstance(hits, list)
                assert stats.index_state in ("idle", "building", "ready", "failed")
        except BaseException as exc:  # noqa: BLE001 - collected and re-raised below
            errors.append(exc)

    def writer() -> None:
        try:
            S.build_index()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer)] + [
        threading.Thread(target=reader) for _ in range(6)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)

    assert not errors, errors
    assert S.index_status()["state"] in ("ready", "idle")
    final_hits, final_stats = S.search_cached("quantum")
    assert len(final_hits) == SESSIONS, "a concurrent build lost sessions"
    assert final_stats.indexed == SESSIONS


def test_warm_async_is_single_flight(tmp_path, monkeypatch):
    """Extra warm requests while a build is in flight must not rebuild.

    This is the promise the cockpit relies on: a dashboard open in three windows
    polling `searchWarm` at once must pay for exactly one indexing pass. A slow
    parser keeps the build in flight long enough to assert against deterministically.
    """
    import time

    parser = _Parser(sessions=_fixture_parser().sessions, slow=0.03)
    S.reset_index(disk=False)
    monkeypatch.setattr(S, "_STORE", IndexStore(tmp_path / "idx.sqlite3"))
    monkeypatch.setattr(S, "available_parsers", lambda: [parser])

    S.warm_async()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and S.index_status()["state"] != "building":
        time.sleep(0.01)
    assert S.index_status()["state"] == "building", "the build never started"

    for _ in range(3):
        status = S.warm_async()
        assert status["state"] == "building", "warm_async started a second build"

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and S.index_status()["state"] == "building":
        time.sleep(0.01)

    loaded = sum(parser.loads.values())
    assert loaded == SESSIONS, f"{loaded} loads for {SESSIONS} sessions: warm double-built"


def test_concurrent_writers_keep_every_row(tmp_path):
    store = IndexStore(tmp_path / "idx.sqlite3")
    errors: list[BaseException] = []

    def write(worker: int) -> None:
        try:
            for row in range(25):
                sid = f"w{worker}-s{row}"
                store.put("fake", sid, f"D:/demo/{sid}.jsonl", "fp1", f"body {sid}", "[]")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=write, args=[worker]) for worker in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)

    assert not errors, errors
    for worker in range(4):
        for row in range(25):
            sid = f"w{worker}-s{row}"
            assert store.get("fake", sid, f"D:/demo/{sid}.jsonl", "fp1"), f"lost {sid}"
    with sqlite3.connect(tmp_path / "idx.sqlite3") as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_two_processes_writing_one_index(tmp_path):
    """The 'cockpit open twice' case: separate processes, one WAL file.

    Run in several rounds against fresh databases because the failure this guards
    (a lost write under startup contention) is intermittent. Each writer must
    report every put as persisted, and the store's write_failures counter must
    stay at zero - that counter exists precisely so a dropped write cannot be
    pretended away.
    """
    script = (
        "import sys;"
        "sys.path.insert(0, 'src');"
        "from agent_handoff.indexstore import IndexStore;"
        "store = IndexStore(sys.argv[1]);"
        "fails = [i for i in range(40) if not store.put('fake',"
        " f'{sys.argv[2]}-s{i}', f'{sys.argv[2]}-s{i}.jsonl', 'fp', f'body {i}', '[]')];"
        "wf = store.stats().get('write_failures', -1);"
        "print(f'{len(fails)}:{wf}')"
    )
    for round_no in range(4):
        path = tmp_path / f"round{round_no}.sqlite3"
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(path), f"p{index}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            for index in range(2)
        ]
        reports = []
        for proc in procs:
            assert proc.wait(120) == 0, f"round {round_no}: a writer died on the shared index"
            out = proc.stdout.read().decode("utf-8", "replace").strip()
            reports.append(out)
        for index, report in enumerate(reports):
            failed, write_failures = report.split(":")
            assert failed == "0", (
                f"round {round_no} writer p{index} lost puts: {report}"
            )
            assert write_failures == "0", (
                f"round {round_no} writer p{index} counted write failures: {report}"
            )

        store = IndexStore(path)
        for index in range(2):
            for row in range(40):
                sid = f"p{index}-s{row}"
                assert store.get("fake", sid, f"{sid}.jsonl", "fp"), (
                    f"round {round_no}: lost {sid}"
                )
        with sqlite3.connect(path) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
