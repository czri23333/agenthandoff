"""Index persistence: roundtrip, self-healing migration, and graceful absence.

The store is a cache, so every failure mode has to degrade to "rebuild" rather
than "crash" — a search tool that cannot write its cache still has to search.
"""

from __future__ import annotations

import sqlite3

from agent_handoff.indexstore import _ENTRIES_DDL, IndexStore, index_path


def test_roundtrip_and_fingerprint_gate(tmp_path):
    store = IndexStore(tmp_path / "idx.sqlite3")
    assert store.available
    store.put("zcode", "s1", "/store/s1.jsonl", "fp-1", "hello 世界", "a.py\nb.py")
    assert store.get("zcode", "s1", "/store/s1.jsonl", "fp-1") == ("hello 世界", "a.py\nb.py")
    assert store.get("zcode", "s1", "/store/s1.jsonl", "fp-2") is None, "stale fp must miss"
    assert store.get("zcode", "s1", "/other/path.jsonl", "fp-1") is None, "src is part of the key"


def test_text_is_compressed_on_disk(tmp_path):
    store = IndexStore(tmp_path / "idx.sqlite3")
    hay = "the same sentence. " * 5000
    store.put("zcode", "big", "/p", "fp", hay, "")
    raw = sqlite3.connect(str(store.path))
    blob = raw.execute("SELECT hay FROM entries WHERE sid='big'").fetchone()[0]
    raw.close()
    assert len(blob) < len(hay.encode("utf-8")) / 4, "dialogue should compress hard"
    assert store.get("zcode", "big", "/p", "fp")[0] == hay


def test_schema_mismatch_repairs_itself(tmp_path):
    """Regression: an earlier build stamped schema_version=2 onto a v1-shaped
    table (CREATE TABLE IF NOT EXISTS never alters), and from then on every
    write failed forever. The version marker can lie, so check real columns."""
    path = tmp_path / "idx.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE entries (cli TEXT, sid TEXT, fp TEXT, hay BLOB, files BLOB,"
        " PRIMARY KEY (cli, sid))"
    )
    conn.execute("INSERT INTO meta VALUES ('schema_version', '2')")  # the lie
    conn.commit()
    conn.close()

    store = IndexStore(path)
    assert store.available
    store.put("zcode", "s9", "/p", "fp", "text", "files")  # would raise pre-fix
    assert store.get("zcode", "s9", "/p", "fp") == ("text", "files")
    assert store.stats()["rows"] == 1
    assert store.stats()["persisted"] is True


def test_clear_and_keys(tmp_path):
    store = IndexStore(tmp_path / "idx.sqlite3")
    store.put("a", "1", "/p1", "fp", "x", "y")
    store.put("b", "2", "/p2", "fp", "x", "y")
    assert sorted(store.keys()) == [("a", "1", "/p1"), ("b", "2", "/p2")]
    store.clear()
    assert store.keys() == []


def test_unwritable_location_degrades_to_memory_only(tmp_path):
    """A directory where the db file should be: no crash, just not persisted."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    store = IndexStore(blocked)  # path is a directory -> sqlite cannot open it
    assert store.available is False
    store.put("zcode", "s1", "/p", "fp", "text", "files")  # no raise
    assert store.get("zcode", "s1", "/p", "fp") is None
    stats = store.stats()
    assert stats["persisted"] is False
    assert "persist_error" in stats or "path" in stats


def test_build_note_roundtrip(tmp_path):
    store = IndexStore(tmp_path / "idx.sqlite3")
    assert store.last_build() is None
    store.note({"sessions": 12, "seconds": 1.5, "persisted": True})
    assert store.last_build()["sessions"] == 12


def test_index_lives_in_our_own_state_dir_never_in_a_cli_store():
    """The read-only promise, enforced: the only writable path is ~/.agenthandoff."""
    path = index_path()
    assert path.parent.name == ".agenthandoff"
    assert ".zcode" not in path.parts and ".claude" not in path.parts


def test_ddl_columns_match_the_documented_contract(tmp_path):
    store = IndexStore(tmp_path / "idx.sqlite3")
    assert store.available
    conn = sqlite3.connect(str(store.path))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(entries)")}
    conn.close()
    assert cols == {"cli", "sid", "src", "fp", "hay", "files"}
    assert "src" in _ENTRIES_DDL, "source path must stay part of the primary key"


def test_wal_mode_keeps_concurrent_readers_from_blocking(tmp_path):
    """The background index writer and the request threads share one db."""
    store = IndexStore(tmp_path / "idx.sqlite3")
    assert store.available
    conn = sqlite3.connect(str(store.path))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode.lower() == "wal"
